import uuid
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User, UserRating
from app.rbac import ROLE_MANAGER, AuthContext, get_current_auth, require_roles
from app.schemas import RatingCreateRequest, RatingUpdateRequest
from app.services import add_audit_log
from app.utils.jalali import format_jalali_label, tehran_today_date
from app.utils.security import extract_client_ip

router = APIRouter(prefix="/api/v1/ratings", tags=["تابلوی افتخارات"])

SOURCE_LABELS = {
    "manual": "امتیاز دستی مدیر",
    "auto_daily_login": "ورود روزانه",
    "auto_timely_action": "اقدام به‌موقع",
    "auto_success": "تکمیل موفق پرونده",
}


@router.get("/leaderboard")
async def get_leaderboard(
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    agg_stmt = (
        select(
            User.id,
            User.display_name,
            User.job_title,
            User.department,
            User.avatar_color,
            func.avg(UserRating.score).label("avg_score"),
            func.count(UserRating.id).label("rating_count"),
        )
        .join(UserRating, UserRating.user_id == User.id)
        .where(User.is_deleted.is_(False), User.is_active.is_(True))
        .group_by(User.id, User.display_name, User.job_title, User.department, User.avatar_color)
        .order_by(func.avg(UserRating.score).desc(), func.count(UserRating.id).desc(), User.id.asc())
    )
    res = await db.execute(agg_stmt)
    rows = res.all()

    user_ids = [r.id for r in rows]
    details_map: dict[int, list[dict]] = {uid: [] for uid in user_ids}
    if user_ids:
        det_res = await db.execute(
            select(UserRating)
            .where(UserRating.user_id.in_(user_ids))
            .order_by(UserRating.created_at.desc(), UserRating.id.desc())
        )
        for ur in det_res.scalars().all():
            if len(details_map[ur.user_id]) < 20:
                details_map[ur.user_id].append(
                    {
                        "id": ur.id,
                        "score": ur.score,
                        "source": ur.source,
                        "source_label": SOURCE_LABELS.get(ur.source, ur.source),
                        # Never expose private task body/details in public leaderboard reasons
                        "reason": ur.reason,
                        "created_at_label": format_jalali_label(ur.created_at),
                        "editable": ur.source == "manual" and ctx.is_manager,
                    }
                )

    items = []
    for idx, r in enumerate(rows, start=1):
        exact_avg = float(r.avg_score or 0)
        items.append(
            {
                "rank": idx,
                "medal": "gold" if idx == 1 else ("silver" if idx == 2 else ("bronze" if idx == 3 else None)),
                "user_id": r.id,
                "display_name": r.display_name,
                "job_title": r.job_title,
                "department": r.department,
                "avatar_color": r.avatar_color,
                "avg_score": round(exact_avg, 2),
                "rating_count": int(r.rating_count),
                "details": details_map.get(r.id, []),
            }
        )
    return {"items": items}


@router.post("")
async def create_manual_rating(
    payload: RatingCreateRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    target = await db.get(User, payload.user_id)
    if not target or target.is_deleted or not target.is_active:
        raise HTTPException(status_code=404, detail="کاربر مقصد یافت نشد.")

    rating = UserRating(
        user_id=target.id,
        score=payload.score,
        source="manual",
        reason=payload.reason.strip(),
        awarded_by=ctx.user.id,
        award_date_tehran=tehran_today_date(),
        idempotency_key=f"manual:{uuid.uuid4().hex}",
    )
    db.add(rating)
    await db.flush()
    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="rating.manual_create",
        target_type="user_rating",
        target_id=str(rating.id),
        after_state={"user_id": target.id, "score": rating.score},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"id": rating.id, "score": rating.score}


@router.patch("/{rating_id}")
async def update_manual_rating(
    rating_id: int,
    payload: RatingUpdateRequest,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rating = await db.get(UserRating, rating_id)
    if not rating:
        raise HTTPException(status_code=404, detail="امتیاز یافت نشد.")
    if rating.source != "manual":
        raise HTTPException(status_code=403, detail="امتیاز خودکار قابل ویرایش نیست.")
    rating.score = payload.score
    rating.reason = payload.reason.strip()
    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="rating.manual_update",
        target_type="user_rating",
        target_id=str(rating.id),
        after_state={"score": rating.score},
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"id": rating.id, "score": rating.score}


@router.delete("/{rating_id}")
async def delete_manual_rating(
    rating_id: int,
    request: Request,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rating = await db.get(UserRating, rating_id)
    if not rating:
        raise HTTPException(status_code=404, detail="امتیاز یافت نشد.")
    if rating.source != "manual":
        raise HTTPException(status_code=403, detail="امتیاز خودکار قابل حذف نیست.")
    await db.delete(rating)
    await add_audit_log(
        db,
        actor_id=ctx.user.id,
        action="rating.manual_delete",
        target_type="user_rating",
        target_id=str(rating_id),
        ip_address=extract_client_ip(request),
        correlation_id=ctx.session.correlation_id,
    )
    await db.commit()
    return {"ok": True}
