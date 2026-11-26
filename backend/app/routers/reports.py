from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.exports import build_rtl_docx, build_rtl_xlsx
from app.models import ArchivedTask, SmsTask, TaskAction, TaskAssignment, User
from app.rbac import ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER, AuthContext, require_roles
from app.services import add_audit_log
from app.utils.jalali import jalali_range_to_utc_half_open
from app.utils.persian import to_persian_digits
from app.utils.security import extract_client_ip

router = APIRouter(prefix="/api/v1/reports", tags=["گزارش‌گیری و آمار"])


def _task_scope_conditions(ctx: AuthContext, start_date: Optional[str], end_date: Optional[str]):
    conds = [
        SmsTask.is_deleted.is_(False),
        ~exists(select(ArchivedTask.id).where(ArchivedTask.task_id == SmsTask.id)),
    ]
    if not ctx.is_manager:
        conds.append(
            exists(
                select(TaskAssignment.id).where(
                    TaskAssignment.task_id == SmsTask.id,
                    TaskAssignment.receiver_id == ctx.user.id,
                    TaskAssignment.is_active.is_(True),
                )
            )
        )
    if start_date or end_date:
        try:
            s_utc, e_utc = jalali_range_to_utc_half_open(start_date, end_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if s_utc:
            conds.append(SmsTask.created_at >= s_utc)
        if e_utc:
            conds.append(SmsTask.created_at < e_utc)
    return conds


async def _compute_summary(db: AsyncSession, ctx: AuthContext, start_date: Optional[str], end_date: Optional[str]) -> dict:
    conds = _task_scope_conditions(ctx, start_date, end_date)

    stmt = select(
        func.count(SmsTask.id).label("total"),
        func.count(SmsTask.id).filter(SmsTask.status == "pending").label("pending"),
        func.count(SmsTask.id).filter(SmsTask.status == "in_progress").label("in_progress"),
        func.count(SmsTask.id).filter(SmsTask.status == "success").label("success"),
        func.count(SmsTask.id).filter(SmsTask.status == "failed").label("failed"),
        func.avg(
            func.extract("epoch", SmsTask.first_action_at - SmsTask.created_at)
        )
        .filter(SmsTask.first_action_at.is_not(None))
        .label("avg_response_seconds"),
    ).where(*conds)

    row = (await db.execute(stmt)).one()
    total = int(row.total or 0)
    pending = int(row.pending or 0)
    in_progress = int(row.in_progress or 0)
    success = int(row.success or 0)
    failed = int(row.failed or 0)

    denom = success + failed
    success_rate = round((success / denom) * 100, 1) if denom > 0 else None
    avg_resp_hours = round(float(row.avg_response_seconds) / 3600.0, 1) if row.avg_response_seconds is not None else None

    return {
        "scope": "organization" if ctx.is_manager else "personal",
        "total": total,
        "pending": pending,
        "in_progress": in_progress,
        "success": success,
        "failed": failed,
        "success_rate_pct": success_rate,
        "success_rate_label": f"{to_persian_digits(success_rate)}٪" if success_rate is not None else "—",
        "avg_response_hours": avg_resp_hours,
        "avg_response_label": f"{to_persian_digits(avg_resp_hours)} ساعت" if avg_resp_hours is not None else "—",
    }


async def _compute_staff_rows(
    db: AsyncSession,
    ctx: AuthContext,
    start_date: Optional[str],
    end_date: Optional[str],
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    try:
        s_utc, e_utc = jalali_range_to_utc_half_open(start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    assign_conds = [SmsTask.is_deleted.is_(False), ~exists(select(ArchivedTask.id).where(ArchivedTask.task_id == SmsTask.id))]
    action_conds = [SmsTask.is_deleted.is_(False), ~exists(select(ArchivedTask.id).where(ArchivedTask.task_id == SmsTask.id))]
    if s_utc:
        assign_conds.append(TaskAssignment.assigned_at >= s_utc)
        action_conds.append(TaskAction.created_at >= s_utc)
    if e_utc:
        assign_conds.append(TaskAssignment.assigned_at < e_utc)
        action_conds.append(TaskAction.created_at < e_utc)

    # Separate relation aggregations to avoid Cartesian product double counting!
    assign_sub = (
        select(
            TaskAssignment.receiver_id.label("uid"),
            func.count(TaskAssignment.task_id.distinct()).label("assigned_count"),
            func.count(TaskAssignment.task_id.distinct())
            .filter(TaskAssignment.is_active.is_(True), SmsTask.status == "pending")
            .label("pending_count"),
        )
        .join(SmsTask, SmsTask.id == TaskAssignment.task_id)
        .where(*assign_conds)
        .group_by(TaskAssignment.receiver_id)
        .subquery()
    )

    action_sub = (
        select(
            TaskAction.actor_id.label("uid"),
            func.count(TaskAction.id).label("actions_count"),
            func.count(SmsTask.id.distinct())
            .filter(SmsTask.status == "success", SmsTask.closed_by == TaskAction.actor_id)
            .label("completed_count"),
        )
        .join(SmsTask, SmsTask.id == TaskAction.task_id)
        .where(*action_conds)
        .group_by(TaskAction.actor_id)
        .subquery()
    )

    user_filter = [User.is_deleted.is_(False), User.is_active.is_(True)]
    if not ctx.is_manager:
        user_filter.append(User.id == ctx.user.id)

    stmt = (
        select(
            User.id,
            User.display_name,
            User.job_title,
            User.department,
            func.coalesce(assign_sub.c.assigned_count, 0).label("assigned_count"),
            func.coalesce(action_sub.c.actions_count, 0).label("actions_count"),
            func.coalesce(action_sub.c.completed_count, 0).label("completed_count"),
            func.coalesce(assign_sub.c.pending_count, 0).label("pending_count"),
        )
        .outerjoin(assign_sub, assign_sub.c.uid == User.id)
        .outerjoin(action_sub, action_sub.c.uid == User.id)
        .where(*user_filter)
        .order_by(func.coalesce(action_sub.c.completed_count, 0).desc(), User.id.asc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    items = [
        {
            "user_id": r.id,
            "display_name": r.display_name,
            "job_title": r.job_title,
            "department": r.department,
            "assigned_count": int(r.assigned_count),
            "actions_count": int(r.actions_count),
            "completed_count": int(r.completed_count),
            "pending_count": int(r.pending_count),
        }
        for r in res.all()
    ]
    total = int((await db.execute(select(func.count(User.id)).where(*user_filter))).scalar() or 0)
    return items, total


@router.get("/summary")
async def report_summary(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    ctx: AuthContext = Depends(require_roles(ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _compute_summary(db, ctx, start_date, end_date)


@router.get("/staff")
async def report_staff(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_roles(ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    items, total = await _compute_staff_rows(db, ctx, start_date, end_date, limit, offset)
    return {"items": items, "total": total}


@router.get("/export/{fmt}")
async def export_report(
    fmt: str,
    request: Request,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    ctx: AuthContext = Depends(require_roles(ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if fmt not in ("word", "excel"):
        raise HTTPException(status_code=404, detail="قالب گزارش پشتیبانی نمی‌شود.")

    summary = await _compute_summary(db, ctx, start_date, end_date)
    staff_rows, _ = await _compute_staff_rows(db, ctx, start_date, end_date, 500, 0)

    headers = ["نام و نام‌خانوادگی", "سمت", "ارجاع‌ها", "اقدامات ثبت‌شده", "انجام‌شده (موفق)", "در انتظار"]
    rows = [
        [
            r["display_name"],
            r["job_title"] or "—",
            r["assigned_count"],
            r["actions_count"],
            r["completed_count"],
            r["pending_count"],
        ]
        for r in staff_rows
    ]

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action=f"export.report.{fmt}",
        target_type="report",
        target_id=summary["scope"],
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()

    subtitle = (
        f"کل پرونده‌ها: {to_persian_digits(summary['total'])} | "
        f"موفق: {to_persian_digits(summary['success'])} | "
        f"نرخ موفقیت: {summary['success_rate_label']} | "
        f"متوسط زمان پاسخ: {summary['avg_response_label']}"
    )
    if fmt == "word":
        data = build_rtl_docx("گزارش جامع عملکرد و پیام‌های مردمی", subtitle, headers, rows)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": 'attachment; filename="hormozgan-report.docx"', "Cache-Control": "no-store"},
        )
    data = build_rtl_xlsx("عملکرد پرسنل", headers, rows, numeric_cols={2, 3, 4, 5})
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="hormozgan-report.xlsx"', "Cache-Control": "no-store"},
    )
