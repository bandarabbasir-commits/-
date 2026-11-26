import asyncio
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.config import get_settings
import app.db as app_db
from app.models import OutboxEvent
from app.rbac import resolve_session_from_token
from app.realtime import hub
from app.routers import admin_ops, auth, chat, drafts, health, ratings, reports, tasks, users, visits
from app.routers.health import latency_metrics
from app.utils.jalali import utc_now
from app.worker import run_background_worker

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":%(message)s}',
)
logger = logging.getLogger("hb.api")

WS_MAX_MESSAGE_BYTES = 4096
WS_MAX_MSGS_PER_10S = 25


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.validate_production_safety()
    stop_event = asyncio.Event()
    worker_task = None
    if settings.app_env != "test":
        await hub.start_listener()
        worker_task = asyncio.create_task(run_background_worker(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        if worker_task:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
        if settings.app_env != "test":
            await hub.stop_listener()


app = FastAPI(
    title="هرمزگان بیدار — نسخهٔ ۲",
    description="API نسخه‌دار مدیریت و پیگیری درخواست‌های مردمی دفتر",
    version="2.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def security_and_observability_middleware(request: Request, call_next):
    req_id = request.headers.get("x-request-id") or secrets.token_hex(8)
    start = time.perf_counter()
    response = await call_next(request)
    dur_ms = (time.perf_counter() - start) * 1000.0

    latency_metrics.total_requests += 1
    latency_metrics.total_duration_ms += dur_ms
    if dur_ms > latency_metrics.max_duration_ms:
        latency_metrics.max_duration_ms = dur_ms

    response.headers["X-Request-ID"] = req_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' ws: wss:; object-src 'none'; base-uri 'self';"
    )

    # Structured log without PII (no body, no phone, no session token)
    logger.info(
        json.dumps(
            {
                "req_id": req_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(dur_ms, 2),
            }
        )
    )
    return response


@app.exception_handler(RequestValidationError)
async def persian_validation_exception_handler(_request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = [str(x) for x in err.get("loc", []) if x != "body"]
        field = ".".join(loc) if loc else "ورودی"
        msg = err.get("msg", "مقدار نامعتبر است.")
        # Translate common Pydantic messages to Persian
        if "String should have at least" in msg:
            msg = "طول متن واردشده کمتر از حد مجاز است."
        elif "Field required" in msg:
            msg = "تکمیل این فیلد الزامی است."
        elif "Input should be" in msg:
            msg = "مقدار انتخاب‌شده معتبر نیست."
        errors.append({"field": field, "message": msg})
    return JSONResponse(
        status_code=422,
        content={"detail": errors[0]["message"] if errors else "اطلاعات ارسالی معتبر نیست.", "errors": errors},
    )


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(drafts.router)
app.include_router(visits.router)
app.include_router(chat.router)
app.include_router(users.router)
app.include_router(ratings.router)
app.include_router(reports.router)
app.include_router(admin_ops.router)


@app.websocket("/api/v1/ws")
async def websocket_endpoint(websocket: WebSocket):
    settings = get_settings()
    origin = (websocket.headers.get("origin") or "").rstrip("/")
    host = websocket.headers.get("host", "")
    peer_ip = websocket.client.host if websocket.client else ""
    if peer_ip in settings.trusted_proxies_list:
        fwd_host = websocket.headers.get("x-forwarded-host", "")
        if fwd_host:
            host = fwd_host.split(",")[0].strip()
    origin_ok = (not origin and settings.app_env == "test") or (origin in settings.allowed_origins_list) or (
        origin.endswith(f"://{host}") if host else False
    )
    if not origin_ok:
        await websocket.close(code=4003, reason="origin_denied")
        return

    raw_token = websocket.cookies.get("hb_session", "")
    async with app_db.AsyncSessionLocal() as db:
        ctx = await resolve_session_from_token(db, raw_token)
        await db.commit()

    if ctx is None:
        await websocket.close(code=4001, reason="unauthorized")
        return

    await websocket.accept()
    connection_id = secrets.token_hex(12)
    await hub.register(websocket, ctx.user.id, ctx.session.id, ctx.roles, connection_id)

    try:
        # Optional delta sync on initial connect or reconnect (?since_event_id=...)
        since_str = websocket.query_params.get("since_event_id")
        if since_str and since_str.isdigit():
            since_id = int(since_str)
            async with app_db.AsyncSessionLocal() as db:
                ev_res = await db.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.id > since_id, OutboxEvent.event_type != "session.revoked")
                    .order_by(OutboxEvent.id.asc())
                    .limit(100)
                )
                for ev in ev_res.scalars().all():
                    target_users = ev.payload.get("target_user_ids")
                    req_role = ev.payload.get("required_role")
                    if target_users is not None and ctx.user.id not in target_users:
                        continue
                    if req_role and req_role not in ctx.roles:
                        continue
                    await websocket.send_json(
                        {
                            "v": 1,
                            "event_id": ev.id,
                            "type": ev.event_type,
                            "channel": ev.channel,
                            "created_at": ev.created_at.isoformat(),
                            "payload": ev.payload,
                        }
                    )

        await websocket.send_json({"v": 1, "type": "ws.connected", "user_id": ctx.user.id, "connection_id": connection_id})

        msg_times: list[float] = []
        while True:
            raw_text = await websocket.receive_text()
            if len(raw_text.encode("utf-8")) > WS_MAX_MESSAGE_BYTES:
                await websocket.send_json({"v": 1, "type": "ws.error", "message": "حجم پیام بیش از حد مجاز است."})
                continue

            now_mono = time.monotonic()
            msg_times = [t for t in msg_times if now_mono - t < 10.0]
            if len(msg_times) >= WS_MAX_MSGS_PER_10S:
                await websocket.send_json({"v": 1, "type": "ws.error", "message": "نرخ ارسال پیام بیش از حد مجاز است."})
                continue
            msg_times.append(now_mono)

            try:
                msg = json.loads(raw_text)
            except Exception:
                continue

            if msg.get("type") == "ping":
                # Verify session hasn't been revoked before refreshing presence
                async with app_db.AsyncSessionLocal() as db:
                    still_valid = await resolve_session_from_token(db, raw_token)
                    await db.commit()
                if still_valid is None:
                    await websocket.send_json({"v": 1, "type": "session.revoked", "reason": "revoked"})
                    await websocket.close(code=4001, reason="session_revoked")
                    break
                await hub.touch_presence(ctx.user.id, ctx.session.id, connection_id)
                await websocket.send_json({"v": 1, "type": "pong", "ts": utc_now().isoformat()})
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unregister(ctx.user.id, connection_id)
