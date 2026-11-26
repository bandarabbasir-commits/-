from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import OutboxEvent, TaskReminder, WsPresence
from app.rbac import ROLE_ADMIN, AuthContext, require_roles
from app.utils.jalali import utc_now
from app.worker import worker_metrics

router = APIRouter(prefix="/api/v1", tags=["سلامت و پایش سرویس"])


class LatencyMetrics:
    total_requests: int = 0
    total_duration_ms: float = 0.0
    max_duration_ms: float = 0.0


latency_metrics = LatencyMetrics()


@router.get("/health")
async def liveness() -> dict:
    return {"status": "ok", "service": "hormozgan-bidar-api"}


@router.get("/ready")
async def readiness(db: AsyncSession = Depends(get_db)) -> dict:
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="اتصال به پایگاه‌داده برقرار نیست.") from exc
    return {"status": "ready", "database": "ok"}


@router.get("/metrics")
async def service_metrics(
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    outbox_backlog = int(
        (await db.execute(select(func.count(OutboxEvent.id)).where(OutboxEvent.published_at.is_(None)))).scalar() or 0
    )
    due_backlog = int(
        (
            await db.execute(
                select(func.count(TaskReminder.id)).where(
                    TaskReminder.fired.is_(False),
                    TaskReminder.cancelled_at.is_(None),
                    TaskReminder.due_at <= utc_now(),
                )
            )
        ).scalar()
        or 0
    )
    active_ws_presence = int(
        (await db.execute(select(func.count(WsPresence.id)).where(WsPresence.expires_at > utc_now()))).scalar() or 0
    )
    avg_ms = (
        round(latency_metrics.total_duration_ms / latency_metrics.total_requests, 2)
        if latency_metrics.total_requests
        else 0.0
    )
    return {
        "requests_total": latency_metrics.total_requests,
        "request_avg_ms": avg_ms,
        "request_max_ms": round(latency_metrics.max_duration_ms, 2),
        "outbox_backlog": outbox_backlog,
        "due_reminder_backlog": due_backlog,
        "reminders_fired_total": worker_metrics.reminders_fired,
        "worker_errors_total": worker_metrics.worker_errors,
        "active_ws_presence": active_ws_presence,
    }
