from dataclasses import dataclass
from typing import Iterable, Optional
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import get_db
from app.models import ArchivedTask, Session, SmsTask, TaskAssignment, User
from app.utils.jalali import utc_now
from app.utils.security import hash_token, verify_csrf_for_session
from datetime import timedelta

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_AUTHOR = "author"
ROLE_EMPLOYEE = "employee"
ROLE_EXPERT = "expert"

VALID_ROLES = {ROLE_ADMIN, ROLE_MANAGER, ROLE_AUTHOR, ROLE_EMPLOYEE, ROLE_EXPERT}

ROLE_LABELS_FA = {
    ROLE_ADMIN: "مدیر سامانه",
    ROLE_MANAGER: "مدیر دفتر",
    ROLE_AUTHOR: "نویسنده",
    ROLE_EMPLOYEE: "کارمند",
    ROLE_EXPERT: "کارشناس",
}


@dataclass
class AuthContext:
    user: User
    session: Session
    roles: set[str]

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def has_any_role(self, roles: Iterable[str]) -> bool:
        return bool(self.roles.intersection(roles))

    @property
    def is_admin(self) -> bool:
        return ROLE_ADMIN in self.roles

    @property
    def is_manager(self) -> bool:
        return ROLE_MANAGER in self.roles

    @property
    def is_author(self) -> bool:
        return ROLE_AUTHOR in self.roles

    @property
    def is_staff_handler(self) -> bool:
        return self.has_any_role({ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER})

    @property
    def primary_role_label(self) -> str:
        for r in (ROLE_MANAGER, ROLE_ADMIN, ROLE_EXPERT, ROLE_EMPLOYEE, ROLE_AUTHOR):
            if r in self.roles:
                return ROLE_LABELS_FA[r]
        return "کاربر"


async def resolve_session_from_token(db: AsyncSession, raw_token: str) -> Optional[AuthContext]:
    if not raw_token:
        return None
    settings = get_settings()
    now = utc_now()
    t_hash = hash_token(raw_token)
    stmt = select(Session).where(Session.token_hash == t_hash)
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()
    if session is None or session.revoked_at is not None:
        return None
    if session.idle_expires_at <= now or session.absolute_expires_at <= now:
        return None

    user_stmt = (
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == session.user_id, User.is_deleted.is_(False), User.is_active.is_(True))
    )
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()
    if user is None:
        return None

    # Slide idle window
    session.last_seen_at = now
    session.idle_expires_at = min(
        session.absolute_expires_at,
        now + timedelta(minutes=settings.session_idle_minutes),
    )
    roles = {r.role for r in user.roles}
    return AuthContext(user=user, session=session, roles=roles)


async def get_current_auth(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    raw_token = request.cookies.get("hb_session", "")
    ctx = await resolve_session_from_token(db, raw_token)
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="نشست کاربری معتبر نیست یا منقضی شده است.",
        )
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        verify_csrf_for_session(request, ctx.session)
    await db.commit()
    return ctx


def require_roles(*allowed_roles: str):
    async def _dep(ctx: AuthContext = Depends(get_current_auth)) -> AuthContext:
        if not ctx.has_any_role(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="شما مجوز دسترسی به این عملیات را ندارید.",
            )
        return ctx

    return _dep


async def get_active_assignment_for_user(db: AsyncSession, task_id: int, user_id: int) -> Optional[TaskAssignment]:
    stmt = select(TaskAssignment).where(
        TaskAssignment.task_id == task_id,
        TaskAssignment.receiver_id == user_id,
        TaskAssignment.is_active.is_(True),
    )
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def is_task_archived(db: AsyncSession, task_id: int) -> bool:
    stmt = select(ArchivedTask.id).where(ArchivedTask.task_id == task_id)
    res = await db.execute(stmt)
    return res.scalar_one_or_none() is not None


async def assert_task_accessible(
    db: AsyncSession,
    ctx: AuthContext,
    task_id: int,
    allow_archived_for_manager: bool = False,
) -> tuple[SmsTask, Optional[TaskAssignment]]:
    task = await db.get(SmsTask, task_id)
    if task is None or task.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="پرونده یافت نشد.")

    archived = await is_task_archived(db, task_id)
    if archived and not (allow_archived_for_manager and ctx.is_manager):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="پرونده در بایگانی قرار دارد.")

    assignment = await get_active_assignment_for_user(db, task_id, ctx.user.id)
    if ctx.is_manager:
        return task, assignment

    # Employee / Expert: only active assignment
    if assignment is not None and ctx.has_any_role({ROLE_EMPLOYEE, ROLE_EXPERT}):
        return task, assignment

    # Note: Author without active assignment or manager role has NO access to converted tasks;
    # Admin without manager role has NO access to supervision inbox!
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="شما مجوز مشاهدهٔ این پرونده را ندارید.")


def sanitize_audit_state(data: Optional[dict]) -> Optional[dict]:
    if data is None:
        return None
    forbidden_keys = {"password", "password_hash", "token", "token_hash", "csrf_token", "secret", "body", "phone", "requester_phone_norm"}
    cleaned = {}
    for k, v in data.items():
        if k.lower() in forbidden_keys:
            cleaned[k] = "[پالایش‌شده]"
        else:
            cleaned[k] = v
    return cleaned
