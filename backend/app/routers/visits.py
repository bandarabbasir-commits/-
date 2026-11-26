from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import and_, delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.exports import build_rtl_xlsx
from app.models import ArchivedVisit, PublicVisit, User, VisitFolder, VisitFolderItem
from app.rbac import ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER, AuthContext, get_current_auth, require_roles
from app.schemas import FolderCreateRequest, TaskFolderAssignRequest, VisitBulkActionRequest, VisitCreateRequest, VisitReviewRequest
from app.services import add_audit_log
from app.utils.jalali import format_jalali_label, utc_now
from app.utils.persian import normalize_iran_phone, normalize_persian_for_search
from app.utils.security import extract_client_ip

router = APIRouter(prefix="/api/v1/visits", tags=["مراجعات مردمی"])

VISIT_STATUS_LABELS = {
    "pending_review": "در انتظار بررسی",
    "approved": "تأییدشده",
    "rejected": "ردشده",
}


@router.get("")
async def list_visits(
    view: str = Query("my", pattern="^(my|pending_review|approved|rejected|archived)$"),
    folder_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    ctx: AuthContext = Depends(require_roles(ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conditions = [PublicVisit.is_deleted.is_(False)]
    is_archived_expr = exists(select(ArchivedVisit.id).where(ArchivedVisit.visit_id == PublicVisit.id))

    if view == "archived":
        if not ctx.is_manager:
            raise HTTPException(status_code=403, detail="مشاهدهٔ بایگانی مراجعات فقط برای مدیر مجاز است.")
        conditions.append(is_archived_expr)
    else:
        conditions.append(~is_archived_expr)

    if view == "my":
        conditions.append(PublicVisit.creator_id == ctx.user.id)
    elif view in ("pending_review", "approved", "rejected"):
        if not ctx.is_manager:
            conditions.append(PublicVisit.creator_id == ctx.user.id)
        conditions.append(PublicVisit.status == view)

    if folder_id is not None:
        conditions.append(
            exists(
                select(VisitFolderItem.id).where(
                    VisitFolderItem.visit_id == PublicVisit.id,
                    VisitFolderItem.user_id == ctx.user.id,
                    VisitFolderItem.folder_id == folder_id,
                )
            )
        )

    if q and q.strip():
        pattern = f"%{normalize_persian_for_search(q)}%"
        conditions.append(
            func.lower(PublicVisit.person_or_org).ilike(pattern)
            | func.lower(PublicVisit.request_desc).ilike(pattern)
        )

    stmt = (
        select(PublicVisit, User.display_name)
        .join(User, User.id == PublicVisit.creator_id)
        .where(*conditions)
        .order_by(PublicVisit.created_at.desc(), PublicVisit.id.desc())
        .limit(limit)
        .offset(offset)
    )
    res = await db.execute(stmt)
    rows = res.all()

    visit_ids = [v.id for v, _ in rows]
    folder_map: dict[int, int] = {}
    if visit_ids:
        f_res = await db.execute(
            select(VisitFolderItem.visit_id, VisitFolderItem.folder_id).where(
                VisitFolderItem.user_id == ctx.user.id,
                VisitFolderItem.visit_id.in_(visit_ids),
            )
        )
        folder_map = {vid: fid for vid, fid in f_res.all()}

    items = [
        {
            "id": v.id,
            "creator_id": v.creator_id,
            "creator_name": cname,
            "person_or_org": v.person_or_org,
            "phone": v.phone_norm,
            "request_desc": v.request_desc,
            "followup_desc": v.followup_desc,
            "action_taken": v.action_taken,
            "status": v.status,
            "status_label": VISIT_STATUS_LABELS.get(v.status, v.status),
            "review_note": v.review_note,
            "reviewed_at_label": format_jalali_label(v.reviewed_at) if v.reviewed_at else None,
            "created_at": v.created_at.isoformat(),
            "created_at_label": format_jalali_label(v.created_at),
            "folder_id": folder_map.get(v.id),
            "version": v.version,
        }
        for v, cname in rows
    ]

    # Aggregated count by exact (person_or_org, phone_norm) within user's scope — never auto-merged by name alone!
    total_count = int((await db.execute(select(func.count(PublicVisit.id)).where(*conditions))).scalar() or 0)
    return {"items": items, "total": total_count}


@router.post("")
async def create_visit(
    payload: VisitCreateRequest,
    ctx: AuthContext = Depends(require_roles(ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        phone_norm = normalize_iran_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    visit = PublicVisit(
        creator_id=ctx.user.id,
        person_or_org=payload.person_or_org.strip(),
        phone_norm=phone_norm,
        request_desc=payload.request_desc.strip(),
        followup_desc=payload.followup_desc.strip(),
        action_taken=payload.action_taken.strip(),
        status="pending_review",
    )
    db.add(visit)
    await db.commit()
    return {
        "id": visit.id,
        "status": visit.status,
        "message": "گزارش برای بررسی ارسال شد",
    }


@router.post("/{visit_id}/review")
async def review_visit(
    visit_id: int,
    payload: VisitReviewRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    visit = await db.get(PublicVisit, visit_id, with_for_update=True)
    if not visit or visit.is_deleted:
        raise HTTPException(status_code=404, detail="گزارش مراجعه یافت نشد.")
    if visit.version != payload.version:
        raise HTTPException(status_code=409, detail="تعارض نسخه در بررسی مراجعه؛ لطفاً تازه‌سازی کنید.")
    if payload.decision == "rejected" and not payload.review_note.strip():
        raise HTTPException(status_code=422, detail="برای رد گزارش، درج دلیل الزامی است.")

    visit.status = payload.decision
    visit.review_note = payload.review_note.strip() or None
    visit.reviewed_by = ctx.user.id
    visit.reviewed_at = utc_now()
    visit.version += 1

    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action=f"visit.{payload.decision}",
        target_type="public_visit",
        target_id=str(visit.id),
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"id": visit.id, "status": visit.status, "status_label": VISIT_STATUS_LABELS[visit.status], "version": visit.version}


@router.get("/folders")
async def list_visit_folders(
    ctx: AuthContext = Depends(require_roles(ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = (
        select(VisitFolder.id, VisitFolder.name, func.count(VisitFolderItem.id))
        .outerjoin(
            VisitFolderItem,
            and_(VisitFolderItem.folder_id == VisitFolder.id, VisitFolderItem.user_id == ctx.user.id),
        )
        .where(VisitFolder.user_id == ctx.user.id)
        .group_by(VisitFolder.id, VisitFolder.name)
        .order_by(VisitFolder.name.asc())
    )
    res = await db.execute(stmt)
    return {"items": [{"id": fid, "name": fname, "count": int(cnt)} for fid, fname, cnt in res.all()]}


@router.post("/folders")
async def create_visit_folder(
    payload: FolderCreateRequest,
    ctx: AuthContext = Depends(require_roles(ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    name = payload.name.strip()
    ex = await db.execute(select(VisitFolder).where(VisitFolder.user_id == ctx.user.id, VisitFolder.name == name))
    if ex.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="فولدر با این نام وجود دارد.")
    vf = VisitFolder(user_id=ctx.user.id, name=name)
    db.add(vf)
    await db.commit()
    return {"id": vf.id, "name": vf.name, "count": 0}


@router.delete("/folders/{folder_id}")
async def delete_visit_folder(
    folder_id: int,
    ctx: AuthContext = Depends(require_roles(ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    vf = await db.get(VisitFolder, folder_id)
    if not vf or vf.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="فولدر یافت نشد.")
    await db.delete(vf)
    await db.commit()
    return {"ok": True}


@router.put("/{visit_id}/folder")
async def assign_visit_folder(
    visit_id: int,
    payload: TaskFolderAssignRequest,
    ctx: AuthContext = Depends(require_roles(ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    visit = await db.get(PublicVisit, visit_id)
    if not visit or visit.is_deleted:
        raise HTTPException(status_code=404, detail="مراجعه یافت نشد.")
    if not ctx.is_manager and visit.creator_id != ctx.user.id:
        raise HTTPException(status_code=403, detail="مجوز تغییر فولدر این مراجعه را ندارید.")

    await db.execute(
        delete(VisitFolderItem).where(VisitFolderItem.user_id == ctx.user.id, VisitFolderItem.visit_id == visit_id)
    )
    if payload.folder_id is not None:
        vf = await db.get(VisitFolder, payload.folder_id)
        if not vf or vf.user_id != ctx.user.id:
            raise HTTPException(status_code=404, detail="فولدر یافت نشد.")
        db.add(VisitFolderItem(folder_id=vf.id, visit_id=visit_id, user_id=ctx.user.id))
    await db.commit()
    return {"visit_id": visit_id, "folder_id": payload.folder_id}


@router.post("/bulk-trash")
async def bulk_trash_visits(
    payload: VisitBulkActionRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = utc_now()
    res = await db.execute(select(PublicVisit).where(PublicVisit.id.in_(payload.visit_ids), PublicVisit.is_deleted.is_(False)))
    visits = list(res.scalars().all())
    for v in visits:
        v.is_deleted = True
        v.deleted_at = now
        v.deleted_by = ctx.user.id
        v.version += 1
    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="visits.bulk_soft_delete",
        target_type="public_visit",
        target_id=f"count:{len(visits)}",
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"deleted_count": len(visits)}


@router.get("/export/excel")
async def export_visits_excel(
    view: str = Query("my", pattern="^(my|pending_review|approved|rejected)$"),
    folder_id: Optional[int] = Query(None),
    ctx: AuthContext = Depends(require_roles(ROLE_EMPLOYEE, ROLE_EXPERT, ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    conditions = [
        PublicVisit.is_deleted.is_(False),
        ~exists(select(ArchivedVisit.id).where(ArchivedVisit.visit_id == PublicVisit.id)),
    ]
    if view == "my" or not ctx.is_manager:
        conditions.append(PublicVisit.creator_id == ctx.user.id)
    if view in ("pending_review", "approved", "rejected"):
        conditions.append(PublicVisit.status == view)
    if folder_id is not None:
        conditions.append(
            exists(
                select(VisitFolderItem.id).where(
                    VisitFolderItem.visit_id == PublicVisit.id,
                    VisitFolderItem.user_id == ctx.user.id,
                    VisitFolderItem.folder_id == folder_id,
                )
            )
        )
    res = await db.execute(
        select(PublicVisit, User.display_name)
        .join(User, User.id == PublicVisit.creator_id)
        .where(*conditions)
        .order_by(PublicVisit.created_at.desc())
        .limit(3000)
    )
    headers = ["شناسه", "فرد یا سازمان", "تلفن", "شرح درخواست", "پیگیری", "اقدام انجام‌شده", "وضعیت", "ثبت‌کننده", "تاریخ ثبت"]
    rows = [
        [
            v.id,
            v.person_or_org,
            v.phone_norm,
            v.request_desc,
            v.followup_desc,
            v.action_taken,
            VISIT_STATUS_LABELS.get(v.status, v.status),
            cname,
            format_jalali_label(v.created_at),
        ]
        for v, cname in res.all()
    ]
    data = build_rtl_xlsx("مراجعات مردمی", headers, rows, numeric_cols={0})
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="hormozgan-visits.xlsx"', "Cache-Control": "no-store"},
    )
