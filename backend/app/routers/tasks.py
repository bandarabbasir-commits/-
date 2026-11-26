from datetime import datetime, timedelta
from typing import Any, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.exports import build_rtl_docx, build_rtl_xlsx, build_utf8_bom_csv
from app.models import (
    ArchivedTask,
    FolderItem,
    IdempotencyRecord,
    PersonalFolder,
    SmsTask,
    TaskAction,
    TaskAssignment,
    TaskEvent,
    TaskNote,
    TaskReminder,
    User,
    UserRole,
)
from app.rbac import (
    ROLE_ADMIN,
    ROLE_EMPLOYEE,
    ROLE_EXPERT,
    ROLE_MANAGER,
    AuthContext,
    assert_task_accessible,
    get_current_auth,
    require_roles,
)
from app.realtime import emit_outbox_event, notify_outbox_signal
from sqlalchemy.orm import aliased
from app.schemas import (
    FolderCreateRequest,
    TaskActionRequest,
    TaskDirectCreateRequest,
    TaskFolderAssignRequest,
    TaskManagerUpdateRequest,
    TaskNoteCreateRequest,
    TaskReminderCreateRequest,
    TaskReopenRequest,
    TaskSingleArchiveRequest,
)
from app.services import (
    add_audit_log,
    add_task_event,
    award_task_success_score,
    award_timely_action_score,
    cancel_all_task_reminders,
    cancel_user_task_reminders_and_folder,
    create_user_notification,
)
from app.utils.jalali import (
    TEHRAN_TZ,
    UTC_TZ,
    format_jalali_label,
    jalali_range_to_utc_half_open,
    parse_jalali_datetime_tehran_to_utc,
    to_tehran_dt,
    utc_now,
)
from app.utils.persian import normalize_iran_phone, normalize_persian_for_search
from app.utils.security import extract_client_ip

router = APIRouter(prefix="/api/v1", tags=["صندوق ورودی و پرونده‌ها"])

SOURCE_LABELS = {
    "sms": "پیامک",
    "phone": "تلفن",
    "in_person": "حضوری",
    "social": "شبکه اجتماعی",
}
PRIORITY_LABELS = {"urgent": "فوری", "medium": "متوسط", "normal": "عادی"}
STATUS_LABELS = {
    "pending": "در انتظار اقدام",
    "in_progress": "در حال پیگیری",
    "success": "موفق / پایان‌یافته",
    "failed": "ناموفق / کنسل‌شده",
}
FLAG_LABELS = {"action": "اقدام شود", "followup": "پیگیری شود"}


def _build_scoped_task_filters(
    ctx: AuthContext,
    view_mode: str,
    tab: str,
    status_filter: str,
    priority_filter: str,
    q: Optional[str],
    created_from: Optional[str],
    created_to: Optional[str],
    action_from: Optional[str],
    action_to: Optional[str],
    quick_time: Optional[str],
    folder_id: Optional[int],
):
    conditions = [
        SmsTask.is_deleted.is_(False),
        ~exists(select(ArchivedTask.id).where(ArchivedTask.task_id == SmsTask.id)),
    ]

    # Strict server-side row scope
    if view_mode == "supervision":
        if not ctx.is_manager:
            raise HTTPException(status_code=403, detail="فقط مدیر مجاز به مشاهدهٔ نمای نظارت است.")
    else:
        # "my" inbox: active assignments to current user
        if not ctx.has_any_role({ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER}):
            raise HTTPException(status_code=403, detail="نقش شما مجوز دسترسی به صندوق پرونده‌ها را ندارد.")
        conditions.append(
            exists(
                select(TaskAssignment.id).where(
                    TaskAssignment.task_id == SmsTask.id,
                    TaskAssignment.receiver_id == ctx.user.id,
                    TaskAssignment.is_active.is_(True),
                )
            )
        )

    # Tab filter
    if tab == "sms":
        conditions.append(SmsTask.source_type == "sms")
    elif tab == "done":
        conditions.append(SmsTask.status.in_(["success", "failed"]))
    elif tab.startswith("sender:"):
        try:
            sender_id = int(tab.split(":", 1)[1])
        except ValueError:
            raise HTTPException(status_code=422, detail="تب فرستنده معتبر نیست.")
        conditions.append(
            exists(
                select(TaskAssignment.id).where(
                    TaskAssignment.task_id == SmsTask.id,
                    TaskAssignment.receiver_id == ctx.user.id,
                    TaskAssignment.sender_id == sender_id,
                    TaskAssignment.is_active.is_(True),
                )
            )
        )

    if status_filter and status_filter != "all":
        conditions.append(SmsTask.status == status_filter)
    if priority_filter and priority_filter != "all":
        conditions.append(SmsTask.priority == priority_filter)

    if folder_id is not None:
        conditions.append(
            exists(
                select(FolderItem.id).where(
                    FolderItem.task_id == SmsTask.id,
                    FolderItem.user_id == ctx.user.id,
                    FolderItem.folder_id == folder_id,
                )
            )
        )

    # Quick time sets created range in Asia/Tehran
    c_start: Optional[datetime] = None
    c_end: Optional[datetime] = None
    if quick_time in ("today", "week", "month"):
        now_t = to_tehran_dt(utc_now())
        start_today_t = datetime(now_t.year, now_t.month, now_t.day, 0, 0, 0, tzinfo=TEHRAN_TZ)
        if quick_time == "today":
            c_start = start_today_t.astimezone(UTC_TZ)
            c_end = (start_today_t + timedelta(days=1)).astimezone(UTC_TZ)
        elif quick_time == "week":
            # Saturday is start of week in Iran: Python weekday() Mon=0..Sun=6 => Sat=5
            days_since_sat = (now_t.weekday() - 5) % 7
            c_start = (start_today_t - timedelta(days=days_since_sat)).astimezone(UTC_TZ)
            c_end = (start_today_t + timedelta(days=1)).astimezone(UTC_TZ)
        elif quick_time == "month":
            import jdatetime
            jt = jdatetime.datetime.fromgregorian(datetime=now_t)
            j_month_start = jdatetime.date(jt.year, jt.month, 1).togregorian()
            t_month_start = datetime(
                j_month_start.year, j_month_start.month, j_month_start.day, 0, 0, 0, tzinfo=TEHRAN_TZ
            )
            c_start = t_month_start.astimezone(UTC_TZ)
            c_end = (start_today_t + timedelta(days=1)).astimezone(UTC_TZ)
    elif created_from or created_to:
        try:
            c_start, c_end = jalali_range_to_utc_half_open(created_from, created_to)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    if c_start:
        conditions.append(SmsTask.created_at >= c_start)
    if c_end:
        conditions.append(SmsTask.created_at < c_end)

    if action_from or action_to:
        try:
            a_start, a_end = jalali_range_to_utc_half_open(action_from, action_to)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        if a_start:
            conditions.append(SmsTask.first_action_at.is_not(None))
            conditions.append(SmsTask.first_action_at >= a_start)
        if a_end:
            conditions.append(SmsTask.first_action_at.is_not(None))
            conditions.append(SmsTask.first_action_at < a_end)

    if q and q.strip():
        q_norm = normalize_persian_for_search(q)
        tokens = [tok for tok in q_norm.split(" ") if tok]
        action_vis = (
            or_(TaskAction.is_private.is_(False), TaskAction.actor_id == ctx.user.id)
            if not ctx.is_manager
            else True
        )
        for tok in tokens[:8]:
            pattern = f"%{tok}%"
            conditions.append(
                or_(
                    SmsTask.body_normalized.ilike(pattern),
                    exists(
                        select(TaskAction.id).where(
                            TaskAction.task_id == SmsTask.id,
                            TaskAction.report_normalized.ilike(pattern),
                            action_vis,
                        )
                    ),
                )
            )

    return conditions


async def _fetch_task_list_rows(
    db: AsyncSession,
    ctx: AuthContext,
    conditions: list,
    limit: int,
    cursor_created: Optional[datetime],
    cursor_id: Optional[int],
):
    stmt = select(SmsTask).where(*conditions)
    if cursor_created is not None and cursor_id is not None:
        stmt = stmt.where(
            or_(
                SmsTask.created_at < cursor_created,
                and_(SmsTask.created_at == cursor_created, SmsTask.id < cursor_id),
            )
        )
    stmt = stmt.order_by(SmsTask.created_at.desc(), SmsTask.id.desc()).limit(limit + 1)
    res = await db.execute(stmt)
    rows = list(res.scalars().all())
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    task_ids = [t.id for t in rows]
    receivers_map: dict[int, list[dict]] = {tid: [] for tid in task_ids}
    sender_map: dict[int, tuple[str, datetime]] = {}
    reminder_count_map: dict[int, int] = {}
    folder_map: dict[int, int] = {}
    safe_latest_map: dict[int, str] = {}

    if task_ids:
        sender_user = aliased(User)
        a_stmt = (
            select(
                TaskAssignment.task_id,
                User.id,
                User.display_name,
                User.avatar_color,
                User.job_title,
                TaskAssignment.assigned_at,
                sender_user.display_name,
            )
            .join(User, User.id == TaskAssignment.receiver_id)
            .outerjoin(sender_user, sender_user.id == TaskAssignment.sender_id)
            .where(TaskAssignment.task_id.in_(task_ids), TaskAssignment.is_active.is_(True))
            .order_by(TaskAssignment.assigned_at.desc(), TaskAssignment.id.desc())
        )
        a_res = await db.execute(a_stmt)
        for tid, uid, dname, acolor, jtitle, assigned_at, sname in a_res.all():
            receivers_map[tid].append(
                {
                    "id": uid,
                    "display_name": dname,
                    "avatar_color": acolor,
                    "job_title": jtitle,
                    "assigned_at_label": format_jalali_label(assigned_at),
                }
            )
            if uid == ctx.user.id:
                sender_map[tid] = (sname or "—", assigned_at)
            elif tid not in sender_map:
                sender_map[tid] = (sname or "—", assigned_at)

        rem_conds = [
            TaskReminder.task_id.in_(task_ids),
            TaskReminder.cancelled_at.is_(None),
            TaskReminder.fired.is_(False),
        ]
        if not ctx.is_manager:
            rem_conds.append(TaskReminder.receiver_id == ctx.user.id)
        rem_res = await db.execute(
            select(TaskReminder.task_id, func.count(TaskReminder.id))
            .where(*rem_conds)
            .group_by(TaskReminder.task_id)
        )
        for tid, cnt in rem_res.all():
            reminder_count_map[tid] = int(cnt or 0)

        f_stmt = select(FolderItem.task_id, FolderItem.folder_id).where(
            FolderItem.user_id == ctx.user.id,
            FolderItem.task_id.in_(task_ids),
        )
        f_res = await db.execute(f_stmt)
        for tid, fid in f_res.all():
            folder_map[tid] = fid

        # Latest authorized report summary per task (never leak private colleague action!)
        act_stmt = (
            select(TaskAction.task_id, TaskAction.report_text)
            .where(
                TaskAction.task_id.in_(task_ids),
                or_(TaskAction.is_private.is_(False), TaskAction.actor_id == ctx.user.id)
                if not ctx.is_manager
                else True,
            )
            .order_by(TaskAction.task_id.asc(), TaskAction.created_at.desc(), TaskAction.id.desc())
        )
        act_res = await db.execute(act_stmt)
        for tid, rtext in act_res.all():
            if tid not in safe_latest_map:
                safe_latest_map[tid] = rtext[:160]

    items = []
    for t in rows:
        sender_info = sender_map.get(t.id)
        items.append(
            {
                "id": t.id,
                "source_type": t.source_type,
                "source_label": SOURCE_LABELS.get(t.source_type, t.source_type),
                "body_summary": t.body[:120] + ("…" if len(t.body) > 120 else ""),
                "requester_name": t.requester_name,
                "priority": t.priority,
                "priority_label": PRIORITY_LABELS.get(t.priority, t.priority),
                "status": t.status,
                "status_label": STATUS_LABELS.get(t.status, t.status),
                "action_flag": t.action_flag,
                "action_flag_label": FLAG_LABELS.get(t.action_flag, t.action_flag),
                "created_at": t.created_at.isoformat(),
                "created_at_label": format_jalali_label(t.created_at),
                "first_action_at": t.first_action_at.isoformat() if t.first_action_at else None,
                "first_action_at_label": format_jalali_label(t.first_action_at) if t.first_action_at else "—",
                "latest_report_summary": safe_latest_map.get(t.id, ""),
                "view_count": t.view_count,
                "sender_name": sender_info[0] if sender_info else "—",
                "assigned_at_label": format_jalali_label(sender_info[1]) if sender_info else "—",
                "reminder_count": reminder_count_map.get(t.id, 0),
                "receivers": receivers_map.get(t.id, []),
                "personal_folder_id": folder_map.get(t.id),
                "needs_reassignment": t.needs_reassignment if ctx.is_manager else False,
                "version": t.version,
            }
        )

    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = f"{last.created_at.astimezone(UTC_TZ).strftime('%Y-%m-%dT%H:%M:%S.%fZ')}|{last.id}"

    return items, next_cursor, has_more


@router.get("/tasks")
async def list_tasks(
    view_mode: str = Query("my", pattern="^(my|supervision)$"),
    tab: str = Query("all"),
    status_filter: str = Query("all", alias="status"),
    priority: str = Query("all"),
    q: Optional[str] = Query(None),
    created_from: Optional[str] = Query(None),
    created_to: Optional[str] = Query(None),
    action_from: Optional[str] = Query(None),
    action_to: Optional[str] = Query(None),
    quick_time: Optional[str] = Query(None),
    folder_id: Optional[int] = Query(None),
    cursor: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Default view_mode fallback for author? Only employee/expert/manager allowed
    conditions = _build_scoped_task_filters(
        ctx=ctx,
        view_mode=view_mode,
        tab=tab,
        status_filter=status_filter,
        priority_filter=priority,
        q=q,
        created_from=created_from,
        created_to=created_to,
        action_from=action_from,
        action_to=action_to,
        quick_time=quick_time,
        folder_id=folder_id,
    )

    cursor_created = None
    cursor_id = None
    if cursor and "|" in cursor:
        try:
            c_ts_str, c_id_str = cursor.split("|", 1)
            cursor_created = datetime.fromisoformat(c_ts_str)
            cursor_id = int(c_id_str)
        except Exception:
            raise HTTPException(status_code=422, detail="مکان‌نمای صفحه‌بندی نامعتبر است.")

    items, next_cursor, has_more = await _fetch_task_list_rows(db, ctx, conditions, limit, cursor_created, cursor_id)

    # Scoped counters (always computed strictly after user scope, before tab/status narrowing)
    scope_conditions = _build_scoped_task_filters(
        ctx=ctx,
        view_mode=view_mode,
        tab="all",
        status_filter="all",
        priority_filter="all",
        q=None,
        created_from=None,
        created_to=None,
        action_from=None,
        action_to=None,
        quick_time=None,
        folder_id=None,
    )

    c_stmt = select(
        func.count(SmsTask.id).filter(SmsTask.status == "pending"),
        func.count(SmsTask.id).filter(SmsTask.status == "in_progress"),
        func.count(SmsTask.id).filter(SmsTask.priority == "urgent", SmsTask.status.in_(["pending", "in_progress"])),
        func.count(SmsTask.id),
    ).where(*scope_conditions)
    c_res = await db.execute(c_stmt)
    pending_count, in_progress_count, urgent_count, total_scope = c_res.one()

    # Dynamic active sender tabs for current user's active assignments
    sender_tabs_stmt = (
        select(User.id, User.display_name, func.count(TaskAssignment.task_id))
        .join(TaskAssignment, TaskAssignment.sender_id == User.id)
        .join(SmsTask, SmsTask.id == TaskAssignment.task_id)
        .where(
            TaskAssignment.receiver_id == ctx.user.id,
            TaskAssignment.is_active.is_(True),
            SmsTask.is_deleted.is_(False),
            ~exists(select(ArchivedTask.id).where(ArchivedTask.task_id == SmsTask.id)),
        )
        .group_by(User.id, User.display_name)
        .order_by(func.count(TaskAssignment.task_id).desc(), User.id.asc())
    )
    st_res = await db.execute(sender_tabs_stmt)
    sender_tabs = [{"sender_id": sid, "display_name": sname, "count": int(cnt)} for sid, sname, cnt in st_res.all()]

    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "counters": {
            "pending": int(pending_count or 0),
            "in_progress": int(in_progress_count or 0),
            "urgent": int(urgent_count or 0),
            "total": int(total_scope or 0),
        },
        "sender_tabs": sender_tabs,
    }


@router.get("/tasks/my-actions")
async def list_my_historical_actions(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Separate safe route returning ONLY the current user's own historical TaskAction entries
    without exposing transferred task details, manager notes, or current assignees.
    """
    stmt = (
        select(TaskAction)
        .where(TaskAction.actor_id == ctx.user.id)
        .order_by(TaskAction.created_at.desc(), TaskAction.id.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    actions = list(res.scalars().all())
    return {
        "items": [
            {
                "id": a.id,
                "task_id": a.task_id,
                "status_after": a.status_after,
                "status_label": STATUS_LABELS.get(a.status_after, a.status_after),
                "report_text": a.report_text,
                "is_private": a.is_private,
                "created_at": a.created_at.isoformat(),
                "created_at_label": format_jalali_label(a.created_at),
            }
            for a in actions
        ]
    }


@router.post("/tasks/direct")
async def create_direct_task(
    payload: TaskDirectCreateRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if payload.idempotency_key:
        existing_res = await db.execute(
            select(SmsTask).where(SmsTask.idempotency_key == payload.idempotency_key)
        )
        existing = existing_res.scalar_one_or_none()
        if existing:
            return {"task_id": existing.id, "duplicate": True}

    try:
        phone_norm = normalize_iran_phone(payload.requester_phone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Validate 1-2 active, eligible receivers
    rec_res = await db.execute(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .where(
            User.id.in_(payload.receiver_ids),
            User.is_active.is_(True),
            User.is_deleted.is_(False),
            UserRole.role.in_([ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER]),
        )
        .distinct()
    )
    receivers = list(rec_res.scalars().all())
    if len(receivers) != len(payload.receiver_ids):
        raise HTTPException(status_code=422, detail="یک یا چند گیرندهٔ انتخاب‌شده معتبر یا فعال نیستند.")

    now = utc_now()
    task = SmsTask(
        source_type=payload.source_type,
        body=payload.body.strip(),
        body_normalized=normalize_persian_for_search(payload.body),
        requester_name=payload.requester_name.strip(),
        requester_phone_norm=phone_norm,
        priority=payload.priority,
        status="pending",
        action_flag=payload.action_flag,
        manager_note=payload.manager_note.strip(),
        created_by=ctx.user.id,
        created_at=now,
        idempotency_key=payload.idempotency_key,
    )
    db.add(task)
    await db.flush()

    for r in receivers:
        db.add(
            TaskAssignment(
                task_id=task.id,
                sender_id=ctx.user.id,
                receiver_id=r.id,
                priority_at_assignment=task.priority,
                assigned_at=now,
                is_active=True,
            )
        )

    rec_names = "، ".join(r.display_name for r in receivers)
    await add_task_event(
        db,
        task_id=task.id,
        actor=ctx.user,
        actor_roles=ctx.roles,
        event_type="direct_created",
        details={"source": SOURCE_LABELS.get(task.source_type), "receivers": rec_names},
    )

    outbox_ids: list[int] = []
    for r in receivers:
        oid = await create_user_notification(
            db,
            user_id=r.id,
            notif_type="task_assigned",
            title="پروندهٔ جدید ارجاع شد",
            body=f"پرونده #{task.id} ({PRIORITY_LABELS[task.priority]}) از سوی {ctx.user.display_name} به شما ارجاع شد.",
            dedup_key=f"direct_assign:{task.id}:{r.id}",
            task_id=task.id,
        )
        if oid:
            outbox_ids.append(oid)

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="task.direct_create",
        target_type="sms_task",
        target_id=str(task.id),
        after_state={"priority": task.priority, "receiver_ids": payload.receiver_ids},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )

    await notify_outbox_signal(db, outbox_ids)
    await db.commit()
    return {"task_id": task.id, "duplicate": False}


@router.get("/tasks/{task_id}")
async def get_task_detail(
    task_id: int,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Strictly read-only detail endpoint (never increments view_count or alters status)."""
    task, _ = await assert_task_accessible(db, ctx, task_id, allow_archived_for_manager=True)

    # Active receivers
    sender_user = aliased(User)
    rec_res = await db.execute(
        select(
            User.id,
            User.display_name,
            User.job_title,
            User.avatar_color,
            TaskAssignment.assigned_at,
            TaskAssignment.forward_reason,
            sender_user.display_name,
        )
        .join(TaskAssignment, TaskAssignment.receiver_id == User.id)
        .outerjoin(sender_user, sender_user.id == TaskAssignment.sender_id)
        .where(TaskAssignment.task_id == task_id, TaskAssignment.is_active.is_(True))
        .order_by(TaskAssignment.assigned_at.desc(), TaskAssignment.id.desc())
    )
    rec_rows = rec_res.all()
    receivers = [
        {
            "id": uid,
            "display_name": dname,
            "job_title": jtitle,
            "avatar_color": acolor,
            "assigned_at_label": format_jalali_label(assigned_at),
            "forward_reason": freason or "",
            "sender_name": sname or "—",
        }
        for uid, dname, jtitle, acolor, assigned_at, freason, sname in rec_rows
    ]
    my_rec = next((r for r in receivers if r["id"] == ctx.user.id), receivers[0] if receivers else None)

    # Authorized actions
    act_stmt = (
        select(TaskAction, User.display_name)
        .join(User, User.id == TaskAction.actor_id)
        .where(
            TaskAction.task_id == task_id,
            or_(TaskAction.is_private.is_(False), TaskAction.actor_id == ctx.user.id)
            if not ctx.is_manager
            else True,
        )
        .order_by(TaskAction.created_at.desc(), TaskAction.id.desc())
    )
    act_res = await db.execute(act_stmt)
    actions = [
        {
            "id": a.id,
            "actor_id": a.actor_id,
            "actor_name": actor_name,
            "status_after": a.status_after,
            "status_label": STATUS_LABELS.get(a.status_after, a.status_after),
            "report_text": a.report_text,
            "is_private": a.is_private,
            "created_at": a.created_at.isoformat(),
            "created_at_label": format_jalali_label(a.created_at),
        }
        for a, actor_name in act_res.all()
    ]

    # Authorized notes
    note_stmt = (
        select(TaskNote, User.display_name)
        .join(User, User.id == TaskNote.owner_id)
        .where(
            TaskNote.task_id == task_id,
            or_(
                TaskNote.owner_id == ctx.user.id,
                TaskNote.visibility == "shared_active_manager",
            ),
        )
        .order_by(TaskNote.created_at.desc(), TaskNote.id.desc())
    )
    note_res = await db.execute(note_stmt)
    notes = [
        {
            "id": n.id,
            "owner_id": n.owner_id,
            "owner_name": owner_name,
            "body": n.body,
            "visibility": n.visibility,
            "created_at": n.created_at.isoformat(),
            "created_at_label": format_jalali_label(n.created_at),
        }
        for n, owner_name in note_res.all()
    ]

    # Timeline events (sanitized: filter out private details for non-managers)
    ev_res = await db.execute(
        select(TaskEvent)
        .where(TaskEvent.task_id == task_id)
        .order_by(TaskEvent.created_at.desc(), TaskEvent.id.desc())
    )
    timeline = []
    for ev in ev_res.scalars().all():
        details = dict(ev.details or {})
        if not ctx.is_manager and details.get("is_private") and ev.actor_id != ctx.user.id:
            continue
        timeline.append(
            {
                "id": ev.id,
                "actor_display_name": ev.actor_display_name,
                "actor_role_label": ev.actor_role_label,
                "event_type": ev.event_type,
                "created_at": ev.created_at.isoformat(),
                "created_at_label": format_jalali_label(ev.created_at),
                "details": details,
            }
        )

    # Personal folder for current user
    f_res = await db.execute(
        select(FolderItem.folder_id).where(FolderItem.task_id == task_id, FolderItem.user_id == ctx.user.id)
    )
    personal_folder_id = f_res.scalar_one_or_none()

    rem_conds = [
        TaskReminder.task_id == task_id,
        TaskReminder.cancelled_at.is_(None),
        TaskReminder.fired.is_(False),
    ]
    if not ctx.is_manager:
        rem_conds.append(TaskReminder.receiver_id == ctx.user.id)
    reminder_count = int((await db.execute(select(func.count(TaskReminder.id)).where(*rem_conds))).scalar() or 0)

    return {
        "id": task.id,
        "source_type": task.source_type,
        "source_label": SOURCE_LABELS.get(task.source_type, task.source_type),
        "body": task.body,
        "requester_name": task.requester_name,
        "requester_phone": task.requester_phone_norm,
        "priority": task.priority,
        "priority_label": PRIORITY_LABELS.get(task.priority, task.priority),
        "status": task.status,
        "status_label": STATUS_LABELS.get(task.status, task.status),
        "action_flag": task.action_flag,
        "action_flag_label": FLAG_LABELS.get(task.action_flag, task.action_flag),
        "manager_note": task.manager_note if ctx.is_manager else None,
        "created_at": task.created_at.isoformat(),
        "created_at_label": format_jalali_label(task.created_at),
        "first_action_at": task.first_action_at.isoformat() if task.first_action_at else None,
        "first_action_at_label": format_jalali_label(task.first_action_at) if task.first_action_at else "—",
        "closed_at": task.closed_at.isoformat() if task.closed_at else None,
        "closed_at_label": format_jalali_label(task.closed_at) if task.closed_at else "—",
        "view_count": task.view_count,
        "sender_name": my_rec["sender_name"] if my_rec else "—",
        "assigned_at_label": my_rec["assigned_at_label"] if my_rec else "—",
        "reminder_count": reminder_count,
        "needs_reassignment": task.needs_reassignment if ctx.is_manager else False,
        "version": task.version,
        "personal_folder_id": personal_folder_id,
        "receivers": receivers,
        "actions": actions,
        "notes": notes,
        "timeline": timeline,
    }


@router.post("/tasks/{task_id}/view")
async def record_task_view(
    task_id: int,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task, active_assign = await assert_task_accessible(db, ctx, task_id)

    if idempotency_key:
        rec_key = f"task_view:{ctx.user.id}:{task_id}:{idempotency_key}"
        existing = await db.get(IdempotencyRecord, rec_key)
        if existing:
            return existing.response_json

    task.view_count += 1
    status_changed = False
    # Only first view by an ACTIVE assignee moves pending -> in_progress; supervision browse does NOT change status
    if active_assign is not None and task.status == "pending":
        task.status = "in_progress"
        status_changed = True
        await add_task_event(
            db,
            task_id=task.id,
            actor=ctx.user,
            actor_roles=ctx.roles,
            event_type="first_view_in_progress",
            details={"view_count": task.view_count},
        )

    resp_data = {
        "task_id": task.id,
        "view_count": task.view_count,
        "status": task.status,
        "status_label": STATUS_LABELS[task.status],
        "status_changed": status_changed,
    }
    if idempotency_key:
        stmt = (
            pg_insert(IdempotencyRecord)
            .values(
                key=f"task_view:{ctx.user.id}:{task_id}:{idempotency_key}",
                scope="task_view",
                actor_id=ctx.user.id,
                response_json=resp_data,
            )
            .on_conflict_do_nothing(index_elements=["key"])
        )
        await db.execute(stmt)
    await db.commit()
    return resp_data


@router.post("/tasks/{task_id}/action")
async def submit_task_action(
    task_id: int,
    payload: TaskActionRequest,
    request: Request,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task, active_assign = await assert_task_accessible(db, ctx, task_id)

    if active_assign is None and not ctx.is_manager:
        raise HTTPException(status_code=403, detail="فقط گیرندهٔ فعال یا مدیر مجاز به ثبت اقدام است.")

    if payload.idempotency_key:
        idem_rec = await db.get(IdempotencyRecord, f"task_action:{ctx.user.id}:{task_id}:{payload.idempotency_key}")
        if idem_rec:
            return idem_rec.response_json

    if task.status in ("success", "failed"):
        raise HTTPException(status_code=409, detail="این پرونده بسته شده است و امکان ثبت اقدام جدید بدون بازگشایی وجود ندارد.")

    # Optimistic version lock
    if task.version != payload.version:
        raise HTTPException(
            status_code=409,
            detail="پرونده هم‌زمان توسط کاربر دیگری تغییر کرده است. لطفاً صفحه را تازه‌سازی و دوباره تلاش کنید.",
        )

    if payload.status in ("success", "failed") and payload.forward_to_ids:
        raise HTTPException(status_code=422, detail="با انتخاب وضعیت نهایی، ارجاع ثانویه مجاز نیست.")

    # Validate secondary forward BEFORE mutating anything
    forward_receivers: list[User] = []
    if payload.forward_to_ids:
        if len(set(payload.forward_to_ids)) != len(payload.forward_to_ids):
            raise HTTPException(status_code=422, detail="گیرندگان ارجاع ثانویه تکراری هستند.")
        if ctx.user.id in payload.forward_to_ids:
            raise HTTPException(status_code=422, detail="امکان ارجاع ثانویه به خودتان وجود ندارد.")

        # Fetch current active assignments
        cur_res = await db.execute(
            select(TaskAssignment).where(TaskAssignment.task_id == task_id, TaskAssignment.is_active.is_(True))
        )
        cur_actives = list(cur_res.scalars().all())
        remaining_other_ids = {a.receiver_id for a in cur_actives if a.receiver_id != ctx.user.id}

        if any(fid in remaining_other_ids for fid in payload.forward_to_ids):
            raise HTTPException(status_code=422, detail="همکار انتخاب‌شده هم‌اکنون گیرندهٔ فعال این پرونده است.")

        projected_total = len(remaining_other_ids) + len(payload.forward_to_ids)
        if projected_total > 2:
            raise HTTPException(
                status_code=409,
                detail="سقف کل ارجاع فعال پرونده ۲ نفر است. با وجود همکار دیگر، امکان انتخاب بیش از یک گیرندهٔ جدید نیست.",
            )

        rec_res = await db.execute(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .where(
                User.id.in_(payload.forward_to_ids),
                User.is_active.is_(True),
                User.is_deleted.is_(False),
                UserRole.role.in_([ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER]),
            )
            .distinct()
        )
        forward_receivers = list(rec_res.scalars().all())
        if len(forward_receivers) != len(payload.forward_to_ids):
            raise HTTPException(status_code=422, detail="گیرندهٔ ارجاع ثانویه معتبر یا فعال نیست.")

    now = utc_now()
    action_row = TaskAction(
        task_id=task.id,
        actor_id=ctx.user.id,
        status_after=payload.status,
        report_text=payload.report_text.strip(),
        report_normalized=normalize_persian_for_search(payload.report_text),
        is_private=payload.is_private,
        idempotency_key=payload.idempotency_key,
        created_at=now,
    )
    db.add(action_row)
    await db.flush()

    if task.first_action_at is None:
        task.first_action_at = now
        await award_timely_action_score(db, ctx.user.id, task.id, active_assign, now)

    if not payload.is_private:
        task.latest_report_summary = payload.report_text.strip()[:240]
        task.latest_action_id = action_row.id

    task.status = payload.status
    task.needs_reassignment = False

    outbox_ids: list[int] = []
    await add_task_event(
        db,
        task_id=task.id,
        actor=ctx.user,
        actor_roles=ctx.roles,
        event_type="action_recorded",
        details={
            "status_after": STATUS_LABELS[payload.status],
            "is_private": payload.is_private,
        },
    )

    if payload.status in ("success", "failed"):
        task.closed_at = now
        task.closed_by = ctx.user.id
        # End all active assignments & folders & unfired reminders
        act_assigns_res = await db.execute(
            select(TaskAssignment).where(TaskAssignment.task_id == task.id, TaskAssignment.is_active.is_(True))
        )
        for a in act_assigns_res.scalars().all():
            a.is_active = False
            a.ended_at = now
            a.end_reason = "closed"
            await db.execute(delete(FolderItem).where(FolderItem.task_id == task.id, FolderItem.user_id == a.receiver_id))
        await cancel_all_task_reminders(db, task.id, f"task_{payload.status}", ctx.user, ctx.roles)

        if payload.status == "success":
            await award_task_success_score(db, ctx.user.id, task.id)

    elif forward_receivers:
        forward_reason = payload.forward_reason.strip()
        # End sender active assignment cleanly & preserve other active assignee
        if active_assign is not None:
            active_assign.is_active = False
            active_assign.ended_at = now
            active_assign.end_reason = "transferred"
            await cancel_user_task_reminders_and_folder(db, task.id, ctx.user.id, "transferred", ctx.user, ctx.roles)

        for fr in forward_receivers:
            db.add(
                TaskAssignment(
                    task_id=task.id,
                    sender_id=ctx.user.id,
                    receiver_id=fr.id,
                    priority_at_assignment=task.priority,
                    forward_reason=forward_reason,
                    assigned_at=now,
                    is_active=True,
                )
            )
            oid = await create_user_notification(
                db,
                user_id=fr.id,
                notif_type="task_forwarded",
                title="ارجاع ثانویهٔ پرونده",
                body=f"پرونده #{task.id} از سوی {ctx.user.display_name} به شما ارجاع شد."
                + (f" دلیل: {forward_reason}" if forward_reason else ""),
                dedup_key=f"forward:{task.id}:{action_row.id}:{fr.id}",
                task_id=task.id,
            )
            if oid:
                outbox_ids.append(oid)

        await add_task_event(
            db,
            task_id=task.id,
            actor=ctx.user,
            actor_roles=ctx.roles,
            event_type="forwarded",
            details={
                "receivers": "، ".join(r.display_name for r in forward_receivers),
                "reason": forward_reason,
            },
        )

    task.version += 1
    ev_update = await emit_outbox_event(
        db,
        event_type="task.updated",
        channel="tasks",
        payload={"task_id": task.id, "status": task.status, "forwarded": bool(forward_receivers)},
    )
    outbox_ids.append(ev_update.id)

    resp_data = {
        "task_id": task.id,
        "action_id": action_row.id,
        "status": task.status,
        "status_label": STATUS_LABELS[task.status],
        "version": task.version,
        "forwarded_to": [r.id for r in forward_receivers],
        "sender_removed": bool(forward_receivers and active_assign is not None),
    }

    if payload.idempotency_key:
        await db.execute(
            pg_insert(IdempotencyRecord)
            .values(
                key=f"task_action:{ctx.user.id}:{task_id}:{payload.idempotency_key}",
                scope="task_action",
                actor_id=ctx.user.id,
                response_json=resp_data,
            )
            .on_conflict_do_nothing()
        )

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="task.action",
        target_type="sms_task",
        target_id=str(task.id),
        after_state={"status": task.status, "forwarded_to": [r.id for r in forward_receivers]},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )

    await notify_outbox_signal(db, outbox_ids)
    await db.commit()
    return resp_data


@router.patch("/tasks/{task_id}")
async def update_task_by_manager(
    task_id: int,
    payload: TaskManagerUpdateRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await db.get(SmsTask, task_id, with_for_update=True)
    if not task or task.is_deleted:
        raise HTTPException(status_code=404, detail="پرونده یافت نشد.")
    if task.version != payload.version:
        raise HTTPException(status_code=409, detail="نسخهٔ پرونده تغییر کرده است. لطفاً تازه‌سازی کنید.")

    before_state = {
        "priority": task.priority,
        "action_flag": task.action_flag,
        "manager_note": task.manager_note,
    }

    now = utc_now()
    outbox_ids: list[int] = []
    reassigned_names: list[str] = []

    if payload.receiver_ids is not None:
        if task.status in ("success", "failed"):
            raise HTTPException(
                status_code=409,
                detail="تغییر گیرنده برای پروندهٔ خاتمه‌یافته بدون بازگشایی مجاز نیست.",
            )
        rec_res = await db.execute(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .where(
                User.id.in_(payload.receiver_ids),
                User.is_active.is_(True),
                User.is_deleted.is_(False),
                UserRole.role.in_([ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER]),
            )
            .distinct()
        )
        new_receivers = list(rec_res.scalars().all())
        if len(new_receivers) != len(payload.receiver_ids):
            raise HTTPException(status_code=422, detail="یک یا چند گیرندهٔ انتخاب‌شده معتبر یا فعال نیستند.")

        cur_res = await db.execute(
            select(TaskAssignment).where(TaskAssignment.task_id == task.id, TaskAssignment.is_active.is_(True))
        )
        cur_actives = list(cur_res.scalars().all())
        cur_ids = {a.receiver_id for a in cur_actives}
        new_ids = set(payload.receiver_ids)

        for a in cur_actives:
            if a.receiver_id not in new_ids:
                a.is_active = False
                a.ended_at = now
                a.end_reason = "reassigned"
                await cancel_user_task_reminders_and_folder(
                    db, task.id, a.receiver_id, "reassigned", ctx.user, ctx.roles
                )

        for nr in new_receivers:
            reassigned_names.append(nr.display_name)
            if nr.id not in cur_ids:
                db.add(
                    TaskAssignment(
                        task_id=task.id,
                        sender_id=ctx.user.id,
                        receiver_id=nr.id,
                        priority_at_assignment=payload.priority,
                        assigned_at=now,
                        is_active=True,
                    )
                )
                oid = await create_user_notification(
                    db,
                    user_id=nr.id,
                    notif_type="task_assigned",
                    title="ارجاع یا بازتخصیص پرونده",
                    body=f"پرونده #{task.id} ({PRIORITY_LABELS[payload.priority]}) از سوی {ctx.user.display_name} به شما ارجاع شد.",
                    dedup_key=f"mgr_reassign:{task.id}:{task.version}:{nr.id}",
                    task_id=task.id,
                )
                if oid:
                    outbox_ids.append(oid)

        task.needs_reassignment = False

    task.priority = payload.priority
    task.action_flag = payload.action_flag
    task.manager_note = payload.manager_note.strip()
    task.version += 1

    await add_task_event(
        db,
        task_id=task.id,
        actor=ctx.user,
        actor_roles=ctx.roles,
        event_type="manager_updated",
        details={
            "priority": PRIORITY_LABELS[task.priority],
            "action_flag": FLAG_LABELS[task.action_flag],
            "receivers": "، ".join(reassigned_names) if reassigned_names else None,
        },
    )
    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="task.manager_update",
        target_type="sms_task",
        target_id=str(task.id),
        before_state=before_state,
        after_state={
            "priority": task.priority,
            "action_flag": task.action_flag,
            "receiver_ids": payload.receiver_ids,
        },
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    ev = await emit_outbox_event(
        db,
        event_type="task.updated",
        channel="tasks",
        payload={"task_id": task.id, "priority": task.priority},
    )
    outbox_ids.append(ev.id)
    await notify_outbox_signal(db, outbox_ids)
    await db.commit()
    return {
        "task_id": task.id,
        "priority": task.priority,
        "action_flag": task.action_flag,
        "manager_note": task.manager_note,
        "needs_reassignment": task.needs_reassignment,
        "version": task.version,
    }


@router.post("/tasks/{task_id}/archive")
async def archive_single_task(
    task_id: int,
    request: Request,
    payload: Optional[TaskSingleArchiveRequest] = None,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await db.get(SmsTask, task_id)
    if not task or task.is_deleted:
        raise HTTPException(status_code=404, detail="پرونده یافت نشد.")
    if task.status not in ("success", "failed"):
        raise HTTPException(status_code=422, detail="فقط پروندهٔ خاتمه‌یافته (موفق یا ناموفق) قابل بایگانی است.")

    reason = payload.reason.strip() if payload and payload.reason else ""
    now = utc_now()
    await db.execute(
        pg_insert(ArchivedTask)
        .values(
            task_id=task.id,
            archived_by=ctx.user.id,
            archived_at=now,
            reason=reason or None,
        )
        .on_conflict_do_nothing(index_elements=["task_id"])
    )
    await add_task_event(
        db,
        task_id=task.id,
        actor=ctx.user,
        actor_roles=ctx.roles,
        event_type="archived",
        details={"reason": reason},
    )
    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="task.archive_single",
        target_type="sms_task",
        target_id=str(task.id),
        after_state={"reason": reason},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    ev = await emit_outbox_event(
        db,
        event_type="task.updated",
        channel="tasks",
        payload={"task_id": task.id, "archived": True},
    )
    await notify_outbox_signal(db, [ev.id])
    await db.commit()
    return {"ok": True, "task_id": task.id}


@router.post("/tasks/{task_id}/reopen")
async def reopen_task(
    task_id: int,
    payload: TaskReopenRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await db.get(SmsTask, task_id)
    if not task or task.is_deleted:
        raise HTTPException(status_code=404, detail="پرونده یافت نشد.")
    if task.version != payload.version:
        raise HTTPException(status_code=409, detail="نسخهٔ پرونده تغییر کرده است. لطفاً تازه‌سازی کنید.")
    if task.status not in ("success", "failed"):
        raise HTTPException(status_code=422, detail="فقط پروندهٔ خاتمه‌یافته قابل بازگشایی است.")

    receivers: list[User] = []
    if payload.receiver_ids:
        rec_res = await db.execute(
            select(User).where(
                User.id.in_(payload.receiver_ids),
                User.is_active.is_(True),
                User.is_deleted.is_(False),
            )
        )
        receivers = list(rec_res.scalars().all())
        if len(receivers) != len(payload.receiver_ids):
            raise HTTPException(status_code=422, detail="گیرندگان انتخاب‌شده معتبر نیستند.")

    now = utc_now()
    prev_status = task.status
    task.status = "in_progress"
    task.closed_at = None
    task.closed_by = None
    # Note: historical first_action_at is NEVER cleared!
    task.needs_reassignment = len(receivers) == 0
    task.version += 1

    for r in receivers:
        db.add(
            TaskAssignment(
                task_id=task.id,
                sender_id=ctx.user.id,
                receiver_id=r.id,
                priority_at_assignment=task.priority,
                assigned_at=now,
                is_active=True,
            )
        )

    await add_task_event(
        db,
        task_id=task.id,
        actor=ctx.user,
        actor_roles=ctx.roles,
        event_type="reopened",
        details={"reason": payload.reason.strip(), "from_status": prev_status},
    )
    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="task.reopen",
        target_type="sms_task",
        target_id=str(task.id),
        before_state={"status": prev_status},
        after_state={"status": "in_progress", "reason": payload.reason.strip()},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"task_id": task.id, "status": task.status, "version": task.version}


@router.post("/tasks/{task_id}/notes")
async def create_task_note(
    task_id: int,
    payload: TaskNoteCreateRequest,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task, _ = await assert_task_accessible(db, ctx, task_id)
    note = TaskNote(
        task_id=task.id,
        owner_id=ctx.user.id,
        body=payload.body.strip(),
        visibility=payload.visibility,
    )
    db.add(note)
    await db.flush()
    await add_task_event(
        db,
        task_id=task.id,
        actor=ctx.user,
        actor_roles=ctx.roles,
        event_type="note_added",
        details={"visibility": payload.visibility, "is_private": payload.visibility == "private"},
    )
    await db.commit()
    return {
        "id": note.id,
        "owner_id": note.owner_id,
        "owner_name": ctx.user.display_name,
        "body": note.body,
        "visibility": note.visibility,
        "created_at": note.created_at.isoformat(),
        "created_at_label": format_jalali_label(note.created_at),
    }


@router.get("/tasks/{task_id}/reminders")
async def list_task_reminders(
    task_id: int,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await assert_task_accessible(db, ctx, task_id)
    stmt = (
        select(TaskReminder)
        .where(
            TaskReminder.task_id == task_id,
            TaskReminder.receiver_id == ctx.user.id,
            TaskReminder.cancelled_at.is_(None),
        )
        .order_by(TaskReminder.due_at.asc())
    )
    res = await db.execute(stmt)
    return {
        "items": [
            {
                "id": r.id,
                "due_at": r.due_at.isoformat(),
                "due_at_label": format_jalali_label(r.due_at),
                "note": r.note,
                "fired": r.fired,
                "fired_at_label": format_jalali_label(r.fired_at) if r.fired_at else None,
            }
            for r in res.scalars().all()
        ]
    }


@router.post("/tasks/{task_id}/reminders")
async def create_task_reminder(
    task_id: int,
    payload: TaskReminderCreateRequest,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task, active_assign = await assert_task_accessible(db, ctx, task_id)
    if active_assign is None:
        raise HTTPException(status_code=403, detail="یادآور فقط برای گیرندهٔ فعال این پرونده قابل تنظیم است.")
    if task.status in ("success", "failed"):
        raise HTTPException(status_code=422, detail="برای پروندهٔ خاتمه‌یافته نمی‌توان یادآور تنظیم کرد.")

    try:
        due_utc = parse_jalali_datetime_tehran_to_utc(payload.jalali_date, payload.tehran_time)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    idem = payload.idempotency_key or f"rem:{ctx.user.id}:{task_id}:{due_utc.isoformat()}:{payload.note[:30]}"
    existing = await db.execute(select(TaskReminder).where(TaskReminder.idempotency_key == idem))
    ex = existing.scalar_one_or_none()
    if ex:
        return {"id": ex.id, "due_at_label": format_jalali_label(ex.due_at)}

    rem = TaskReminder(
        task_id=task.id,
        assignment_id=active_assign.id,
        receiver_id=ctx.user.id,
        due_at=due_utc,
        note=payload.note.strip(),
        idempotency_key=idem,
    )
    db.add(rem)
    await db.commit()
    return {
        "id": rem.id,
        "due_at": rem.due_at.isoformat(),
        "due_at_label": format_jalali_label(rem.due_at),
        "note": rem.note,
        "fired": rem.fired,
    }


@router.delete("/tasks/{task_id}/reminders/{reminder_id}")
async def delete_task_reminder(
    task_id: int,
    reminder_id: int,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await assert_task_accessible(db, ctx, task_id)
    rem = await db.get(TaskReminder, reminder_id)
    if not rem or rem.task_id != task_id or rem.receiver_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="یادآور یافت نشد.")
    await db.delete(rem)
    await db.commit()
    return {"ok": True}


@router.get("/folders")
async def list_personal_folders(
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = (
        select(
            PersonalFolder.id,
            PersonalFolder.name,
            func.count(FolderItem.id),
        )
        .outerjoin(
            FolderItem,
            and_(
                FolderItem.folder_id == PersonalFolder.id,
                FolderItem.user_id == ctx.user.id,
            ),
        )
        .where(PersonalFolder.user_id == ctx.user.id)
        .group_by(PersonalFolder.id, PersonalFolder.name)
        .order_by(PersonalFolder.name.asc())
    )
    res = await db.execute(stmt)
    return {"items": [{"id": fid, "name": fname, "count": int(cnt)} for fid, fname, cnt in res.all()]}


@router.post("/folders")
async def create_personal_folder(
    payload: FolderCreateRequest,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    name = payload.name.strip()
    ex_res = await db.execute(
        select(PersonalFolder).where(PersonalFolder.user_id == ctx.user.id, PersonalFolder.name == name)
    )
    if ex_res.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="فولدر با این نام هم‌اکنون وجود دارد.")
    folder = PersonalFolder(user_id=ctx.user.id, name=name)
    db.add(folder)
    await db.commit()
    return {"id": folder.id, "name": folder.name, "count": 0}


@router.delete("/folders/{folder_id}")
async def delete_personal_folder(
    folder_id: int,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    folder = await db.get(PersonalFolder, folder_id)
    if not folder or folder.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="فولدر یافت نشد.")
    # Deleting folder removes FolderItems via CASCADE without deleting any SmsTask!
    await db.delete(folder)
    await db.commit()
    return {"ok": True}


@router.put("/tasks/{task_id}/folder")
async def assign_task_to_personal_folder(
    task_id: int,
    payload: TaskFolderAssignRequest,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await assert_task_accessible(db, ctx, task_id)
    await db.execute(delete(FolderItem).where(FolderItem.user_id == ctx.user.id, FolderItem.task_id == task_id))
    if payload.folder_id is not None:
        folder = await db.get(PersonalFolder, payload.folder_id)
        if not folder or folder.user_id != ctx.user.id:
            raise HTTPException(status_code=404, detail="فولدر شخصی یافت نشد.")
        db.add(FolderItem(folder_id=folder.id, task_id=task_id, user_id=ctx.user.id))
    await db.commit()
    return {"task_id": task_id, "folder_id": payload.folder_id}


@router.post("/tasks/{task_id}/trash")
async def soft_delete_task(
    task_id: int,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await db.get(SmsTask, task_id)
    if not task or task.is_deleted:
        raise HTTPException(status_code=404, detail="پرونده یافت نشد.")
    now = utc_now()
    task.is_deleted = True
    task.deleted_at = now
    task.deleted_by = ctx.user.id
    task.version += 1

    act_res = await db.execute(
        select(TaskAssignment).where(TaskAssignment.task_id == task.id, TaskAssignment.is_active.is_(True))
    )
    for a in act_res.scalars().all():
        a.is_active = False
        a.ended_at = now
        a.end_reason = "deleted"
        await db.execute(delete(FolderItem).where(FolderItem.task_id == task.id, FolderItem.user_id == a.receiver_id))

    await cancel_all_task_reminders(db, task.id, "task_soft_deleted", ctx.user, ctx.roles)
    await add_task_event(db, task.id, ctx.user, ctx.roles, "soft_deleted", {})
    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="task.soft_delete",
        target_type="sms_task",
        target_id=str(task.id),
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"ok": True}


@router.get("/exports/{fmt}")
async def export_tasks(
    fmt: str,
    request: Request,
    view_mode: str = Query("my", pattern="^(my|supervision)$"),
    tab: str = Query("all"),
    status_filter: str = Query("all", alias="status"),
    priority: str = Query("all"),
    q: Optional[str] = Query(None),
    created_from: Optional[str] = Query(None),
    created_to: Optional[str] = Query(None),
    action_from: Optional[str] = Query(None),
    action_to: Optional[str] = Query(None),
    quick_time: Optional[str] = Query(None),
    folder_id: Optional[int] = Query(None),
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if fmt not in ("word", "excel", "csv"):
        raise HTTPException(status_code=404, detail="قالب خروجی پشتیبانی نمی‌شود.")

    settings = get_settings()
    conditions = _build_scoped_task_filters(
        ctx=ctx,
        view_mode=view_mode,
        tab=tab,
        status_filter=status_filter,
        priority_filter=priority,
        q=q,
        created_from=created_from,
        created_to=created_to,
        action_from=action_from,
        action_to=action_to,
        quick_time=quick_time,
        folder_id=folder_id,
    )
    items, _, has_more = await _fetch_task_list_rows(
        db, ctx, conditions, limit=min(settings.export_max_rows, 5000), cursor_created=None, cursor_id=None
    )

    headers = ["شناسه", "منبع", "متن درخواست", "اولویت", "تاریخ ثبت", "اولین اقدام", "آخرین گزارش مجاز", "وضعیت", "تعداد مشاهده"]
    rows = [
        [
            it["id"],
            it["source_label"],
            it["body_summary"],
            it["priority_label"],
            it["created_at_label"],
            it["first_action_at_label"],
            it["latest_report_summary"] or "—",
            it["status_label"],
            it["view_count"],
        ]
        for it in items
    ]

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action=f"export.tasks.{fmt}",
        target_type="export",
        target_id=f"rows:{len(rows)}",
        after_state={"view_mode": view_mode, "truncated": has_more},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()

    if fmt == "word":
        data = build_rtl_docx(
            title="گزارش پرونده‌های پیام‌های مردمی — هرمزگان بیدار",
            subtitle=f"تعداد ردیف: {len(rows)}" + (" (محدودشده به سقف خروجی)" if has_more else ""),
            headers=headers,
            rows=rows,
        )
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": 'attachment; filename="hormozgan-tasks.docx"', "Cache-Control": "no-store"},
        )
    if fmt == "excel":
        data = build_rtl_xlsx("پرونده‌ها", headers, rows, numeric_cols={0, 8})
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="hormozgan-tasks.xlsx"', "Cache-Control": "no-store"},
        )
    data = build_utf8_bom_csv(headers, rows)
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="hormozgan-tasks.csv"', "Cache-Control": "no-store"},
    )
