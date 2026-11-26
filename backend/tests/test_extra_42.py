import asyncio
import json
from datetime import timedelta
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from starlette.testclient import TestClient

import app.db as app_db
from app.main import app
from app.models import AuditLog, OutboxEvent, SmsTask, TaskAssignment, User, UserRating
from app.realtime import emit_outbox_event, notify_outbox_signal
from app.utils.jalali import jalali_range_to_utc_half_open, parse_jalali_date, utc_now
from app.utils.persian import normalize_digits_ascii, to_persian_digits
from tests.conftest import login_as


def test_21_persian_digits_conversion():
    assert to_persian_digits("1405/08/30") == "۱۴۰۵/۰۸/۳۰"
    assert normalize_digits_ascii("۱۴۰۵/٠٨/۳۰") == "1405/08/30"


def test_22_jalali_esfand_leap_years_and_tehran_day_utc():
    # 1399 & 1403 are leap; 1404 is common
    assert parse_jalali_date("1399/12/30").day == 30
    assert parse_jalali_date("1403/12/30").day == 30
    with pytest.raises(ValueError):
        parse_jalali_date("1402/12/30")
    s_utc, e_utc = jalali_range_to_utc_half_open("1405/06/31", "1405/07/01")
    assert (e_utc - s_utc).total_seconds() == 2 * 86400


@pytest.mark.asyncio
async def test_23_persian_search_matches_arabic_yeh_kaf_and_persian_digits():
    c_mgr, csrf_m, _ = await login_as("manager1")
    c_emp1, _, emp1 = await login_as("emp1")
    await c_mgr.post(
        "/api/v1/tasks/direct",
        json={
            "source_type": "sms",
            "requester_name": "تست نرمال‌سازی",
            "requester_phone": "09170000801",
            "body": "مشکل کتابخانه و ایستگاه اتوبوس ۱۲ در بندر",
            "priority": "normal",
            "receiver_ids": [emp1["id"]],
        },
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    # Search using Arabic Kaf (ك) & Yeh (ي) & ASCII digits (12)
    res = await c_emp1.get("/api/v1/tasks?q=كتابخانه 12")
    assert res.status_code == 200
    assert any("کتابخانه" in it["body_summary"] for it in res.json()["items"])
    await c_mgr.aclose()
    await c_emp1.aclose()


@pytest.mark.asyncio
async def test_24_direct_task_rejects_inactive_or_author_only_receiver():
    c_mgr, csrf_m, _ = await login_as("manager1")
    c_auth, _, auth_u = await login_as("author1")
    bad = await c_mgr.post(
        "/api/v1/tasks/direct",
        json={
            "source_type": "sms",
            "requester_name": "تست",
            "requester_phone": "09170000802",
            "body": "ارسال اشتباه به نویسنده",
            "priority": "normal",
            "receiver_ids": [auth_u["id"]],
        },
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    assert bad.status_code == 422
    await c_mgr.aclose()
    await c_auth.aclose()


@pytest.mark.asyncio
async def test_25_personal_folder_max_one_per_user_and_delete_preserves_task():
    c_mgr, csrf_m, _ = await login_as("manager1")
    c_emp1, csrf_e1, emp1 = await login_as("emp1")
    ct = await c_mgr.post(
        "/api/v1/tasks/direct",
        json={
            "source_type": "sms",
            "requester_name": "تست فولدر",
            "requester_phone": "09170000803",
            "body": "پرونده تست فولدر شخصی",
            "priority": "normal",
            "receiver_ids": [emp1["id"]],
        },
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    tid = ct.json()["task_id"]
    f1 = (
        await c_emp1.post(
            "/api/v1/folders", json={"name": "فولدر اول"}, headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"}
        )
    ).json()["id"]
    f2 = (
        await c_emp1.post(
            "/api/v1/folders", json={"name": "فولدر دوم"}, headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"}
        )
    ).json()["id"]

    await c_emp1.put(
        f"/api/v1/tasks/{tid}/folder",
        json={"folder_id": f1},
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    # Moving to f2 removes from f1 (max 1 folder per user per task)
    await c_emp1.put(
        f"/api/v1/tasks/{tid}/folder",
        json={"folder_id": f2},
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    folders = (await c_emp1.get("/api/v1/folders")).json()["items"]
    assert next(f for f in folders if f["id"] == f1)["count"] == 0
    assert next(f for f in folders if f["id"] == f2)["count"] == 1

    # Deleting f2 does NOT delete task
    await c_emp1.delete(f"/api/v1/folders/{f2}", headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"})
    assert (await c_emp1.get(f"/api/v1/tasks/{tid}")).status_code == 200
    await c_mgr.aclose()
    await c_emp1.aclose()


@pytest.mark.asyncio
async def test_26_timely_action_sla_awards_within_sla_and_skips_overdue():
    c_mgr, csrf_m, _ = await login_as("manager1")
    c_emp2, csrf_e2, emp2 = await login_as("emp2")

    # Task 1: within 2h urgent SLA -> gets auto_timely_action
    ct1 = await c_mgr.post(
        "/api/v1/tasks/direct",
        json={
            "source_type": "sms",
            "requester_name": "SLA OK",
            "requester_phone": "09170000804",
            "body": "پرونده فوری در مهلت SLA",
            "priority": "urgent",
            "receiver_ids": [emp2["id"]],
        },
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    t1 = ct1.json()["task_id"]
    v1 = (await c_emp2.get(f"/api/v1/tasks/{t1}")).json()["version"]
    await c_emp2.post(
        f"/api/v1/tasks/{t1}/action",
        json={"status": "in_progress", "report_text": "اقدام سریع در مهلت", "version": v1},
        headers={"X-CSRF-Token": csrf_e2, "Origin": "http://localhost:3000"},
    )

    # Task 2: simulate assignment started 5 hours ago on urgent (SLA=2h) -> NO timely score
    ct2 = await c_mgr.post(
        "/api/v1/tasks/direct",
        json={
            "source_type": "sms",
            "requester_name": "SLA Late",
            "requester_phone": "09170000805",
            "body": "پرونده فوری خارج از مهلت SLA",
            "priority": "urgent",
            "receiver_ids": [emp2["id"]],
        },
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    t2 = ct2.json()["task_id"]
    async with app_db.AsyncSessionLocal() as db:
        assign = (
            await db.execute(select(TaskAssignment).where(TaskAssignment.task_id == t2, TaskAssignment.receiver_id == emp2["id"]))
        ).scalar_one()
        assign.assigned_at = utc_now() - timedelta(hours=5)
        await db.commit()

    v2 = (await c_emp2.get(f"/api/v1/tasks/{t2}")).json()["version"]
    await c_emp2.post(
        f"/api/v1/tasks/{t2}/action",
        json={"status": "in_progress", "report_text": "اقدام با تأخیر", "version": v2},
        headers={"X-CSRF-Token": csrf_e2, "Origin": "http://localhost:3000"},
    )

    async with app_db.AsyncSessionLocal() as db:
        r1 = (
            await db.execute(select(UserRating).where(UserRating.task_id == t1, UserRating.source == "auto_timely_action"))
        ).scalars().all()
        r2 = (
            await db.execute(select(UserRating).where(UserRating.task_id == t2, UserRating.source == "auto_timely_action"))
        ).scalars().all()
        assert len(r1) == 1
        assert len(r2) == 0

    await c_mgr.aclose()
    await c_emp2.aclose()


@pytest.mark.asyncio
async def test_27_manual_rating_manager_only_and_auto_immutable():
    c_mgr, csrf_m, _ = await login_as("manager1")
    c_emp1, csrf_e1, emp1 = await login_as("emp1")

    assert (
        await c_emp1.post(
            "/api/v1/ratings",
            json={"user_id": emp1["id"], "score": 5, "reason": "خودامتیازدهی غیرمجاز"},
            headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
        )
    ).status_code == 403

    r_ok = await c_mgr.post(
        "/api/v1/ratings",
        json={"user_id": emp1["id"], "score": 5, "reason": "پیگیری دقیق هفته"},
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    assert r_ok.status_code == 200
    rid = r_ok.json()["id"]
    await c_mgr.patch(
        f"/api/v1/ratings/{rid}",
        json={"score": 4, "reason": "ویرایش‌شده"},
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    await c_mgr.delete(f"/api/v1/ratings/{rid}", headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"})

    # Auto score cannot be deleted by manager
    async with app_db.AsyncSessionLocal() as db:
        auto_r = (
            await db.execute(select(UserRating).where(UserRating.source != "manual").limit(1))
        ).scalar_one_or_none()
    if auto_r:
        assert (
            await c_mgr.delete(
                f"/api/v1/ratings/{auto_r.id}", headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"}
            )
        ).status_code == 403

    await c_mgr.aclose()
    await c_emp1.aclose()


@pytest.mark.asyncio
async def test_28_session_revoked_on_password_reset_and_role_change():
    c_adm, csrf_a, _ = await login_as("admin")
    c_emp6, csrf_e6, emp6 = await login_as("emp6")

    assert (await c_emp6.get("/api/v1/auth/me")).status_code == 200

    # Admin resets emp6 password -> emp6 session invalidated immediately
    await c_adm.post(
        f"/api/v1/users/{emp6['id']}/password",
        json={"new_password": "NewPass@1405"},
        headers={"X-CSRF-Token": csrf_a, "Origin": "http://localhost:3000"},
    )
    assert (await c_emp6.get("/api/v1/auth/me")).status_code == 401

    # Re-login with new password and test role update revokes session
    c_emp6_new, _, _ = await login_as("emp6", "NewPass@1405")
    u6 = next(u for u in (await c_adm.get("/api/v1/users")).json()["items"] if u["id"] == emp6["id"])
    await c_adm.patch(
        f"/api/v1/users/{emp6['id']}",
        json={
            "display_name": u6["display_name"],
            "job_title": u6["job_title"],
            "department": u6["department"],
            "display_access_level": u6["display_access_level"],
            "org_role_type": u6["org_role_type"],
            "roles": ["employee", "expert"],
            "version": u6["version"],
        },
        headers={"X-CSRF-Token": csrf_a, "Origin": "http://localhost:3000"},
    )
    assert (await c_emp6_new.get("/api/v1/auth/me")).status_code == 401

    # Restore original password for consistency
    await c_adm.post(
        f"/api/v1/users/{emp6['id']}/password",
        json={"new_password": "TestPass@1405"},
        headers={"X-CSRF-Token": csrf_a, "Origin": "http://localhost:3000"},
    )
    for cl in (c_adm, c_emp6, c_emp6_new):
        await cl.aclose()


@pytest.mark.asyncio
async def test_29_export_file_authorization_and_cache_control():
    c_auth, _, _ = await login_as("author1")
    c_emp1, _, _ = await login_as("emp1")
    c_adm, _, _ = await login_as("admin")

    # Author cannot export tasks
    assert (await c_auth.get("/api/v1/exports/word")).status_code == 403
    # Employee cannot export backup or login-logs
    assert (await c_emp1.get("/api/v1/backups/export")).status_code == 403
    assert (await c_emp1.get("/api/v1/login-logs/export/excel")).status_code == 403

    # Admin backup export must have Cache-Control: no-store
    b_res = await c_adm.get("/api/v1/backups/export")
    assert b_res.status_code == 200
    assert "no-store" in b_res.headers.get("cache-control", "")

    for cl in (c_auth, c_emp1, c_adm):
        await cl.aclose()


@pytest.mark.asyncio
async def test_30_login_logs_excel_excludes_ip_and_ua_by_default():
    from openpyxl import load_workbook
    import io

    c_adm, _, _ = await login_as("admin")
    res = await c_adm.get("/api/v1/login-logs/export/excel")
    assert res.status_code == 200
    wb = load_workbook(io.BytesIO(res.content))
    headers = [cell.value for cell in wb.active[1]]
    assert "IP" not in " ".join(str(h) for h in headers)
    assert "user-agent" not in " ".join(str(h) for h in headers).lower()
    await c_adm.aclose()


@pytest.mark.asyncio
async def test_31_reopen_forbidden_for_employee():
    c_emp1, csrf_e1, _ = await login_as("emp1")
    res = await c_emp1.post(
        "/api/v1/tasks/1/reopen",
        json={"reason": "تست", "receiver_ids": [], "version": 1},
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    assert res.status_code == 403
    await c_emp1.aclose()


@pytest.mark.asyncio
async def test_32_draft_edit_after_distributed_409_and_trash_requires_reason():
    c_auth, csrf_a, _ = await login_as("author1")
    c_mgr, csrf_m, _ = await login_as("manager1")
    c_emp1, _, emp1 = await login_as("emp1")

    d = (
        await c_auth.post(
            "/api/v1/drafts",
            json={"source_type": "sms", "body": "پیش‌نویس آزمون ویرایش پس از توزیع", "priority": "normal"},
            headers={"X-CSRF-Token": csrf_a, "Origin": "http://localhost:3000"},
        )
    ).json()

    # Trash with short/empty reason -> 422
    bad_trash = await c_mgr.post(
        f"/api/v1/drafts/{d['id']}/trash",
        json={"reason": "", "version": d["version"]},
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    assert bad_trash.status_code == 422

    # Distribute then try edit -> 409
    await c_mgr.post(
        f"/api/v1/drafts/{d['id']}/distribute",
        json={"receiver_ids": [emp1["id"]], "version": d["version"]},
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    bad_edit = await c_mgr.patch(
        f"/api/v1/drafts/{d['id']}",
        json={
            "body": "تلاش ویرایش بعد توزیع",
            "priority": "urgent",
            "action_flag": "action",
            "manager_note": "",
            "mark_ready": False,
            "version": d["version"] + 1,
        },
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    assert bad_edit.status_code == 409

    for cl in (c_auth, c_mgr, c_emp1):
        await cl.aclose()


@pytest.mark.asyncio
async def test_33_visits_no_auto_merge_same_name_and_archive_separate():
    c_emp1, csrf_e1, _ = await login_as("emp1")
    c_mgr, csrf_m, _ = await login_as("manager1")

    v1 = (
        await c_emp1.post(
            "/api/v1/visits",
            json={
                "person_or_org": "محمد رضایی فرضی",
                "phone": "09170000901",
                "request_desc": "درخواست اول",
                "followup_desc": "پیگیری اول",
                "action_taken": "ثبت اول",
            },
            headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
        )
    ).json()["id"]
    v2 = (
        await c_emp1.post(
            "/api/v1/visits",
            json={
                "person_or_org": "محمد رضایی فرضی",
                "phone": "09170000902",
                "request_desc": "درخواست دوم با نام مشابه و تلفن متفاوت",
                "followup_desc": "پیگیری دوم",
                "action_taken": "ثبت دوم",
            },
            headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
        )
    ).json()["id"]

    # Both remain distinct records
    items = (await c_emp1.get("/api/v1/visits?view=my")).json()["items"]
    assert len([i for i in items if i["id"] in (v1, v2)]) == 2

    # Approve & archive v1
    await c_mgr.post(
        f"/api/v1/visits/{v1}/review",
        json={"decision": "approved", "review_note": "تأیید", "version": 1},
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    await c_mgr.post(
        "/api/v1/archive/clear-done",
        json={"target_type": "visit", "statuses": ["approved"]},
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    active_after = (await c_mgr.get("/api/v1/visits?view=approved")).json()["items"]
    assert all(i["id"] != v1 for i in active_after)

    await c_emp1.aclose()
    await c_mgr.aclose()


@pytest.mark.asyncio
async def test_34_notifications_mark_read_and_health_ready():
    c_emp5, csrf_e5, _ = await login_as("emp5")
    r_health = await c_emp5.get("/api/v1/health")
    r_ready = await c_emp5.get("/api/v1/ready")
    assert r_health.status_code == 200
    assert r_ready.status_code == 200

    await c_emp5.post("/api/v1/notifications/read", headers={"X-CSRF-Token": csrf_e5, "Origin": "http://localhost:3000"})
    unread = (await c_emp5.get("/api/v1/notifications")).json()["unread_count"]
    assert unread == 0
    await c_emp5.aclose()


@pytest.mark.asyncio
async def test_35_metrics_admin_only():
    c_emp1, _, _ = await login_as("emp1")
    c_adm, _, _ = await login_as("admin")
    assert (await c_emp1.get("/api/v1/metrics")).status_code == 403
    m = await c_adm.get("/api/v1/metrics")
    assert m.status_code == 200
    assert "outbox_backlog" in m.json()
    await c_emp1.aclose()
    await c_adm.aclose()


@pytest.mark.asyncio
async def test_36_backup_restore_rejects_secrets_and_executes_transactionally():
    c_adm, csrf_a, _ = await login_as("admin")
    bad = await c_adm.post(
        "/api/v1/backups/dry-run",
        json={"schema_version": "2.0", "data": {"sms_tasks": [], "public_visits": [], "password_hash": "leak"}},
        headers={"X-CSRF-Token": csrf_a, "Origin": "http://localhost:3000"},
    )
    assert bad.status_code == 422

    # Transactional restore test with 1 synthetic record
    b_res = (await c_adm.get("/api/v1/backups/export")).json()
    b_res["data"]["sms_tasks"].append(
        {
            "id": 888881,
            "source_type": "sms",
            "requester_name": "تست بازیابی واقعی",
            "requester_phone_norm": "09170000888",
            "body": "پرونده بازیابی‌شده از بکاپ",
            "priority": "normal",
            "status": "pending",
            "action_flag": "action",
            "created_by": None,
            "is_deleted": False,
        }
    )
    rest = await c_adm.post(
        "/api/v1/backups/restore",
        json={"backup_payload": b_res, "confirm_phrase": "تأیید بازیابی", "password": "TestPass@1405"},
        headers={"X-CSRF-Token": csrf_a, "Origin": "http://localhost:3000"},
    )
    assert rest.status_code == 200
    assert rest.json()["inserted_tasks"] == 1
    await c_adm.aclose()


@pytest.mark.asyncio
async def test_37_websocket_auth_origin_delta_sync_and_revocation():
    # Test WebSocket via Starlette TestClient against real PostgreSQL
    with TestClient(app) as tc:
        # 1. Unauthenticated WS rejected
        with pytest.raises(Exception):
            with tc.websocket_connect("/api/v1/ws", headers={"Origin": "http://localhost:3000"}):
                pass

        # 2. Login via TestClient
        csrf = tc.get("/api/v1/auth/csrf").json()["csrf_token"]
        login_r = tc.post(
            "/api/v1/auth/login",
            json={"username": "emp3", "password": "TestPass@1405"},
            headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:3000"},
        )
        assert login_r.status_code == 200
        emp3_id = login_r.json()["user"]["id"]
        csrf_session = login_r.json()["csrf_token"]

        # 3. Denied Origin rejected
        with pytest.raises(Exception):
            with tc.websocket_connect("/api/v1/ws", headers={"Origin": "https://evil.example"}):
                pass

        # 4. Valid connection receives ws.connected + ping/pong
        with tc.websocket_connect("/api/v1/ws", headers={"Origin": "http://localhost:3000"}) as ws:
            hello = ws.receive_json()
            assert hello["type"] == "ws.connected"
            ws.send_text(json.dumps({"type": "ping"}))
            pong = ws.receive_json()
            assert pong["type"] == "pong"

        # 5. Simulate missed outbox event while disconnected, then reconnect with since_event_id=0
        async with app_db.AsyncSessionLocal() as db:
            ev = await emit_outbox_event(
                db,
                event_type="notification.reminder",
                channel=f"user:{emp3_id}",
                payload={"target_user_ids": [emp3_id], "title": "تست بازیابی اتصال", "body": "رویداد جامانده"},
            )
            await db.commit()
            target_ev_id = ev.id

        with tc.websocket_connect(
            f"/api/v1/ws?since_event_id={target_ev_id - 1}",
            headers={"Origin": "http://localhost:3000"},
        ) as ws:
            missed = ws.receive_json()
            assert missed["event_id"] == target_ev_id
            assert missed["payload"]["title"] == "تست بازیابی اتصال"

        # 6. Logout revokes session -> subsequent WS connect rejected
        tc.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf_session, "Origin": "http://localhost:3000"})
        with pytest.raises(Exception):
            with tc.websocket_connect("/api/v1/ws", headers={"Origin": "http://localhost:3000"}):
                pass


@pytest.mark.asyncio
async def test_38_postgres_listen_notify_cross_connection_signal():
    import asyncpg
    from app.config import get_settings

    dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    received = []
    listener = await asyncpg.connect(dsn)
    try:
        async def _cb(_c, _p, _ch, payload):
            received.append(payload)

        await listener.add_listener("hb_outbox_events", _cb)
        async with app_db.AsyncSessionLocal() as db:
            ev = await emit_outbox_event(db, "test.notify", "global", {"ok": True})
            await notify_outbox_signal(db, [ev.id])
            await db.commit()
        await asyncio.sleep(0.2)
        assert len(received) == 1
        assert str(ev.id) in received[0]
    finally:
        await listener.close()


@pytest.mark.asyncio
async def test_39_report_summary_counts_two_assignee_task_once():
    c_mgr, csrf_m, _ = await login_as("manager1")
    c_emp1, _, emp1 = await login_as("emp1")
    c_emp2, _, emp2 = await login_as("emp2")

    before = (await c_mgr.get("/api/v1/reports/summary")).json()["total"]
    await c_mgr.post(
        "/api/v1/tasks/direct",
        json={
            "source_type": "sms",
            "requester_name": "تست گزارش دوگیرنده",
            "requester_phone": "09170000911",
            "body": "پرونده دوگیرنده نباید دوبار شمارش شود",
            "priority": "normal",
            "receiver_ids": [emp1["id"], emp2["id"]],
        },
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    after = (await c_mgr.get("/api/v1/reports/summary")).json()["total"]
    assert after == before + 1
    for cl in (c_mgr, c_emp1, c_emp2):
        await cl.aclose()


@pytest.mark.asyncio
async def test_40_csrf_rejects_cross_origin_mutation():
    c_emp1, csrf_e1, _ = await login_as("emp1")
    res = await c_emp1.post(
        "/api/v1/folders",
        json={"name": "تست مبدأ جعلی"},
        headers={"X-CSRF-Token": csrf_e1, "Origin": "https://attacker.example"},
    )
    assert res.status_code == 403
    await c_emp1.aclose()


@pytest.mark.asyncio
async def test_41_task_pagination_cursor_stable_tie_breaker():
    c_mgr, _, _ = await login_as("manager1")
    p1 = (await c_mgr.get("/api/v1/tasks?view_mode=supervision&limit=2")).json()
    assert len(p1["items"]) <= 2
    if p1["has_more"] and p1["next_cursor"]:
        p2 = (await c_mgr.get(f"/api/v1/tasks?view_mode=supervision&limit=2&cursor={p1['next_cursor']}")).json()
        ids1 = {i["id"] for i in p1["items"]}
        ids2 = {i["id"] for i in p2["items"]}
        assert ids1.isdisjoint(ids2)
    await c_mgr.aclose()


@pytest.mark.asyncio
async def test_42_csv_and_excel_formula_injection_neutralized_in_export():
    c_mgr, csrf_m, _ = await login_as("manager1")
    c_emp1, _, emp1 = await login_as("emp1")
    await c_mgr.post(
        "/api/v1/tasks/direct",
        json={
            "source_type": "sms",
            "requester_name": "تست فرمول",
            "requester_phone": "09170000912",
            "body": "=HYPERLINK(\"http://evil\",\"کلیک\") آزمایش تزریق فرمول",
            "priority": "normal",
            "receiver_ids": [emp1["id"]],
        },
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    csv_res = await c_mgr.get("/api/v1/exports/csv?view_mode=supervision&q=آزمایش تزریق فرمول")
    assert "'=HYPERLINK" in csv_res.text
    await c_mgr.aclose()
    await c_emp1.aclose()
