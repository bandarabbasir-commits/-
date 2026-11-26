import asyncio
import json
import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any, Optional
import asyncpg
from fastapi import WebSocket
from sqlalchemy import delete, select

from app.config import get_settings
import app.db as app_db
from app.models import OutboxEvent, WsPresence
from app.utils.jalali import utc_now

logger = logging.getLogger("hb.realtime")

OUTBOX_NOTIFY_CHANNEL = "hb_outbox_events"


async def emit_outbox_event(
    db,
    event_type: str,
    channel: str,
    payload: dict[str, Any],
) -> OutboxEvent:
    """
    Must be called INSIDE the business transaction so business mutation + TaskEvent + OutboxEvent commit atomically.
    Caller or post-commit hook triggers pg_notify.
    """
    ev = OutboxEvent(
        event_type=event_type,
        channel=channel,
        payload=payload,
    )
    db.add(ev)
    await db.flush()
    return ev


async def notify_outbox_signal(db, event_ids: list[int]) -> None:
    """Send PostgreSQL NOTIFY signal AFTER commit (or right after flush before commit so PG delivers on commit)."""
    if not event_ids:
        return
    payload = json.dumps({"event_ids": event_ids})
    # PostgreSQL delivers NOTIFY only when the current transaction commits!
    await db.execute(
        select_notify_expr(OUTBOX_NOTIFY_CHANNEL, payload)
    )


def select_notify_expr(channel: str, payload: str):
    from sqlalchemy import func
    return select_pg_notify(channel, payload)


def select_pg_notify(channel: str, payload: str):
    from sqlalchemy import func, select
    return select(func.pg_notify(channel, payload))


class RealtimeHub:
    """
    Process-local WebSocket connection registry, coordinated across workers via PostgreSQL Outbox + LISTEN/NOTIFY
    and DB-backed ws_presence table.
    """

    def __init__(self) -> None:
        self.connections_by_user: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._listener_conn: Optional[asyncpg.Connection] = None
        self._listener_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def register(
        self,
        websocket: WebSocket,
        user_id: int,
        session_id: str,
        roles: set[str],
        connection_id: str,
    ) -> None:
        self.connections_by_user[user_id][connection_id] = {
            "ws": websocket,
            "session_id": session_id,
            "roles": set(roles),
            "msg_timestamps": [],
        }
        await self.touch_presence(user_id, session_id, connection_id)

    async def unregister(self, user_id: int, connection_id: str) -> None:
        user_conns = self.connections_by_user.get(user_id)
        if user_conns and connection_id in user_conns:
            del user_conns[connection_id]
            if not user_conns:
                del self.connections_by_user[user_id]
        try:
            async with app_db.AsyncSessionLocal() as db:
                await db.execute(delete(WsPresence).where(WsPresence.connection_id == connection_id))
                await db.commit()
        except Exception:
            logger.exception("presence_cleanup_failed")

    async def touch_presence(self, user_id: int, session_id: str, connection_id: str) -> None:
        settings = get_settings()
        now = utc_now()
        exp = now + timedelta(seconds=settings.presence_ttl_seconds)
        async with app_db.AsyncSessionLocal() as db:
            stmt = select(WsPresence).where(WsPresence.connection_id == connection_id)
            res = await db.execute(stmt)
            row = res.scalar_one_or_none()
            if row is None:
                db.add(
                    WsPresence(
                        user_id=user_id,
                        session_id=session_id,
                        connection_id=connection_id,
                        last_heartbeat_at=now,
                        expires_at=exp,
                    )
                )
            else:
                row.last_heartbeat_at = now
                row.expires_at = exp
            await db.commit()

    async def disconnect_sessions(self, session_ids: list[str], reason: str = "session_revoked") -> None:
        if not session_ids:
            return
        targets: list[tuple[int, str, WebSocket]] = []
        target_set = set(session_ids)
        for uid, conns in list(self.connections_by_user.items()):
            for cid, info in list(conns.items()):
                if info["session_id"] in target_set:
                    targets.append((uid, cid, info["ws"]))
        for uid, cid, ws in targets:
            try:
                await ws.send_json({"v": 1, "type": "session.revoked", "reason": reason})
                await ws.close(code=4001, reason=reason)
            except Exception:
                pass
            await self.unregister(uid, cid)

    async def start_listener(self) -> None:
        self._stop_event.clear()
        self._listener_task = asyncio.create_task(self._listen_loop())

    async def stop_listener(self) -> None:
        self._stop_event.set()
        if self._listener_conn is not None:
            try:
                await self._listener_conn.close()
            except Exception:
                pass
        if self._listener_task is not None:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

    async def _listen_loop(self) -> None:
        settings = get_settings()
        dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        while not self._stop_event.is_set():
            try:
                conn = await asyncpg.connect(dsn)
                self._listener_conn = conn

                def _on_notify(_conn, _pid, _channel, payload_str: str) -> None:
                    asyncio.create_task(self._handle_notify(payload_str))

                await conn.add_listener(OUTBOX_NOTIFY_CHANNEL, _on_notify)
                # Catch up any unpublished events
                await self._flush_unpublished_outbox()
                while not self._stop_event.is_set():
                    await asyncio.sleep(5)
                    # Periodic lightweight safety sweep in case a NOTIFY was missed during reconnect
                    await self._flush_unpublished_outbox()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("ws_listener_reconnecting")
                await asyncio.sleep(2)
            finally:
                if self._listener_conn is not None:
                    try:
                        await self._listener_conn.close()
                    except Exception:
                        pass
                    self._listener_conn = None

    async def _handle_notify(self, payload_str: str) -> None:
        try:
            data = json.loads(payload_str)
            event_ids = data.get("event_ids", [])
            if event_ids:
                await self._deliver_outbox_ids(event_ids)
        except Exception:
            logger.exception("notify_handle_error")

    async def _flush_unpublished_outbox(self) -> None:
        async with app_db.AsyncSessionLocal() as db:
            stmt = (
                select(OutboxEvent.id)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.id.asc())
                .limit(100)
            )
            res = await db.execute(stmt)
            ids = list(res.scalars().all())
        if ids:
            await self._deliver_outbox_ids(ids)

    async def _deliver_outbox_ids(self, event_ids: list[int]) -> None:
        async with app_db.AsyncSessionLocal() as db:
            stmt = select(OutboxEvent).where(OutboxEvent.id.in_(event_ids)).order_by(OutboxEvent.id.asc())
            res = await db.execute(stmt)
            events = list(res.scalars().all())
            now = utc_now()
            for ev in events:
                await self._dispatch_event_to_local_clients(ev)
                if ev.published_at is None:
                    ev.published_at = now
            await db.commit()

    async def _dispatch_event_to_local_clients(self, ev: OutboxEvent) -> None:
        if ev.event_type == "session.revoked":
            sids = ev.payload.get("session_ids", [])
            await self.disconnect_sessions(sids, ev.payload.get("reason", "revoked"))
            return

        envelope = {
            "v": 1,
            "event_id": ev.id,
            "type": ev.event_type,
            "channel": ev.channel,
            "created_at": ev.created_at.isoformat() if ev.created_at else utc_now().isoformat(),
            "payload": ev.payload,
        }

        target_users = ev.payload.get("target_user_ids")
        required_role = ev.payload.get("required_role")

        for uid, conns in list(self.connections_by_user.items()):
            if target_users is not None and uid not in target_users:
                continue
            for cid, info in list(conns.items()):
                if required_role and required_role not in info["roles"]:
                    continue
                ws: WebSocket = info["ws"]
                try:
                    await ws.send_json(envelope)
                except Exception:
                    pass


hub = RealtimeHub()
