from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Draft, SmsTask, TaskAssignment, User, UserRole
from app.rbac import (
    ROLE_AUTHOR,
    ROLE_EMPLOYEE,
    ROLE_EXPERT,
    ROLE_MANAGER,
    AuthContext,
    get_current_auth,
    require_roles,
)
from app.realtime import notify_outbox_signal
from app.schemas import (
    DraftCloseRequest,
    DraftCreateRequest,
    DraftDistributeRequest,
    DraftTrashRequest,
    DraftUpdateRequest,
)
from app.services import add_audit_log, add_task_event, create_user_notification
from app.utils.jalali import format_jalali_label, utc_now
from app.utils.persian import normalize_iran_phone, normalize_persian_for_search
from app.utils.security import extract_client_ip

router = APIRouter(prefix="/api/v1/drafts", tags=["پیش‌نویس‌ها"])

DRAFT_STATUS_LABELS = {
    "new": "جدید",
    "edited": "ویرایش‌شده",
    "ready_to_distribute": "در انتظار توزیع",
    "distributed": "توزیع‌شده",
    "closed": "بسته‌شده",
}
PRIORITY_LABELS = {"urgent": "فوری", "medium": "متوسط", "normal": "عادی"}
SOURCE_LABELS = {"sms": "پیامک", "phone": "تلفن", "in_person": "حضوری", "social": "شبکه اجتماعی"}


def _serialize_draft(d: Draft, author_name: str, is_manager: bool) -> dict:
    return {
        "id": d.id,
        "author_id": d.author_id,
        "author_name": author_name,
        "source_type": d.source_type,
        "source_label": SOURCE_LABELS.get(d.source_type, d.source_type),
        "requester_name": d.requester_name,
        "requester_phone": d.requester_phone_norm,
        "body": d.body,
        "priority": d.priority,
        "priority_label": PRIORITY_LABELS.get(d.priority, d.priority),
        "status": d.status,
        "status_label": DRAFT_STATUS_LABELS.get(d.status, d.status),
        "action_flag": d.action_flag,
        "manager_note": d.manager_note if is_manager else None,
        "edited_at": d.edited_at.isoformat() if d.edited_at else None,
        "edited_at_label": format_jalali_label(d.edited_at) if d.edited_at else None,
        "distributed_task_id": d.distributed_task_id if is_manager else None,
        "closed_at_label": format_jalali_label(d.closed_at) if d.closed_at else None,
        "created_at": d.created_at.isoformat(),
        "created_at_label": format_jalali_label(d.created_at),
        "version": d.version,
    }


@router.get("")
async def list_drafts(
    status_filter: str = Query("open", alias="status"),
    author_id: Optional[int] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_roles(ROLE_AUTHOR, ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conditions = [Draft.is_deleted.is_(False)]
    if not ctx.is_manager:
        # Author sees ONLY own drafts
        conditions.append(Draft.author_id == ctx.user.id)
    elif author_id is not None:
        conditions.append(Draft.author_id == author_id)

    if status_filter == "open":
        conditions.append(Draft.status.in_(["new", "edited", "ready_to_distribute"]))
    elif status_filter == "history":
        conditions.append(Draft.status.in_(["distributed", "closed"]))
    elif status_filter in DRAFT_STATUS_LABELS:
        conditions.append(Draft.status == status_filter)

    stmt = (
        select(Draft, User.display_name)
        .join(User, User.id == Draft.author_id)
        .where(*conditions)
        .order_by(Draft.created_at.desc(), Draft.id.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    items = [_serialize_draft(d, aname, ctx.is_manager) for d, aname in res.all()]

    count_stmt = select(func.count(Draft.id)).where(*conditions)
    total = int((await db.execute(count_stmt)).scalar() or 0)
    return {"items": items, "total": total}


@router.post("")
async def create_draft(
    payload: DraftCreateRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_AUTHOR, ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    phone_norm = ""
    if payload.requester_phone and payload.requester_phone.strip():
        try:
            phone_norm = normalize_iran_phone(payload.requester_phone)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    draft = Draft(
        author_id=ctx.user.id,
        source_type=payload.source_type,
        requester_name=payload.requester_name.strip(),
        requester_phone_norm=phone_norm,
        body=payload.body.strip(),
        body_normalized=normalize_persian_for_search(payload.body),
        priority=payload.priority,
        action_flag=payload.action_flag,
        status="new",
    )
    db.add(draft)
    await db.flush()
    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="draft.create",
        target_type="draft",
        target_id=str(draft.id),
        after_state={"priority": draft.priority, "source_type": draft.source_type},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return _serialize_draft(draft, ctx.user.display_name, ctx.is_manager)


@router.patch("/{draft_id}")
async def update_draft(
    draft_id: int,
    payload: DraftUpdateRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    draft = await db.get(Draft, draft_id, with_for_update=True)
    if not draft or draft.is_deleted:
        raise HTTPException(status_code=404, detail="پیش‌نویس یافت نشد.")
    if draft.status in ("distributed", "closed"):
        raise HTTPException(status_code=409, detail="پیش‌نویس بسته‌شده یا توزیع‌شده فقط خواندنی است.")
    if draft.version != payload.version:
        raise HTTPException(status_code=409, detail="پیش‌نویس هم‌زمان ویرایش شده است. لطفاً تازه‌سازی کنید.")

    now = utc_now()
    draft.body = payload.body.strip()
    draft.body_normalized = normalize_persian_for_search(payload.body)
    draft.priority = payload.priority
    draft.action_flag = payload.action_flag
    draft.manager_note = payload.manager_note.strip()
    draft.edited_at = now
    draft.status = "ready_to_distribute" if payload.mark_ready else "edited"
    draft.version += 1

    author = await db.get(User, draft.author_id)
    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="draft.update",
        target_type="draft",
        target_id=str(draft.id),
        after_state={"status": draft.status, "priority": draft.priority},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return _serialize_draft(draft, author.display_name if author else "نویسنده", True)


@router.post("/{draft_id}/distribute")
async def distribute_draft(
    draft_id: int,
    payload: DraftDistributeRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if len(set(payload.receiver_ids)) != len(payload.receiver_ids):
        raise HTTPException(status_code=422, detail="گیرندگان انتخاب‌شده نباید تکراری باشند.")

    # Row-level lock on draft prevents concurrent duplicate distribution
    draft = await db.get(Draft, draft_id, with_for_update=True)
    if not draft or draft.is_deleted:
        raise HTTPException(status_code=404, detail="پیش‌نویس یافت نشد.")

    if payload.idempotency_key and draft.idempotency_key == payload.idempotency_key and draft.distributed_task_id:
        return {"draft_id": draft.id, "task_id": draft.distributed_task_id, "duplicate": True}

    if draft.status in ("distributed", "closed") or draft.distributed_task_id is not None:
        raise HTTPException(status_code=409, detail="این پیش‌نویس قبلاً توزیع یا بسته شده است.")
    if draft.version != payload.version:
        raise HTTPException(status_code=409, detail="تعارض نسخه در توزیع پیش‌نویس؛ لطفاً صفحه را تازه‌سازی کنید.")

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
        raise HTTPException(status_code=422, detail="یک یا چند گیرنده معتبر یا فعال نیستند.")

    author = await db.get(User, draft.author_id)
    author_name = author.display_name if author else "نویسنده"
    rec_names = "، ".join(r.display_name for r in receivers)

    now = utc_now()
    task = SmsTask(
        source_type=draft.source_type,
        body=draft.body,
        body_normalized=draft.body_normalized or normalize_persian_for_search(draft.body),
        requester_name=draft.requester_name,
        requester_phone_norm=draft.requester_phone_norm,
        priority=draft.priority,
        status="pending",
        action_flag=draft.action_flag,
        manager_note=draft.manager_note,
        created_by=ctx.user.id,
        created_at=now,
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

    trail_summary = f"پیش‌نویس توسط {author_name} ← بررسی و ارجاع توسط {ctx.user.display_name} ← {rec_names}"
    await add_task_event(
        db,
        task_id=task.id,
        actor=ctx.user,
        actor_roles=ctx.roles,
        event_type="draft_distributed",
        details={"trail": trail_summary, "draft_id": draft.id},
    )

    draft.status = "distributed"
    draft.distributed_task_id = task.id
    draft.idempotency_key = payload.idempotency_key
    draft.version += 1

    outbox_ids: list[int] = []
    for r in receivers:
        oid = await create_user_notification(
            db,
            user_id=r.id,
            notif_type="task_assigned",
            title="پروندهٔ جدید از پیش‌نویس ارجاع شد",
            body=f"پرونده #{task.id} ({PRIORITY_LABELS[task.priority]}) از سوی {ctx.user.display_name} به شما ارجاع شد.",
            dedup_key=f"draft_dist:{draft.id}:{task.id}:{r.id}",
            task_id=task.id,
        )
        if oid:
            outbox_ids.append(oid)

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="draft.distribute",
        target_type="draft",
        target_id=str(draft.id),
        after_state={"task_id": task.id, "receiver_ids": payload.receiver_ids},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )

    await notify_outbox_signal(db, outbox_ids)
    await db.commit()
    return {"draft_id": draft.id, "task_id": task.id, "trail": trail_summary, "duplicate": False}


@router.post("/{draft_id}/close")
async def close_draft_without_task(
    draft_id: int,
    payload: DraftCloseRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    draft = await db.get(Draft, draft_id, with_for_update=True)
    if not draft or draft.is_deleted:
        raise HTTPException(status_code=404, detail="پیش‌نویس یافت نشد.")
    if draft.status in ("distributed", "closed"):
        raise HTTPException(status_code=409, detail="پیش‌نویس قبلاً بسته یا توزیع شده است.")
    if draft.version != payload.version:
        raise HTTPException(status_code=409, detail="تعارض نسخه در بستن پیش‌نویس.")

    draft.status = "closed"
    draft.closed_at = utc_now()
    draft.closed_by = ctx.user.id
    if payload.manager_note.strip():
        draft.manager_note = payload.manager_note.strip()
    draft.version += 1

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="draft.close",
        target_type="draft",
        target_id=str(draft.id),
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"draft_id": draft.id, "status": draft.status}


@router.post("/{draft_id}/trash")
async def soft_delete_draft(
    draft_id: int,
    payload: DraftTrashRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    draft = await db.get(Draft, draft_id, with_for_update=True)
    if not draft or draft.is_deleted:
        raise HTTPException(status_code=404, detail="پیش‌نویس یافت نشد.")
    if draft.status == "distributed":
        raise HTTPException(status_code=409, detail="پیش‌نویس توزیع‌شده را نمی‌توان حذف کرد.")
    if draft.version != payload.version:
        raise HTTPException(status_code=409, detail="تعارض نسخه در حذف پیش‌نویس.")

    draft.is_deleted = True
    draft.deleted_at = utc_now()
    draft.delete_reason = payload.reason.strip()
    draft.version += 1

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="draft.soft_delete",
        target_type="draft",
        target_id=str(draft.id),
        after_state={"reason": draft.delete_reason},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"ok": True}
