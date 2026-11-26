from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import get_db
from app.models import TaskAssignment, User, UserRole, WsPresence
from app.rbac import (
    ROLE_ADMIN,
    ROLE_EMPLOYEE,
    ROLE_EXPERT,
    ROLE_MANAGER,
    AuthContext,
    get_current_auth,
    require_roles,
)
from app.realtime import emit_outbox_event, hub, notify_outbox_signal
from app.schemas import (
    UserCreateRequest,
    UserPasswordResetRequest,
    UserStatusToggleRequest,
    UserUpdateRequest,
)
from app.services import add_audit_log
from app.utils.jalali import utc_now
from app.utils.persian import normalize_digits_ascii, normalize_persian_for_search
from app.utils.security import compute_avatar_color, extract_client_ip, hash_password, revoke_user_sessions

router = APIRouter(prefix="/api/v1/users", tags=["کاربران و دایرکتوری"])


@router.get("/directory")
async def list_directory(
    assignable_only: bool = Query(False),
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Minimal role-safe directory for colleague picker, chat, and presence.
    NEVER returns username, password hash, tokens, or contact info.
    """
    now = utc_now()
    online_res = await db.execute(
        select(WsPresence.user_id).where(WsPresence.expires_at > now).distinct()
    )
    online_ids = {uid for (uid,) in online_res.all()}

    stmt = (
        select(User)
        .options(selectinload(User.roles))
        .where(User.is_active.is_(True), User.is_deleted.is_(False))
        .order_by(User.display_name.asc(), User.id.asc())
    )
    res = await db.execute(stmt)
    users = list(res.scalars().all())

    items = []
    for u in users:
        role_set = {r.role for r in u.roles}
        if assignable_only and not role_set.intersection({ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER}):
            continue
        items.append(
            {
                "id": u.id,
                "display_name": u.display_name,
                "job_title": u.job_title,
                "department": u.department,
                "avatar_color": u.avatar_color,
                "is_online": u.id in online_ids,
            }
        )
    return {"items": items}


@router.get("")
async def list_users_admin(
    q: str = Query(""),
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = (
        select(User)
        .options(selectinload(User.roles))
        .where(User.is_deleted.is_(False))
        .order_by(User.department.asc(), User.display_name.asc(), User.id.asc())
    )
    res = await db.execute(stmt)
    users = list(res.scalars().all())

    # Open active assignment count per user
    cnt_res = await db.execute(
        select(TaskAssignment.receiver_id, func.count(TaskAssignment.id))
        .where(TaskAssignment.is_active.is_(True))
        .group_by(TaskAssignment.receiver_id)
    )
    open_counts = {uid: int(cnt) for uid, cnt in cnt_res.all()}

    q_norm = normalize_persian_for_search(q)
    items = []
    for u in users:
        if q_norm:
            haystack = normalize_persian_for_search(f"{u.display_name} {u.job_title} {u.department} {u.username}")
            if q_norm not in haystack:
                continue
        items.append(
            {
                "id": u.id,
                "username": u.username,
                "display_name": u.display_name,
                "job_title": u.job_title,
                "department": u.department,
                "display_access_level": u.display_access_level,
                "org_role_type": u.org_role_type,
                "roles": sorted({r.role for r in u.roles}),
                "is_active": u.is_active,
                "is_deleted": u.is_deleted,
                "avatar_color": u.avatar_color,
                "theme_preference": u.theme_preference,
                "open_assignment_count": open_counts.get(u.id, 0),
                "created_at": u.created_at.isoformat(),
                "version": u.version,
            }
        )
    return {"items": items}


@router.post("")
async def create_user(
    payload: UserCreateRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    uname_clean = normalize_digits_ascii(payload.username.strip())
    uname_lower = uname_clean.lower()

    ex_res = await db.execute(select(User).where(User.username_lower == uname_lower))
    if ex_res.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="این نام کاربری قبلاً ثبت شده است.")

    user = User(
        username=uname_clean,
        username_lower=uname_lower,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
        job_title=payload.job_title.strip(),
        department=payload.department.strip(),
        display_access_level=payload.display_access_level,
        org_role_type=payload.org_role_type,
        avatar_color=compute_avatar_color(uname_lower + payload.display_name.strip()),
    )
    db.add(user)
    await db.flush()

    for r in set(payload.roles):
        db.add(UserRole(user_id=user.id, role=r, granted_by=ctx.user.id))

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="user.create",
        target_type="user",
        target_id=str(user.id),
        after_state={"username": user.username, "roles": sorted(set(payload.roles))},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"id": user.id, "username": user.username, "roles": sorted(set(payload.roles))}


async def _count_other_active_admins(db: AsyncSession, exclude_user_id: int) -> int:
    res = await db.execute(
        select(func.count(User.id.distinct()))
        .join(UserRole, UserRole.user_id == User.id)
        .where(
            User.id != exclude_user_id,
            User.is_active.is_(True),
            User.is_deleted.is_(False),
            UserRole.role == ROLE_ADMIN,
        )
    )
    return int(res.scalar() or 0)


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(User).options(selectinload(User.roles)).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user or user.is_deleted:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    if user.version != payload.version:
        raise HTTPException(status_code=409, detail="اطلاعات کاربر هم‌زمان تغییر کرده است.")

    old_roles = {r.role for r in user.roles}
    new_roles = set(payload.roles)
    if ROLE_ADMIN in old_roles and ROLE_ADMIN not in new_roles:
        if await _count_other_active_admins(db, user.id) == 0:
            raise HTTPException(status_code=409, detail="امکان حذف نقش ادمین از آخرین مدیر سامانهٔ فعال وجود ندارد.")

    user.display_name = payload.display_name.strip()
    user.job_title = payload.job_title.strip()
    user.department = payload.department.strip()
    user.display_access_level = payload.display_access_level
    user.org_role_type = payload.org_role_type
    user.version += 1

    # Sync roles
    for ur in list(user.roles):
        if ur.role not in new_roles:
            await db.delete(ur)
    for r in new_roles - old_roles:
        db.add(UserRole(user_id=user.id, role=r, granted_by=ctx.user.id))

    outbox_ids: list[int] = []
    if old_roles != new_roles:
        revoked = await revoke_user_sessions(db, user.id, "roles_changed")
        if revoked:
            ev = await emit_outbox_event(
                db, "session.revoked", "system", {"session_ids": revoked, "reason": "roles_changed"}
            )
            outbox_ids.append(ev.id)
            await hub.disconnect_sessions(revoked, "roles_changed")

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="user.update",
        target_type="user",
        target_id=str(user.id),
        before_state={"roles": sorted(old_roles)},
        after_state={"roles": sorted(new_roles)},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await notify_outbox_signal(db, outbox_ids)
    await db.commit()
    return {"id": user.id, "roles": sorted(new_roles), "version": user.version}


@router.post("/{user_id}/password")
async def reset_user_password(
    user_id: int,
    payload: UserPasswordResetRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await db.get(User, user_id)
    if not user or user.is_deleted:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    user.password_hash = hash_password(payload.new_password)
    user.version += 1

    revoked = await revoke_user_sessions(db, user.id, "password_changed")
    outbox_ids: list[int] = []
    if revoked:
        ev = await emit_outbox_event(
            db, "session.revoked", "system", {"session_ids": revoked, "reason": "password_changed"}
        )
        outbox_ids.append(ev.id)
        await hub.disconnect_sessions(revoked, "password_changed")

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="user.password_reset",
        target_type="user",
        target_id=str(user.id),
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await notify_outbox_signal(db, outbox_ids)
    await db.commit()
    return {"ok": True}


@router.post("/{user_id}/status")
async def toggle_user_status(
    user_id: int,
    payload: UserStatusToggleRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(User).options(selectinload(User.roles)).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user or user.is_deleted:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    if user.version != payload.version:
        raise HTTPException(status_code=409, detail="تعارض نسخه در تغییر وضعیت کاربر.")

    if not payload.is_active and any(r.role == ROLE_ADMIN for r in user.roles):
        if await _count_other_active_admins(db, user.id) == 0:
            raise HTTPException(status_code=409, detail="امکان غیرفعال‌کردن آخرین مدیر سامانهٔ فعال وجود ندارد.")

    user.is_active = payload.is_active
    user.version += 1

    open_count_res = await db.execute(
        select(func.count(TaskAssignment.id)).where(
            TaskAssignment.receiver_id == user.id, TaskAssignment.is_active.is_(True)
        )
    )
    open_assignments = int(open_count_res.scalar() or 0)

    outbox_ids: list[int] = []
    if not payload.is_active:
        revoked = await revoke_user_sessions(db, user.id, "user_deactivated")
        if revoked:
            ev = await emit_outbox_event(
                db, "session.revoked", "system", {"session_ids": revoked, "reason": "user_deactivated"}
            )
            outbox_ids.append(ev.id)
            await hub.disconnect_sessions(revoked, "user_deactivated")

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="user.status_change",
        target_type="user",
        target_id=str(user.id),
        after_state={"is_active": user.is_active, "open_assignments": open_assignments},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await notify_outbox_signal(db, outbox_ids)
    await db.commit()
    return {
        "id": user.id,
        "is_active": user.is_active,
        "version": user.version,
        "open_assignment_count": open_assignments,
        "reassignment_warning": (
            f"این کاربر {open_assignments} پروندهٔ ارجاعی باز دارد که نیازمند واگذاری مجدد است."
            if (not user.is_active and open_assignments > 0)
            else None
        ),
    }


@router.delete("/{user_id}")
async def soft_delete_user(
    user_id: int,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    res = await db.execute(select(User).options(selectinload(User.roles)).where(User.id == user_id))
    user = res.scalar_one_or_none()
    if not user or user.is_deleted:
        raise HTTPException(status_code=404, detail="کاربر یافت نشد.")
    if any(r.role == ROLE_ADMIN for r in user.roles):
        if await _count_other_active_admins(db, user.id) == 0:
            raise HTTPException(status_code=409, detail="امکان حذف آخرین مدیر سامانهٔ فعال وجود ندارد.")

    user.is_deleted = True
    user.is_active = False
    user.deleted_at = utc_now()
    user.version += 1

    revoked = await revoke_user_sessions(db, user.id, "user_deleted")
    if revoked:
        ev = await emit_outbox_event(db, "session.revoked", "system", {"session_ids": revoked, "reason": "user_deleted"})
        await notify_outbox_signal(db, [ev.id])
        await hub.disconnect_sessions(revoked, "user_deleted")

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="user.soft_delete",
        target_type="user",
        target_id=str(user.id),
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"ok": True}
