import secrets
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_db
from app.models import ChatMessage, ChatRead, LoginLog, Notification, Session, User, UserRole
from app.rbac import AuthContext, get_current_auth
from app.realtime import hub, notify_outbox_signal, emit_outbox_event
from app.schemas import BootstrapAdminRequest, LoginRequest, ThemeUpdateRequest
from app.services import award_daily_login_score
from app.utils.jalali import format_jalali_label, utc_now
from app.utils.persian import normalize_digits_ascii
from app.utils.security import (
    check_rate_limit,
    clear_rate_limit,
    compute_avatar_color,
    extract_client_ip,
    generate_opaque_token,
    hash_password,
    hash_token,
    record_failed_login,
    verify_origin_header,
    verify_password,
    verify_preauth_csrf,
)

router = APIRouter(prefix="/api/v1/auth", tags=["احراز هویت"])


def _resolve_cookie_flags(request: Request) -> tuple[bool, str, bool]:
    settings = get_settings()
    xf_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    origin = request.headers.get("origin", "").lower()
    referer = request.headers.get("referer", "").lower()
    xf_host = request.headers.get("x-forwarded-host", "").lower()
    host = request.headers.get("host", "").lower()
    sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
    is_https_proxy = (
        xf_proto == "https"
        or request.url.scheme == "https"
        or origin.startswith("https://")
        or referer.startswith("https://")
        or ".run.app" in xf_host
        or ".run.app" in host
    )
    if (is_https_proxy and sec_fetch_site == "cross-site") or ".run.app" in xf_host or ".run.app" in host:
        return True, "none", True
    if settings.app_env == "production":
        return settings.cookie_secure, settings.cookie_samesite, False
    if is_https_proxy or sec_fetch_site == "cross-site":
        return True, "none", True
    return settings.cookie_secure, settings.cookie_samesite, False


def _mark_cookies_partitioned(response: Response) -> None:
    updated = []
    for key, val in response.raw_headers:
        if key.lower() == b"set-cookie" and (val.startswith(b"hb_session=") or val.startswith(b"hb_csrf=")):
            if b"partitioned" not in val.lower():
                val = val + b"; Partitioned"
        updated.append((key, val))
    response.raw_headers[:] = updated


def _set_auth_cookies(request: Request, response: Response, raw_session_token: str, csrf_token: str) -> None:
    settings = get_settings()
    secure, samesite, partitioned = _resolve_cookie_flags(request)
    response.set_cookie(
        key="hb_session",
        value=raw_session_token,
        httponly=True,
        secure=secure,
        samesite=samesite,
        path="/",
        max_age=settings.session_absolute_hours * 3600,
    )
    response.set_cookie(
        key="hb_csrf",
        value=csrf_token,
        httponly=False,
        secure=secure,
        samesite=samesite,
        path="/",
        max_age=settings.session_absolute_hours * 3600,
    )
    if partitioned:
        _mark_cookies_partitioned(response)


@router.get("/csrf")
async def issue_preauth_csrf(request: Request, response: Response) -> dict:
    token = generate_opaque_token()
    secure, samesite, partitioned = _resolve_cookie_flags(request)
    response.set_cookie(
        key="hb_csrf",
        value=token,
        httponly=False,
        secure=secure,
        samesite=samesite,
        path="/",
        max_age=3600,
    )
    if partitioned:
        _mark_cookies_partitioned(response)
    return {"csrf_token": token}


@router.get("/bootstrap-status")
async def get_bootstrap_status(db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()
    if settings.admin_initial_password:
        return {"needs_setup": False}
    user_count = int((await db.execute(select(func.count(User.id)))).scalar() or 0)
    return {"needs_setup": user_count == 0}


@router.post("/bootstrap-admin")
async def bootstrap_first_admin(
    payload: BootstrapAdminRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    verify_preauth_csrf(request)
    settings = get_settings()
    if settings.admin_initial_password:
        raise HTTPException(status_code=409, detail="راه‌اندازی اولیه قبلاً از طریق تنظیمات محیطی انجام شده است.")

    from sqlalchemy import text as sa_text
    await db.execute(sa_text("SELECT pg_advisory_xact_lock(982451)"))
    user_count = int((await db.execute(select(func.count(User.id)))).scalar() or 0)
    if user_count > 0:
        raise HTTPException(status_code=409, detail="حساب کاربری در سامانه ثبت شده است؛ از صفحه ورود استفاده کنید.")

    uname = normalize_digits_ascii(payload.username.strip())
    uname_lower = uname.lower()
    user = User(
        username=uname,
        username_lower=uname_lower,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
        job_title="مدیر سامانه و دفتر",
        department="مدیریت دفتر",
        display_access_level="supervisor",
        org_role_type="referral",
        avatar_color=compute_avatar_color(uname_lower + payload.display_name),
    )
    db.add(user)
    await db.flush()
    roles = ["admin", "manager"]
    for r in roles:
        db.add(UserRole(user_id=user.id, role=r))

    now = utc_now()
    session_id = secrets.token_urlsafe(24)
    raw_token = generate_opaque_token()
    csrf_token = generate_opaque_token()
    corr_id = secrets.token_hex(12)
    ip_addr = extract_client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]

    db.add(
        Session(
            id=session_id,
            user_id=user.id,
            token_hash=hash_token(raw_token),
            csrf_token=csrf_token,
            ip_address=ip_addr,
            user_agent=ua,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(minutes=settings.session_idle_minutes),
            absolute_expires_at=now + timedelta(hours=settings.session_absolute_hours),
            correlation_id=corr_id,
        )
    )
    db.add(
        LoginLog(
            user_id=user.id,
            username_snapshot=user.username,
            action="login",
            ip_address=ip_addr,
            user_agent=ua,
            correlation_id=corr_id,
            session_id=session_id,
            created_at=now,
        )
    )
    await db.commit()
    _set_auth_cookies(request, response, raw_token, csrf_token)
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "job_title": user.job_title,
            "department": user.department,
            "display_access_level": user.display_access_level,
            "org_role_type": user.org_role_type,
            "roles": sorted(roles),
            "avatar_color": user.avatar_color,
            "theme_preference": user.theme_preference,
        },
        "csrf_token": csrf_token,
    }


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    verify_preauth_csrf(request)
    settings = get_settings()

    ip_addr = extract_client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    uname_norm = normalize_digits_ascii(payload.username.strip()).lower()

    ip_bucket = f"ip:{ip_addr}"
    user_bucket = f"user:{uname_norm}"
    await check_rate_limit(db, ip_bucket)
    await check_rate_limit(db, user_bucket)

    stmt = (
        select(User)
        .options(selectinload(User.roles))
        .where(User.username_lower == uname_norm)
    )
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    invalid_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="نام کاربری یا رمز اشتباه است",
    )

    if user is None or user.is_deleted or not user.is_active:
        await record_failed_login(db, ip_bucket)
        await record_failed_login(db, user_bucket)
        await db.commit()
        raise invalid_exc

    if not verify_password(payload.password, user.password_hash):
        await record_failed_login(db, ip_bucket)
        await record_failed_login(db, user_bucket)
        await db.commit()
        raise invalid_exc

    # Rotate any prior cookie session if present
    old_raw = request.cookies.get("hb_session", "")
    if old_raw:
        old_hash = hash_token(old_raw)
        old_res = await db.execute(select(Session).where(Session.token_hash == old_hash, Session.revoked_at.is_(None)))
        old_sess = old_res.scalar_one_or_none()
        if old_sess:
            old_sess.revoked_at = utc_now()
            old_sess.revoke_reason = "rotated_on_login"

    await clear_rate_limit(db, ip_bucket)
    await clear_rate_limit(db, user_bucket)

    now = utc_now()
    session_id = secrets.token_urlsafe(24)
    raw_token = generate_opaque_token()
    csrf_token = generate_opaque_token()
    corr_id = secrets.token_hex(12)

    sess = Session(
        id=session_id,
        user_id=user.id,
        token_hash=hash_token(raw_token),
        csrf_token=csrf_token,
        ip_address=ip_addr,
        user_agent=ua,
        created_at=now,
        last_seen_at=now,
        idle_expires_at=now + timedelta(minutes=settings.session_idle_minutes),
        absolute_expires_at=now + timedelta(hours=settings.session_absolute_hours),
        correlation_id=corr_id,
    )
    db.add(sess)

    db.add(
        LoginLog(
            user_id=user.id,
            username_snapshot=user.username,
            action="login",
            ip_address=ip_addr,
            user_agent=ua,
            correlation_id=corr_id,
            session_id=session_id,
            created_at=now,
        )
    )

    await award_daily_login_score(db, user.id)
    await db.commit()

    _set_auth_cookies(request, response, raw_token, csrf_token)
    roles = sorted({r.role for r in user.roles})
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "job_title": user.job_title,
            "department": user.department,
            "display_access_level": user.display_access_level,
            "org_role_type": user.org_role_type,
            "roles": roles,
            "avatar_color": user.avatar_color,
            "theme_preference": user.theme_preference,
        },
        "csrf_token": csrf_token,
        "login_at_label": format_jalali_label(now),
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    verify_origin_header(request)
    now = utc_now()
    ctx.session.revoked_at = now
    ctx.session.revoke_reason = "user_logout"

    # At most 1 logout row per session even across retries or multiple tabs
    log_stmt = (
        pg_insert(LoginLog)
        .values(
            user_id=ctx.user.id,
            username_snapshot=ctx.user.username,
            action="logout",
            ip_address=extract_client_ip(request),
            user_agent=request.headers.get("user-agent", "")[:512],
            correlation_id=ctx.session.correlation_id,
            session_id=ctx.session.id,
            created_at=now,
        )
        .on_conflict_do_nothing()
    )
    await db.execute(log_stmt)

    ev = await emit_outbox_event(
        db,
        event_type="session.revoked",
        channel="system",
        payload={"session_ids": [ctx.session.id], "reason": "user_logout"},
    )
    await notify_outbox_signal(db, [ev.id])
    await db.commit()

    await hub.disconnect_sessions([ctx.session.id], "user_logout")

    secure, samesite, partitioned = _resolve_cookie_flags(request)
    response.delete_cookie("hb_session", path="/", secure=secure, samesite=samesite)
    if partitioned:
        _mark_cookies_partitioned(response)
    return {"ok": True, "message": "خروج با موفقیت انجام شد."}


@router.get("/me")
async def get_me(
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    unread_notif_res = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == ctx.user.id,
            Notification.is_read.is_(False),
        )
    )
    unread_notifications = int(unread_notif_res.scalar() or 0)

    # Unread chat per channel
    read_subq = select(ChatRead.message_id).where(ChatRead.user_id == ctx.user.id)
    unread_public_res = await db.execute(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.channel == "public",
            ChatMessage.sender_id != ctx.user.id,
            ~ChatMessage.id.in_(read_subq),
        )
    )
    unread_announce_res = await db.execute(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.channel == "announcements",
            ChatMessage.sender_id != ctx.user.id,
            ~ChatMessage.id.in_(read_subq),
        )
    )
    return {
        "user": {
            "id": ctx.user.id,
            "username": ctx.user.username,
            "display_name": ctx.user.display_name,
            "job_title": ctx.user.job_title,
            "department": ctx.user.department,
            "display_access_level": ctx.user.display_access_level,
            "org_role_type": ctx.user.org_role_type,
            "roles": sorted(ctx.roles),
            "avatar_color": ctx.user.avatar_color,
            "theme_preference": ctx.user.theme_preference,
        },
        "csrf_token": ctx.session.csrf_token,
        "unread_notifications": unread_notifications,
        "unread_chat_public": int(unread_public_res.scalar() or 0),
        "unread_chat_announcements": int(unread_announce_res.scalar() or 0),
    }


@router.patch("/theme")
async def update_theme(
    payload: ThemeUpdateRequest,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await db.get(User, ctx.user.id)
    if user:
        user.theme_preference = payload.theme_preference
        await db.commit()
    return {"theme_preference": payload.theme_preference}
