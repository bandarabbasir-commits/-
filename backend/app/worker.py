import asyncio
import logging
from datetime import timedelta
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import get_settings
import app.db as app_db
from app.models import Notification, SmsTask, TaskAssignment, TaskReminder, WsPresence
from app.realtime import emit_outbox_event, notify_outbox_signal
from app.utils.jalali import format_jalali_label, utc_now

logger = logging.getLogger("hb.worker")


class WorkerMetrics:
    reminder_batches_processed: int = 0
    reminders_fired: int = 0
    worker_errors: int = 0


worker_metrics = WorkerMetrics()


async def process_due_reminders_once() -> int:
    """
    Claim due reminders using FOR UPDATE SKIP LOCKED so multiple workers never double-fire.
    Verifies active assignment & non-deleted/non-closed task; if no longer eligible, cancels instead of firing.
    """
    now = utc_now()
    fired_count = 0
    async with app_db.AsyncSessionLocal() as db:
        stmt = (
            select(TaskReminder)
            .where(
                TaskReminder.fired.is_(False),
                TaskReminder.cancelled_at.is_(None),
                TaskReminder.due_at <= now,
            )
            .order_by(TaskReminder.due_at.asc(), TaskReminder.id.asc())
            .limit(50)
            .with_for_update(skip_locked=True)
        )
        res = await db.execute(stmt)
        due_rows = list(res.scalars().all())
        if not due_rows:
            return 0

        outbox_ids: list[int] = []
        for rem in due_rows:
            task = await db.get(SmsTask, rem.task_id)
            active_assign = None
            if task and not task.is_deleted and task.status not in ("success", "failed"):
                assign_res = await db.execute(
                    select(TaskAssignment).where(
                        TaskAssignment.task_id == rem.task_id,
                        TaskAssignment.receiver_id == rem.receiver_id,
                        TaskAssignment.is_active.is_(True),
                    )
                )
                active_assign = assign_res.scalar_one_or_none()

            if active_assign is None:
                rem.cancelled_at = now
                rem.cancel_reason = "ineligible_at_due_time"
                continue

            # Atomic notification + outbox + fired=True
            dedup_key = f"reminder:{rem.id}:{rem.idempotency_key}"
            title = "یادآور پیگیری پرونده"
            body = f"سررسید یادآور پرونده #{rem.task_id} ({format_jalali_label(rem.due_at)})"
            if rem.note:
                body = f"{body} — {rem.note[:120]}"

            ev = await emit_outbox_event(
                db,
                event_type="reminder.fired",
                channel=f"user:{rem.receiver_id}",
                payload={
                    "target_user_ids": [rem.receiver_id],
                    "reminder_id": rem.id,
                    "task_id": rem.task_id,
                    "title": title,
                    "body": body,
                    "dedup_key": dedup_key,
                },
            )
            outbox_ids.append(ev.id)

            notif_stmt = (
                pg_insert(Notification)
                .values(
                    user_id=rem.receiver_id,
                    type="reminder",
                    title=title,
                    body=body[:500],
                    task_id=rem.task_id,
                    outbox_event_id=ev.id,
                    dedup_key=dedup_key,
                    is_read=False,
                )
                .on_conflict_do_nothing(index_elements=["dedup_key"])
            )
            await db.execute(notif_stmt)

            rem.fired = True
            rem.fired_at = now
            fired_count += 1

        if outbox_ids:
            await notify_outbox_signal(db, outbox_ids)
        await db.commit()
        worker_metrics.reminder_batches_processed += 1
        worker_metrics.reminders_fired += fired_count
    return fired_count


async def cleanup_expired_presence_once() -> None:
    now = utc_now()
    async with app_db.AsyncSessionLocal() as db:
        await db.execute(delete(WsPresence).where(WsPresence.expires_at <= now))
        await db.commit()


async def run_background_worker(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    while not stop_event.is_set():
        try:
            await process_due_reminders_once()
            await cleanup_expired_presence_once()
        except asyncio.CancelledError:
            break
        except Exception:
            worker_metrics.worker_errors += 1
            logger.exception("reminder_worker_iteration_failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.reminder_poll_seconds)
        except asyncio.TimeoutError:
            pass
