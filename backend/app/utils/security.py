import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Optional
from urllib.parse import urlparse

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from fastapi import HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AuthRateLimit, Session, WsPresence
from app.utils.jalali import utc_now

_ph = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

AVATAR_PALETTE = [
    "#0F766E",  # Deep Teal
    "#0369A1",  # Ocean Blue
    "#1D4ED8",  # Cobalt
    "#047857",  # Sea Emerald
    "#B45309",  # Warm Amber
    "#7C2D12",  # Terracotta
    "#4338CA",  # Indigo
    "#0E7490",  # Cyan Slate
]


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def compute_avatar_color(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return AVATAR_PALETTE[digest[0] % len(AVATAR_PALETTE)]


def extract_client_ip(request: Request) -> str:
    settings = get_settings()
    peer_ip = request.client.host if request.client else ""
    if peer_ip in settings.trusted_proxies_list:
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            first_ip = xff.split(",")[0].strip()
            if first_ip:
                return first_ip[:64]
        xri = request.headers.get("x-real-ip", "").strip()
        if xri:
            return xri[:64]
    return (peer_ip or "unknown")[:64]


def _request_origin_allowed(request: Request) -> bool:
    settings = get_settings()
    origin = request.headers.get("origin")
    if not origin:
        referer = request.headers.get("referer")
        if referer:
            parsed = urlparse(referer)
            origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""

    if not origin:
        # Allow non-browser same-origin / test clients only when Host matches allowed origin
        return settings.app_env == "test"

    origin_clean = origin.rstrip("/")
    if origin_clean in settings.allowed_origins_list:
        return True

    # Also match exact Host / X-Forwarded-Host when behind trusted reverse proxy
    peer_ip = request.client.host if request.client else ""
    host = request.headers.get("host", "")
    if peer_ip in settings.trusted_proxies_list:
        fwd_host = request.headers.get("x-forwarded-host", "")
        if fwd_host:
            host = fwd_host.split(",")[0].strip()
    parsed_origin = urlparse(origin_clean)
    return bool(host and parsed_origin.netloc == host)


def verify_origin_header(request: Request) -> None:
    if not _request_origin_allowed(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="درخواست از مبدأ غیرمجاز مسدود شد.",
        )


def verify_csrf_for_session(request: Request, session: Session) -> None:
    verify_origin_header(request)
    header_token = request.headers.get("x-csrf-token", "")
    if not header_token or not hmac.compare_digest(header_token, session.csrf_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="توکن امنیتی CSRF نامعتبر یا منقضی است.",
        )


def verify_preauth_csrf(request: Request) -> None:
    verify_origin_header(request)
    cookie_token = request.cookies.get("hb_csrf", "")
    header_token = request.headers.get("x-csrf-token", "")
    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="نشست امنیتی فرم ورود معتبر نیست؛ لطفاً صفحه را تازه‌سازی کنید.",
        )


async def check_rate_limit(db: AsyncSession, bucket_key: str) -> None:
    settings = get_settings()
    now = utc_now()
    row = await db.get(AuthRateLimit, bucket_key, with_for_update=True)
    if row is None:
        return
    if row.blocked_until and row.blocked_until > now:
        remaining = int((row.blocked_until - now).total_seconds()) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"تعداد تلاش‌های ورود بیش از حد مجاز است. لطفاً {remaining} ثانیه دیگر تلاش کنید.",
        )


async def record_failed_login(db: AsyncSession, bucket_key: str) -> None:
    settings = get_settings()
    now = utc_now()
    row = await db.get(AuthRateLimit, bucket_key, with_for_update=True)
    if row is None:
        stmt = (
            pg_insert(AuthRateLimit)
            .values(bucket_key=bucket_key, attempt_count=1, window_start=now, blocked_until=None)
            .on_conflict_do_nothing()
        )
        await db.execute(stmt)
        return

    window_end = row.window_start + timedelta(seconds=settings.login_rate_limit_window_seconds)
    if now > window_end:
        row.attempt_count = 1
        row.window_start = now
        row.blocked_until = None
    else:
        row.attempt_count += 1
        if row.attempt_count >= settings.login_rate_limit_max_attempts:
            row.blocked_until = now + timedelta(seconds=settings.login_rate_limit_lock_seconds)


async def clear_rate_limit(db: AsyncSession, bucket_key: str) -> None:
    await db.execute(delete(AuthRateLimit).where(AuthRateLimit.bucket_key == bucket_key))


async def revoke_user_sessions(
    db: AsyncSession,
    user_id: int,
    reason: str,
    except_session_id: Optional[str] = None,
) -> list[str]:
    now = utc_now()
    stmt = select(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
    if except_session_id:
        stmt = stmt.where(Session.id != except_session_id)
    res = await db.execute(stmt)
    sessions = list(res.scalars().all())
    revoked_ids: list[str] = []
    for s in sessions:
        s.revoked_at = now
        s.revoke_reason = reason
        revoked_ids.append(s.id)
    if revoked_ids:
        await db.execute(delete(WsPresence).where(WsPresence.session_id.in_(revoked_ids)))
    return revoked_ids
