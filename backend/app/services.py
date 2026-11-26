from datetime import timedelta
from typing import Any, Optional
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    AuditLog,
    FolderItem,
    Notification,
    TaskAssignment,
    TaskEvent,
    TaskReminder,
    User,
    UserRating,
)
from app.rbac import ROLE_LABELS_FA, sanitize_audit_state
from app.realtime import emit_outbox_event
from app.utils.jalali import tehran_today_date, utc_now


def get_actor_role_label(roles: set[str]) -> str:
    for r in ("manager", "admin", "expert", "employee", "author"):
        if r in roles:
            return ROLE_LABELS_FA[r]
    return "کاربر"


async def add_task_event(
    db: AsyncSession,
    task_id: int,
    actor: Optional[User],
    actor_roles: set[str],
    event_type: str,
    details: Optional[dict[str, Any]] = None,
) -> TaskEvent:
    ev = TaskEvent(
        task_id=task_id,
        actor_id=actor.id if actor else None,
        actor_display_name=actor.display_name if actor else "سامانه",
        actor_role_label=get_actor_role_label(actor_roles) if actor else "سامانه",
        event_type=event_type,
        details=details or {},
    )
    db.add(ev)
    await db.flush()
    return ev


async def add_audit_log(
    db: AsyncSession,
    actor_id: Optional[int],
    action: str,
    target_type: str,
    target_id: str,
    before_state: Optional[dict[str, Any]] = None,
    after_state: Optional[dict[str, Any]] = None,
    ip_address: str = "",
    correlation_id: str = "",
) -> AuditLog:
    row = AuditLog(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        before_state=sanitize_audit_state(before_state),
        after_state=sanitize_audit_state(after_state),
        ip_address=ip_address[:64],
        correlation_id=correlation_id[:64],
    )
    db.add(row)
    await db.flush()
    return row


async def award_daily_login_score(db: AsyncSession, user_id: int) -> None:
    settings = get_settings()
    today_tehran = tehran_today_date()
    idem = f"daily_login:{user_id}:{today_tehran.isoformat()}"
    stmt = (
        pg_insert(UserRating)
        .values(
            user_id=user_id,
            score=settings.auto_score_daily_login,
            source="auto_daily_login",
            reason="امتیاز خودکار حضور و ورود روزانه",
            award_date_tehran=today_tehran,
            idempotency_key=idem,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    await db.execute(stmt)


async def award_timely_action_score(
    db: AsyncSession,
    user_id: int,
    task_id: int,
    assignment: Optional[TaskAssignment],
    action_time,
) -> None:
    if assignment is None:
        return
    settings = get_settings()
    sla_map = {
        "urgent": settings.sla_hours_urgent,
        "medium": settings.sla_hours_medium,
        "normal": settings.sla_hours_normal,
    }
    sla_hours = sla_map.get(assignment.priority_at_assignment, settings.sla_hours_normal)
    deadline = assignment.assigned_at + timedelta(hours=sla_hours)
    if action_time <= deadline:
        idem = f"timely_action:task:{task_id}:user:{user_id}:assign:{assignment.id}"
        stmt = (
            pg_insert(UserRating)
            .values(
                user_id=user_id,
                score=settings.auto_score_timely_action,
                source="auto_timely_action",
                reason="امتیاز خودکار ثبت اقدام به‌موقع در مهلت مقرر",
                task_id=task_id,
                award_date_tehran=tehran_today_date(),
                idempotency_key=idem,
            )
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
        )
        await db.execute(stmt)


async def award_task_success_score(db: AsyncSession, user_id: int, task_id: int) -> None:
    settings = get_settings()
    idem = f"task_success:task:{task_id}"
    stmt = (
        pg_insert(UserRating)
        .values(
            user_id=user_id,
            score=settings.auto_score_success,
            source="auto_success",
            reason="امتیاز خودکار تکمیل موفق پرونده",
            task_id=task_id,
            award_date_tehran=tehran_today_date(),
            idempotency_key=idem,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    await db.execute(stmt)


async def cancel_user_task_reminders_and_folder(
    db: AsyncSession,
    task_id: int,
    receiver_id: int,
    reason: str,
    actor: Optional[User],
    actor_roles: set[str],
) -> None:
    now = utc_now()
    # Remove from user's personal folder when assignment ends
    await db.execute(
        delete(FolderItem).where(FolderItem.task_id == task_id, FolderItem.user_id == receiver_id)
    )
    # Cancel unfired reminders for that receiver
    rem_res = await db.execute(
        select(TaskReminder).where(
            TaskReminder.task_id == task_id,
            TaskReminder.receiver_id == receiver_id,
            TaskReminder.fired.is_(False),
            TaskReminder.cancelled_at.is_(None),
        )
    )
    rems = list(rem_res.scalars().all())
    if rems:
        for rem in rems:
            rem.cancelled_at = now
            rem.cancel_reason = reason
        await add_task_event(
            db,
            task_id=task_id,
            actor=actor,
            actor_roles=actor_roles,
            event_type="reminder_cancelled",
            details={"count": len(rems), "reason": reason, "receiver_id": receiver_id},
        )


async def cancel_all_task_reminders(
    db: AsyncSession,
    task_id: int,
    reason: str,
    actor: Optional[User],
    actor_roles: set[str],
) -> None:
    now = utc_now()
    rem_res = await db.execute(
        select(TaskReminder).where(
            TaskReminder.task_id == task_id,
            TaskReminder.fired.is_(False),
            TaskReminder.cancelled_at.is_(None),
        )
    )
    rems = list(rem_res.scalars().all())
    if rems:
        for rem in rems:
            rem.cancelled_at = now
            rem.cancel_reason = reason
        await add_task_event(
            db,
            task_id=task_id,
            actor=actor,
            actor_roles=actor_roles,
            event_type="reminder_cancelled",
            details={"count": len(rems), "reason": reason},
        )


async def create_user_notification(
    db: AsyncSession,
    user_id: int,
    notif_type: str,
    title: str,
    body: str,
    dedup_key: str,
    task_id: Optional[int] = None,
) -> Optional[int]:
    ev = await emit_outbox_event(
        db,
        event_type=f"notification.{notif_type}",
        channel=f"user:{user_id}",
        payload={
            "target_user_ids": [user_id],
            "title": title,
            "body": body,
            "task_id": task_id,
            "dedup_key": dedup_key,
        },
    )
    stmt = (
        pg_insert(Notification)
        .values(
            user_id=user_id,
            type=notif_type,
            title=title[:160],
            body=body[:500],
            task_id=task_id,
            outbox_event_id=ev.id,
            dedup_key=dedup_key,
            is_read=False,
        )
        .on_conflict_do_nothing(index_elements=["dedup_key"])
    )
    await db.execute(stmt)
    return ev.id
