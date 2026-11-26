import json
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import and_, delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.exports import build_rtl_xlsx
from app.models import (
    ArchivedTask,
    ArchivedVisit,
    Draft,
    LoginLog,
    Notification,
    PublicVisit,
    SmsTask,
    TaskAction,
    TaskAssignment,
    User,
    UserRating,
    UserRole,
)
from app.rbac import ROLE_ADMIN, ROLE_MANAGER, AuthContext, get_current_auth, require_roles
from app.schemas import (
    ArchivePreviewRequest,
    ArchiveRestoreRequest,
    BackupRestoreConfirmRequest,
    TrashPurgeRequest,
    TrashRestoreRequest,
)
from app.services import add_audit_log, add_task_event
from app.utils.jalali import format_jalali_label, jalali_range_to_utc_half_open, utc_now
from app.utils.persian import normalize_persian_for_search
from app.utils.security import extract_client_ip, verify_password

router = APIRouter(prefix="/api/v1", tags=["عملیات مدیریت، سطل زباله، آرشیو و بکاپ"])

BACKUP_SCHEMA_VERSION = "2.0"
PURGE_CONFIRM_PHRASE = "حذف دائم"
RESTORE_CONFIRM_PHRASE = "تأیید بازیابی"


# ---------------------------------------------------------------------------
# Notifications (All Authenticated Users)
# ---------------------------------------------------------------------------
@router.get("/notifications")
async def list_notifications(
    after_id: Optional[int] = Query(None),
    limit: int = Query(30, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(Notification).where(Notification.user_id == ctx.user.id)
    if after_id is not None:
        stmt = stmt.where(Notification.id > after_id).order_by(Notification.id.asc())
    else:
        stmt = stmt.order_by(Notification.id.desc())
    stmt = stmt.limit(limit)
    res = await db.execute(stmt)
    rows = list(res.scalars().all())

    unread_count = int(
        (
            await db.execute(
                select(func.count(Notification.id)).where(
                    Notification.user_id == ctx.user.id, Notification.is_read.is_(False)
                )
            )
        ).scalar()
        or 0
    )
    return {
        "items": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "body": n.body,
                "task_id": n.task_id,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat(),
                "created_at_label": format_jalali_label(n.created_at),
            }
            for n in rows
        ],
        "unread_count": unread_count,
    }


@router.post("/notifications/read")
async def mark_notifications_read(
    notification_ids: Optional[list[int]] = None,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = utc_now()
    stmt = select(Notification).where(Notification.user_id == ctx.user.id, Notification.is_read.is_(False))
    if notification_ids:
        stmt = stmt.where(Notification.id.in_(notification_ids))
    res = await db.execute(stmt)
    for n in res.scalars().all():
        n.is_read = True
        n.read_at = now
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Trash (Admin Only)
# ---------------------------------------------------------------------------
@router.get("/trash")
async def list_trash(
    target_type: str = Query("task", pattern="^(task|visit)$"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if target_type == "task":
        stmt = (
            select(SmsTask)
            .where(SmsTask.is_deleted.is_(True))
            .order_by(SmsTask.deleted_at.desc(), SmsTask.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await db.execute(stmt)).scalars().all())
        total = int(
            (await db.execute(select(func.count(SmsTask.id)).where(SmsTask.is_deleted.is_(True)))).scalar() or 0
        )
        return {
            "items": [
                {
                    "id": t.id,
                    "target_type": "task",
                    "title": f"پرونده #{t.id} — {t.requester_name or 'بدون نام'}",
                    "summary": t.body[:140],
                    "status": t.status,
                    "deleted_at_label": format_jalali_label(t.deleted_at),
                    "version": t.version,
                }
                for t in rows
            ],
            "total": total,
        }

    stmt = (
        select(PublicVisit)
        .where(PublicVisit.is_deleted.is_(True))
        .order_by(PublicVisit.deleted_at.desc(), PublicVisit.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    total = int(
        (await db.execute(select(func.count(PublicVisit.id)).where(PublicVisit.is_deleted.is_(True)))).scalar() or 0
    )
    return {
        "items": [
            {
                "id": v.id,
                "target_type": "visit",
                "title": f"مراجعه #{v.id} — {v.person_or_org}",
                "summary": v.request_desc[:140],
                "status": v.status,
                "deleted_at_label": format_jalali_label(v.deleted_at),
                "version": v.version,
            }
            for v in rows
        ],
        "total": total,
    }


@router.post("/trash/{item_id}/restore")
async def restore_from_trash(
    item_id: int,
    payload: TrashRestoreRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if payload.target_type == "visit":
        visit = await db.get(PublicVisit, item_id, with_for_update=True)
        if not visit or not visit.is_deleted:
            raise HTTPException(status_code=404, detail="مورد حذف‌شده یافت نشد.")
        if visit.version != payload.version:
            raise HTTPException(status_code=409, detail="تعارض نسخه در بازیابی.")
        visit.is_deleted = False
        visit.deleted_at = None
        visit.deleted_by = None
        visit.version += 1
        await add_audit_log(
            db,
            actor_id=ctx.user.id,
            action="trash.restore_visit",
            target_type="public_visit",
            target_id=str(visit.id),
            ip_address=extract_client_ip(request),
            correlation_id=ctx.session.correlation_id,
        )
        await db.commit()
        return {"ok": True, "id": visit.id, "needs_reassignment": False}

    task = await db.get(SmsTask, item_id, with_for_update=True)
    if not task or not task.is_deleted:
        raise HTTPException(status_code=404, detail="پروندهٔ حذف‌شده یافت نشد.")
    if task.version != payload.version:
        raise HTTPException(status_code=409, detail="تعارض نسخه در بازیابی پرونده.")

    task.is_deleted = False
    task.deleted_at = None
    task.deleted_by = None
    task.version += 1

    # Check most recent receivers before deletion; restore ONLY if task is open AND receiver is active
    needs_reassignment = False
    if task.status in ("pending", "in_progress"):
        last_assigns = await db.execute(
            select(TaskAssignment, User.is_active, User.is_deleted)
            .join(User, User.id == TaskAssignment.receiver_id)
            .where(TaskAssignment.task_id == task.id, TaskAssignment.end_reason == "deleted")
            .order_by(TaskAssignment.ended_at.desc(), TaskAssignment.id.desc())
            .limit(2)
        )
        restored_any = False
        for assign, u_active, u_deleted in last_assigns.all():
            if u_active and not u_deleted:
                assign.is_active = True
                assign.ended_at = None
                assign.end_reason = None
                restored_any = True
            else:
                needs_reassignment = True
        if not restored_any:
            needs_reassignment = True

    task.needs_reassignment = needs_reassignment
    # Note: cancelled reminders are NOT automatically recreated/re-fired!
    await add_task_event(
        db,
        task_id=task.id,
        actor=ctx.user,
        actor_roles=ctx.roles,
        event_type="restored_from_trash",
        details={"needs_reassignment": needs_reassignment},
    )
    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="trash.restore_task",
        target_type="sms_task",
        target_id=str(task.id),
        after_state={"needs_reassignment": needs_reassignment},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"ok": True, "id": task.id, "needs_reassignment": needs_reassignment}


@router.post("/trash/purge")
async def purge_trash_permanently(
    payload: TrashPurgeRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Step 2 security verification: phrase + current password re-auth + server-verified count
    if payload.confirm_phrase.strip() != PURGE_CONFIRM_PHRASE:
        raise HTTPException(status_code=422, detail=f"عبارت تأیید باید دقیقاً «{PURGE_CONFIRM_PHRASE}» باشد.")
    if not verify_password(payload.password, ctx.user.password_hash):
        raise HTTPException(status_code=403, detail="رمز عبور فعلی جهت تأیید هویت صحیح نیست.")

    unique_ids = list(dict.fromkeys(payload.ids))
    if payload.target_type == "task":
        res = await db.execute(
            select(SmsTask).where(SmsTask.id.in_(unique_ids), SmsTask.is_deleted.is_(True)).with_for_update()
        )
        rows = list(res.scalars().all())
    else:
        res = await db.execute(
            select(PublicVisit).where(PublicVisit.id.in_(unique_ids), PublicVisit.is_deleted.is_(True)).with_for_update()
        )
        rows = list(res.scalars().all())

    if len(rows) != payload.expected_count or len(rows) == 0:
        raise HTTPException(
            status_code=409,
            detail=f"تعداد اقلام قابل حذف دائم ({len(rows)}) با مقدار تأییدشده ({payload.expected_count}) مطابقت ندارد.",
        )

    purged_ids = [r.id for r in rows]
    for r in rows:
        await db.delete(r)

    # Keep only minimal non-content metadata in immutable audit_log
    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action=f"trash.purge_{payload.target_type}",
        target_type=payload.target_type,
        target_id=",".join(str(i) for i in purged_ids),
        after_state={"purged_count": len(purged_ids)},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"purged_count": len(purged_ids), "purged_ids": purged_ids}


# ---------------------------------------------------------------------------
# Login Logs (Admin Only)
# ---------------------------------------------------------------------------
@router.get("/login-logs")
async def list_login_logs(
    user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conds = []
    if user_id is not None:
        conds.append(LoginLog.user_id == user_id)
    if action in ("login", "logout"):
        conds.append(LoginLog.action == action)

    stmt = (
        select(LoginLog, User.display_name)
        .join(User, User.id == LoginLog.user_id)
        .where(*conds)
        .order_by(LoginLog.created_at.desc(), LoginLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    total = int((await db.execute(select(func.count(LoginLog.id)).where(*conds))).scalar() or 0)
    return {
        "items": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "username": log.username_snapshot,
                "display_name": dname,
                "action": log.action,
                "action_label": "ورود" if log.action == "login" else "خروج",
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "created_at": log.created_at.isoformat(),
                "created_at_label": format_jalali_label(log.created_at),
            }
            for log, dname in res.all()
        ],
        "total": total,
    }


@router.get("/login-logs/export/excel")
async def export_login_logs_excel(
    request: Request,
    user_id: Optional[int] = Query(None),
    action: Optional[str] = Query(None),
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    conds = []
    if user_id is not None:
        conds.append(LoginLog.user_id == user_id)
    if action in ("login", "logout"):
        conds.append(LoginLog.action == action)

    stmt = (
        select(LoginLog, User.display_name)
        .join(User, User.id == LoginLog.user_id)
        .where(*conds)
        .order_by(LoginLog.created_at.desc(), LoginLog.id.desc())
        .limit(5000)
    )
    res = await db.execute(stmt)
    # By default IP and User-Agent are NOT included in Excel export (restricted to admin detail view)
    headers = ["ردیف", "کاربر", "نام کاربری", "عملیات", "تاریخ و ساعت شمسی"]
    rows = [
        [
            log.id,
            dname,
            log.username_snapshot,
            "ورود" if log.action == "login" else "خروج",
            format_jalali_label(log.created_at),
        ]
        for log, dname in res.all()
    ]
    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="export.login_logs.excel",
        target_type="login_log",
        target_id=f"rows:{len(rows)}",
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    data = build_rtl_xlsx("ورود و خروج", headers, rows, numeric_cols={0})
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="hormozgan-login-logs.xlsx"', "Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# Work Archive (Manager or Admin)
# ---------------------------------------------------------------------------
@router.get("/archive")
async def list_archive(
    target_type: str = Query("task", pattern="^(task|visit)$"),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER, ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if target_type == "task":
        conds = [SmsTask.is_deleted.is_(False)]
        if q and q.strip():
            conds.append(SmsTask.body_normalized.ilike(f"%{normalize_persian_for_search(q)}%"))
        stmt = (
            select(ArchivedTask, SmsTask)
            .join(SmsTask, SmsTask.id == ArchivedTask.task_id)
            .where(*conds)
            .order_by(ArchivedTask.archived_at.desc(), ArchivedTask.id.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await db.execute(stmt)).all()
        total = int(
            (
                await db.execute(
                    select(func.count(ArchivedTask.id)).join(SmsTask, SmsTask.id == ArchivedTask.task_id).where(*conds)
                )
            ).scalar()
            or 0
        )
        return {
            "items": [
                {
                    "id": t.id,
                    "target_type": "task",
                    "title": f"پرونده #{t.id} — {t.requester_name or 'بدون نام'}",
                    "summary": t.body[:140],
                    "status": t.status,
                    "archived_at_label": format_jalali_label(a.archived_at),
                    "reason": a.reason,
                }
                for a, t in rows
            ],
            "total": total,
        }

    conds = [PublicVisit.is_deleted.is_(False)]
    if q and q.strip():
        conds.append(PublicVisit.person_or_org.ilike(f"%{q.strip()}%"))
    stmt = (
        select(ArchivedVisit, PublicVisit)
        .join(PublicVisit, PublicVisit.id == ArchivedVisit.visit_id)
        .where(*conds)
        .order_by(ArchivedVisit.archived_at.desc(), ArchivedVisit.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    total = int(
        (
            await db.execute(
                select(func.count(ArchivedVisit.id))
                .join(PublicVisit, PublicVisit.id == ArchivedVisit.visit_id)
                .where(*conds)
            )
        ).scalar()
        or 0
    )
    return {
        "items": [
            {
                "id": v.id,
                "target_type": "visit",
                "title": f"مراجعه #{v.id} — {v.person_or_org}",
                "summary": v.request_desc[:140],
                "status": v.status,
                "archived_at_label": format_jalali_label(a.archived_at),
                "reason": a.reason,
            }
            for a, v in rows
        ],
        "total": total,
    }


def _archive_candidate_filters(payload: ArchivePreviewRequest):
    before_utc = None
    if payload.before_jalali_date and payload.before_jalali_date.strip():
        try:
            _, before_utc = jalali_range_to_utc_half_open(None, payload.before_jalali_date)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    if payload.target_type == "task":
        allowed = {"success", "failed"}
        statuses = [s for s in payload.statuses if s in allowed] or ["success", "failed"]
        conds = [
            SmsTask.is_deleted.is_(False),
            SmsTask.status.in_(statuses),
            ~exists(select(ArchivedTask.id).where(ArchivedTask.task_id == SmsTask.id)),
        ]
        if before_utc:
            conds.append(SmsTask.created_at < before_utc)
        return conds, statuses

    allowed = {"approved", "rejected"}
    statuses = [s for s in payload.statuses if s in allowed] or ["approved", "rejected"]
    conds = [
        PublicVisit.is_deleted.is_(False),
        PublicVisit.status.in_(statuses),
        ~exists(select(ArchivedVisit.id).where(ArchivedVisit.visit_id == PublicVisit.id)),
    ]
    if before_utc:
        conds.append(PublicVisit.created_at < before_utc)
    return conds, statuses


@router.post("/archive/preview")
async def preview_archive_clear(
    payload: ArchivePreviewRequest,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER, ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conds, statuses = _archive_candidate_filters(payload)
    if payload.target_type == "task":
        cnt = int((await db.execute(select(func.count(SmsTask.id)).where(*conds))).scalar() or 0)
    else:
        cnt = int((await db.execute(select(func.count(PublicVisit.id)).where(*conds))).scalar() or 0)
    return {"target_type": payload.target_type, "statuses": statuses, "matching_count": cnt}


@router.post("/archive/clear-done")
async def execute_archive_clear(
    payload: ArchivePreviewRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER, ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conds, statuses = _archive_candidate_filters(payload)
    now = utc_now()
    if payload.target_type == "task":
        ids = list((await db.execute(select(SmsTask.id).where(*conds))).scalars().all())
        if ids:
            values = [
                {"task_id": tid, "archived_by": ctx.user.id, "archived_at": now, "reason": payload.reason.strip() or None}
                for tid in ids
            ]
            await db.execute(pg_insert(ArchivedTask).values(values).on_conflict_do_nothing(index_elements=["task_id"]))
    else:
        ids = list((await db.execute(select(PublicVisit.id).where(*conds))).scalars().all())
        if ids:
            values = [
                {"visit_id": vid, "archived_by": ctx.user.id, "archived_at": now, "reason": payload.reason.strip() or None}
                for vid in ids
            ]
            await db.execute(pg_insert(ArchivedVisit).values(values).on_conflict_do_nothing(index_elements=["visit_id"]))

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action=f"archive.clear_{payload.target_type}",
        target_type=payload.target_type,
        target_id=f"count:{len(ids)}",
        after_state={"statuses": statuses, "archived_count": len(ids)},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"archived_count": len(ids)}


@router.post("/archive/restore")
async def restore_from_archive(
    payload: ArchiveRestoreRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER, ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if payload.target_type == "task":
        res = await db.execute(delete(ArchivedTask).where(ArchivedTask.task_id.in_(payload.ids)).returning(ArchivedTask.task_id))
        restored_ids = list(res.scalars().all())
    else:
        res = await db.execute(delete(ArchivedVisit).where(ArchivedVisit.visit_id.in_(payload.ids)).returning(ArchivedVisit.visit_id))
        restored_ids = list(res.scalars().all())

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action=f"archive.restore_{payload.target_type}",
        target_type=payload.target_type,
        target_id=",".join(str(i) for i in restored_ids),
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"restored_count": len(restored_ids), "restored_ids": restored_ids}


# ---------------------------------------------------------------------------
# Versioned Application JSON Backup & Dry-Run Restore (Admin Only)
# ---------------------------------------------------------------------------
@router.get("/backups/export")
async def export_json_backup(
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Exports sanitized application data in a versioned JSON schema.
    NEVER includes password_hash, tokens, sessions, or secrets.
    """
    users = list((await db.execute(select(User).order_by(User.id.asc()))).scalars().all())
    tasks = list((await db.execute(select(SmsTask).order_by(SmsTask.id.asc()))).scalars().all())
    drafts = list((await db.execute(select(Draft).order_by(Draft.id.asc()))).scalars().all())
    visits = list((await db.execute(select(PublicVisit).order_by(PublicVisit.id.asc()))).scalars().all())
    ratings = list((await db.execute(select(UserRating).order_by(UserRating.id.asc()))).scalars().all())

    backup_obj = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "exported_at": utc_now().isoformat(),
        "exported_at_label": format_jalali_label(utc_now()),
        "counts": {
            "users": len(users),
            "sms_tasks": len(tasks),
            "drafts": len(drafts),
            "public_visits": len(visits),
            "user_ratings": len(ratings),
        },
        "data": {
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "job_title": u.job_title,
                    "department": u.department,
                    "display_access_level": u.display_access_level,
                    "org_role_type": u.org_role_type,
                    "is_active": u.is_active,
                    "is_deleted": u.is_deleted,
                }
                for u in users
            ],
            "sms_tasks": [
                {
                    "id": t.id,
                    "source_type": t.source_type,
                    "requester_name": t.requester_name,
                    "requester_phone_norm": t.requester_phone_norm,
                    "body": t.body,
                    "priority": t.priority,
                    "status": t.status,
                    "action_flag": t.action_flag,
                    "created_by": t.created_by,
                    "created_at": t.created_at.isoformat(),
                    "is_deleted": t.is_deleted,
                }
                for t in tasks
            ],
            "drafts": [
                {
                    "id": d.id,
                    "author_id": d.author_id,
                    "source_type": d.source_type,
                    "body": d.body,
                    "priority": d.priority,
                    "status": d.status,
                    "distributed_task_id": d.distributed_task_id,
                }
                for d in drafts
            ],
            "public_visits": [
                {
                    "id": v.id,
                    "creator_id": v.creator_id,
                    "person_or_org": v.person_or_org,
                    "phone_norm": v.phone_norm,
                    "request_desc": v.request_desc,
                    "followup_desc": v.followup_desc,
                    "action_taken": v.action_taken,
                    "status": v.status,
                }
                for v in visits
            ],
        },
    }

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="backup.export",
        target_type="backup",
        target_id=BACKUP_SCHEMA_VERSION,
        after_state=backup_obj["counts"],
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()

    raw_bytes = json.dumps(backup_obj, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        content=raw_bytes,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="hormozgan-backup-v2.json"',
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


async def _validate_backup_payload(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="ساختار فایل بکاپ معتبر نیست.")
    if payload.get("schema_version") != BACKUP_SCHEMA_VERSION:
        raise HTTPException(
            status_code=422,
            detail=f"نسخهٔ بکاپ ({payload.get('schema_version')}) با نسخهٔ سامانه ({BACKUP_SCHEMA_VERSION}) سازگار نیست.",
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="بخش data در فایل بکاپ وجود ندارد.")

    # Ensure zero forbidden secret fields
    raw_dump = json.dumps(payload, ensure_ascii=False)
    for forbidden in ("password_hash", "token_hash", "csrf_token"):
        if forbidden in raw_dump:
            raise HTTPException(status_code=422, detail="فایل بکاپ حاوی کلیدهای حساس غیرمجاز است.")

    incoming_tasks = data.get("sms_tasks", [])
    incoming_visits = data.get("public_visits", [])
    incoming_users = data.get("users", [])
    if not isinstance(incoming_tasks, list) or not isinstance(incoming_visits, list):
        raise HTTPException(status_code=422, detail="ساختار آرایه‌های بکاپ نامعتبر است.")

    existing_user_ids = set((await db.execute(select(User.id))).scalars().all())
    existing_task_ids = set((await db.execute(select(SmsTask.id))).scalars().all())
    existing_visit_ids = set((await db.execute(select(PublicVisit.id))).scalars().all())

    incoming_user_ids = {u["id"] for u in incoming_users if isinstance(u, dict) and "id" in u}
    valid_creator_ids = existing_user_ids | incoming_user_ids

    fk_errors: list[str] = []
    new_tasks = 0
    for t in incoming_tasks:
        tid = t.get("id")
        if not isinstance(tid, int):
            fk_errors.append("شناسهٔ نامعتبر در sms_tasks")
            continue
        cby = t.get("created_by")
        if cby is not None and cby not in valid_creator_ids:
            fk_errors.append(f"پرونده #{tid}: مرجع ثبت‌کننده ({cby}) یافت نشد")
        if tid not in existing_task_ids:
            new_tasks += 1

    new_visits = 0
    for v in incoming_visits:
        vid = v.get("id")
        cid = v.get("creator_id")
        if cid not in valid_creator_ids:
            fk_errors.append(f"مراجعه #{vid}: مرجع ثبت‌کننده ({cid}) یافت نشد")
        if vid not in existing_visit_ids:
            new_visits += 1

    return {
        "valid": len(fk_errors) == 0,
        "schema_version": payload.get("schema_version"),
        "exported_at_label": payload.get("exported_at_label", "—"),
        "counts": {
            "incoming_users": len(incoming_users),
            "incoming_tasks": len(incoming_tasks),
            "new_tasks_to_insert": new_tasks,
            "existing_tasks_skipped": len(incoming_tasks) - new_tasks,
            "incoming_visits": len(incoming_visits),
            "new_visits_to_insert": new_visits,
        },
        "fk_errors": fk_errors[:20],
    }


@router.post("/backups/dry-run")
async def backup_dry_run(
    payload: dict[str, Any],
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Strictly read-only dry-run validation & diff preview (zero DB mutations)."""
    return await _validate_backup_payload(db, payload)


@router.post("/backups/restore")
async def backup_restore_confirm(
    payload: BackupRestoreConfirmRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if payload.confirm_phrase.strip() != RESTORE_CONFIRM_PHRASE:
        raise HTTPException(status_code=422, detail=f"عبارت تأیید باید دقیقاً «{RESTORE_CONFIRM_PHRASE}» باشد.")
    if not verify_password(payload.password, ctx.user.password_hash):
        raise HTTPException(status_code=403, detail="رمز عبور جهت تأیید بازیابی صحیح نیست.")

    preview = await _validate_backup_payload(db, payload.backup_payload)
    if not preview["valid"]:
        raise HTTPException(status_code=422, detail="اعتبارسنجی ارجاعات بکاپ ناموفق بود.", headers={"X-Backup-Errors": "1"})

    data = payload.backup_payload["data"]
    existing_task_ids = set((await db.execute(select(SmsTask.id))).scalars().all())
    existing_visit_ids = set((await db.execute(select(PublicVisit.id))).scalars().all())
    existing_user_ids = set((await db.execute(select(User.id))).scalars().all())

    inserted_tasks = 0
    for t in data.get("sms_tasks", []):
        if t["id"] in existing_task_ids:
            continue
        cby = t.get("created_by") if t.get("created_by") in existing_user_ids else None
        db.add(
            SmsTask(
                id=t["id"],
                source_type=t.get("source_type", "sms"),
                requester_name=t.get("requester_name", ""),
                requester_phone_norm=t.get("requester_phone_norm", ""),
                body=t.get("body", ""),
                body_normalized=normalize_persian_for_search(t.get("body", "")),
                priority=t.get("priority", "normal"),
                status=t.get("status", "pending"),
                action_flag=t.get("action_flag", "action"),
                created_by=cby,
                is_deleted=bool(t.get("is_deleted", False)),
            )
        )
        inserted_tasks += 1

    inserted_visits = 0
    for v in data.get("public_visits", []):
        if v["id"] in existing_visit_ids:
            continue
        cid = v.get("creator_id") if v.get("creator_id") in existing_user_ids else ctx.user.id
        db.add(
            PublicVisit(
                id=v["id"],
                creator_id=cid,
                person_or_org=v.get("person_or_org", ""),
                phone_norm=v.get("phone_norm", ""),
                request_desc=v.get("request_desc", ""),
                followup_desc=v.get("followup_desc", ""),
                action_taken=v.get("action_taken", ""),
                status=v.get("status", "pending_review"),
            )
        )
        inserted_visits += 1

    await db.flush()
    # Sync PostgreSQL sequences safely after explicit ID inserts
    await db.execute(select(func.setval("sms_tasks_id_seq", func.coalesce(func.max(SmsTask.id), 1))))
    await db.execute(select(func.setval("public_visits_id_seq", func.coalesce(func.max(PublicVisit.id), 1))))

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="backup.restore",
        target_type="backup",
        target_id=BACKUP_SCHEMA_VERSION,
        after_state={"inserted_tasks": inserted_tasks, "inserted_visits": inserted_visits},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"ok": True, "inserted_tasks": inserted_tasks, "inserted_visits": inserted_visits}
