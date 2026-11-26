from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import ChatMessage, ChatRead, Notification, User, WsPresence
from app.rbac import ROLE_MANAGER, AuthContext, get_current_auth, require_roles
from app.realtime import emit_outbox_event, notify_outbox_signal
from app.schemas import ChatReadMarkRequest, ChatSendRequest
from app.utils.jalali import format_jalali_label, utc_now

router = APIRouter(prefix="/api/v1/chat", tags=["چت سازمانی و اطلاع‌رسانی"])


@router.get("")
async def list_chat_messages(
    channel: str = Query("public", pattern="^(public|announcements)$"),
    before_id: Optional[int] = Query(None),
    limit: int = Query(40, ge=1, le=100),
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = (
        select(ChatMessage, User.display_name, User.job_title, User.avatar_color)
        .join(User, User.id == ChatMessage.sender_id)
        .where(ChatMessage.channel == channel)
    )
    if before_id is not None:
        stmt = stmt.where(ChatMessage.id < before_id)
    stmt = stmt.order_by(ChatMessage.id.desc()).limit(limit + 1)
    res = await db.execute(stmt)
    rows = res.all()
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]
    rows.reverse()

    msg_ids = [m.id for m, _, _, _ in rows]
    reads_count: dict[int, int] = {}
    my_reads: set[int] = set()
    readers_map: dict[int, list[dict]] = {}

    if msg_ids:
        cnt_res = await db.execute(
            select(ChatRead.message_id, func.count(ChatRead.id))
            .where(ChatRead.message_id.in_(msg_ids))
            .group_by(ChatRead.message_id)
        )
        reads_count = {mid: int(cnt) for mid, cnt in cnt_res.all()}

        my_res = await db.execute(
            select(ChatRead.message_id).where(ChatRead.message_id.in_(msg_ids), ChatRead.user_id == ctx.user.id)
        )
        my_reads = {mid for (mid,) in my_res.all()}

        # Only expose reader names/timestamps for own messages or manager (without over-exposing)
        if ctx.is_manager:
            rd_res = await db.execute(
                select(ChatRead.message_id, User.display_name, ChatRead.read_at)
                .join(User, User.id == ChatRead.user_id)
                .where(ChatRead.message_id.in_(msg_ids))
                .order_by(ChatRead.read_at.asc())
            )
            for mid, dname, rat in rd_res.all():
                readers_map.setdefault(mid, []).append(
                    {"display_name": dname, "read_at_label": format_jalali_label(rat)}
                )

    items = [
        {
            "id": m.id,
            "channel": m.channel,
            "sender_id": m.sender_id,
            "sender_name": sname,
            "sender_job_title": stitle,
            "sender_avatar_color": scolor,
            "body": m.body,
            "created_at": m.created_at.isoformat(),
            "created_at_label": format_jalali_label(m.created_at),
            "read_count": reads_count.get(m.id, 0),
            "read_by_me": m.id in my_reads,
            "readers": readers_map.get(m.id) if (ctx.is_manager or m.sender_id == ctx.user.id) else None,
        }
        for m, sname, stitle, scolor in rows
    ]

    # Unread counts per tab
    read_subq = select(ChatRead.message_id).where(ChatRead.user_id == ctx.user.id)
    unread_public = int(
        (
            await db.execute(
                select(func.count(ChatMessage.id)).where(
                    ChatMessage.channel == "public",
                    ChatMessage.sender_id != ctx.user.id,
                    ~ChatMessage.id.in_(read_subq),
                )
            )
        ).scalar()
        or 0
    )
    unread_announce = int(
        (
            await db.execute(
                select(func.count(ChatMessage.id)).where(
                    ChatMessage.channel == "announcements",
                    ChatMessage.sender_id != ctx.user.id,
                    ~ChatMessage.id.in_(read_subq),
                )
            )
        ).scalar()
        or 0
    )

    return {
        "items": items,
        "has_more": has_more,
        "next_before_id": items[0]["id"] if items and has_more else None,
        "unread_public": unread_public,
        "unread_announcements": unread_announce,
    }


async def _post_chat_message(
    db: AsyncSession,
    ctx: AuthContext,
    channel: str,
    payload: ChatSendRequest,
) -> dict:
    if payload.client_msg_id:
        ex_res = await db.execute(select(ChatMessage).where(ChatMessage.client_msg_id == payload.client_msg_id))
        ex = ex_res.scalar_one_or_none()
        if ex:
            return {"id": ex.id, "duplicate": True, "created_at_label": format_jalali_label(ex.created_at)}

    msg = ChatMessage(
        channel=channel,
        sender_id=ctx.user.id,
        body=payload.body.strip(),
        client_msg_id=payload.client_msg_id,
    )
    db.add(msg)
    await db.flush()

    outbox_ids: list[int] = []
    ev = await emit_outbox_event(
        db,
        event_type="chat.message",
        channel=f"chat:{channel}",
        payload={
            "id": msg.id,
            "channel": channel,
            "sender_id": ctx.user.id,
            "sender_name": ctx.user.display_name,
            "sender_job_title": ctx.user.job_title,
            "sender_avatar_color": ctx.user.avatar_color,
            "body": msg.body,
            "created_at": msg.created_at.isoformat(),
            "created_at_label": format_jalali_label(msg.created_at),
        },
    )
    outbox_ids.append(ev.id)

    if channel == "announcements":
        # Notify all active non-deleted users
        u_res = await db.execute(
            select(User.id).where(User.is_active.is_(True), User.is_deleted.is_(False), User.id != ctx.user.id)
        )
        for (uid,) in u_res.all():
            dedup = f"announce:{msg.id}:{uid}"
            ev_n = await emit_outbox_event(
                db,
                event_type="notification.announcement",
                channel=f"user:{uid}",
                payload={
                    "target_user_ids": [uid],
                    "title": f"اطلاعیهٔ تیمی از {ctx.user.display_name}",
                    "body": msg.body[:200],
                    "dedup_key": dedup,
                },
            )
            outbox_ids.append(ev_n.id)
            await db.execute(
                pg_insert(Notification)
                .values(
                    user_id=uid,
                    type="announcement",
                    title=f"اطلاعیهٔ تیمی از {ctx.user.display_name}"[:160],
                    body=msg.body[:500],
                    outbox_event_id=ev_n.id,
                    dedup_key=dedup,
                )
                .on_conflict_do_nothing()
            )

    await notify_outbox_signal(db, outbox_ids)
    await db.commit()
    return {
        "id": msg.id,
        "channel": channel,
        "sender_id": ctx.user.id,
        "sender_name": ctx.user.display_name,
        "sender_job_title": ctx.user.job_title,
        "sender_avatar_color": ctx.user.avatar_color,
        "body": msg.body,
        "created_at": msg.created_at.isoformat(),
        "created_at_label": format_jalali_label(msg.created_at),
        "duplicate": False,
    }


@router.post("")
async def send_public_chat(
    payload: ChatSendRequest,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _post_chat_message(db, ctx, "public", payload)


@router.post("/announce")
async def send_announcement(
    payload: ChatSendRequest,
    ctx: AuthContext = Depends(require_roles(ROLE_MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Note: display_access_level='supervisor' alone does NOT grant announcement rights; ROLE_MANAGER is strictly required.
    return await _post_chat_message(db, ctx, "announcements", payload)


@router.post("/reads")
async def mark_chat_reads(
    payload: ChatReadMarkRequest,
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = utc_now()
    # Only mark existing messages not already marked by this user
    msg_res = await db.execute(
        select(ChatMessage.id).where(ChatMessage.id.in_(payload.message_ids), ChatMessage.sender_id != ctx.user.id)
    )
    valid_ids = [mid for (mid,) in msg_res.all()]
    if valid_ids:
        values = [{"message_id": mid, "user_id": ctx.user.id, "read_at": now} for mid in valid_ids]
        await db.execute(
            pg_insert(ChatRead).values(values).on_conflict_do_nothing(index_elements=["message_id", "user_id"])
        )
        ev = await emit_outbox_event(
            db,
            event_type="chat.read_receipt",
            channel="chat",
            payload={"message_ids": valid_ids, "user_id": ctx.user.id, "read_at_label": format_jalali_label(now)},
        )
        await notify_outbox_signal(db, [ev.id])
        await db.commit()
    return {"marked_ids": valid_ids}


@router.get("/presence")
async def get_online_users(
    ctx: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    now = utc_now()
    stmt = (
        select(User.id, User.display_name, User.job_title, User.avatar_color)
        .join(WsPresence, WsPresence.user_id == User.id)
        .where(
            WsPresence.expires_at > now,
            User.is_active.is_(True),
            User.is_deleted.is_(False),
        )
        .distinct()
        .order_by(User.display_name.asc())
    )
    res = await db.execute(stmt)
    return {
        "online_users": [
            {"id": uid, "display_name": dname, "job_title": jtitle, "avatar_color": acolor}
            for uid, dname, jtitle, acolor in res.all()
        ]
    }
