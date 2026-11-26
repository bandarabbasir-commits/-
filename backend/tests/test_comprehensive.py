import asyncio
import io
import zipfile
import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import load_workbook
from sqlalchemy import func, select, text

import app.db as app_db
from app.main import app
from app.models import AuditLog, LoginLog, Notification, OutboxEvent, SmsTask, TaskEvent, TaskReminder, User, UserRating
from app.utils.jalali import (
    format_jalali_label,
    jalali_range_to_utc_half_open,
    parse_jalali_date,
    parse_jalali_datetime_tehran_to_utc,
    utc_now,
)
from app.utils.persian import normalize_iran_phone, normalize_persian_for_search, sanitize_spreadsheet_cell
from app.utils.security import hash_password, verify_password
from app.worker import process_due_reminders_once
from tests.conftest import login_as


@pytest.mark.asyncio
async def test_01_argon2id_password_hashing():
    h = hash_password("TestSecret#1405")
    assert h.startswith("$argon2id$")
    assert verify_password("TestSecret#1405", h) is True
    assert verify_password("wrong", h) is False


@pytest.mark.asyncio
async def test_02_persian_normalization_preserves_original_and_normalizes_search():
    raw = "كردستان و يزد با ۱۲۳ و نيم‌فاصله"
    norm = normalize_persian_for_search(raw)
    assert "ي" not in norm
    assert "ك" not in norm
    assert "123" in norm
    assert "\u200c" not in norm
    assert raw.startswith("ك")  # original unchanged


@pytest.mark.asyncio
async def test_03_iran_phone_normalization_and_validation():
    assert normalize_iran_phone("+98 917-000-0001") == "09170000001"
    assert normalize_iran_phone("۰۹۱۷۰۰۰۰۰۰۲") == "09170000002"
    assert normalize_iran_phone("00987630000003") == "07630000003"
    with pytest.raises(ValueError):
        normalize_iran_phone("12345")


@pytest.mark.asyncio
async def test_04_jalali_leap_year_nowruz_and_half_open_range():
    # 1403 is leap year (Esfand 30 valid), 1404 is non-leap (Esfand 30 invalid)
    d_leap = parse_jalali_date("۱۴۰۳/۱۲/۳۰")
    assert d_leap.day == 30
    with pytest.raises(ValueError):
        parse_jalali_date("1404/12/30")
    # Nowruz boundary
    s_utc, e_utc = jalali_range_to_utc_half_open("1405/01/01", "1405/01/01")
    assert (e_utc - s_utc).total_seconds() == 86400
    lbl = format_jalali_label(parse_jalali_datetime_tehran_to_utc("1405/08/30", "15:42"))
    assert "۳۰ آبان ۱۴۰۵ — ۱۵:۴۲" == lbl


@pytest.mark.asyncio
async def test_05_login_generic_error_and_csrf_protection():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:3000") as client:
        # Missing pre-auth CSRF token -> 403
        r_no_csrf = await client.post("/api/v1/auth/login", json={"username": "emp1", "password": "wrong"})
        assert r_no_csrf.status_code == 403

        csrf = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
        r_bad_pw = await client.post(
            "/api/v1/auth/login",
            json={"username": "emp1", "password": "wrong"},
            headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:3000"},
        )
        r_unknown = await client.post(
            "/api/v1/auth/login",
            json={"username": "no_such_user", "password": "wrong"},
            headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:3000"},
        )
        assert r_bad_pw.status_code == 401
        assert r_unknown.status_code == 401
        assert r_bad_pw.json()["detail"] == "نام کاربری یا رمز اشتباه است"
        assert r_unknown.json()["detail"] == "نام کاربری یا رمز اشتباه است"


@pytest.mark.asyncio
async def test_06_login_rate_limit_blocks_after_threshold():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:3000") as client:
        csrf = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
        for _ in range(8):
            await client.post(
                "/api/v1/auth/login",
                json={"username": "rate_test_user", "password": "bad"},
                headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:3000"},
            )
        r_locked = await client.post(
            "/api/v1/auth/login",
            json={"username": "rate_test_user", "password": "bad"},
            headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:3000"},
        )
        assert r_locked.status_code == 429
        # Clear ip bucket for subsequent tests
        async with app_db.AsyncSessionLocal() as db:
            await db.execute(text("DELETE FROM auth_rate_limits"))
            await db.commit()


@pytest.mark.asyncio
async def test_07_single_logout_row_even_with_retries_and_daily_login_score_once():
    c, csrf, user = await login_as("emp4")
    # Second login same day should NOT double-award daily login score
    c2, csrf2, _ = await login_as("emp4")
    r_out1 = await c.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:3000"})
    assert r_out1.status_code == 200
    # Retry logout with revoked cookie -> 401 and zero extra login_logs rows
    r_out2 = await c.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:3000"})
    assert r_out2.status_code == 401

    async with app_db.AsyncSessionLocal() as db_session:
        logs = (
            await db_session.execute(
                select(LoginLog).where(LoginLog.user_id == user["id"], LoginLog.action == "logout")
            )
        ).scalars().all()
        assert len(logs) == 1

        daily_scores = (
            await db_session.execute(
                select(UserRating).where(UserRating.user_id == user["id"], UserRating.source == "auto_daily_login")
            )
        ).scalars().all()
        assert len(daily_scores) == 1

    await c2.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf2, "Origin": "http://localhost:3000"})
    await c.aclose()
    await c2.aclose()


@pytest.mark.asyncio
async def test_08_role_boundaries_admin_supervisor_author_and_multirole():
    c_admin, csrf_adm, _ = await login_as("admin")
    c_sup, csrf_sup, _ = await login_as("sup1")
    c_auth, csrf_auth, _ = await login_as("author1")
    c_multi, csrf_multi, _ = await login_as("multi1")

    # Admin without manager role CANNOT access supervision inbox or send announcements
    assert (await c_admin.get("/api/v1/tasks?view_mode=supervision")).status_code == 403
    assert (
        await c_admin.post(
            "/api/v1/chat/announce",
            json={"body": "تست"},
            headers={"X-CSRF-Token": csrf_adm, "Origin": "http://localhost:3000"},
        )
    ).status_code == 403

    # Supervisor display field alone CANNOT send team announcements
    assert (
        await c_sup.post(
            "/api/v1/chat/announce",
            json={"body": "تست"},
            headers={"X-CSRF-Token": csrf_sup, "Origin": "http://localhost:3000"},
        )
    ).status_code == 403

    # Author CANNOT access tasks inbox
    assert (await c_auth.get("/api/v1/tasks")).status_code == 403

    # Multi-role (manager + admin) accesses BOTH users admin & supervision
    assert (await c_multi.get("/api/v1/users")).status_code == 200
    assert (await c_multi.get("/api/v1/tasks?view_mode=supervision")).status_code == 200

    for cl in (c_admin, c_sup, c_auth, c_multi):
        await cl.aclose()


@pytest.mark.asyncio
async def test_09_directory_hides_pii_and_admin_users_never_leak_hashes():
    c_emp, _, _ = await login_as("emp1")
    c_adm, _, _ = await login_as("admin")

    dir_res = await c_emp.get("/api/v1/users/directory")
    assert dir_res.status_code == 200
    for item in dir_res.json()["items"]:
        assert "username" not in item
        assert "password_hash" not in item

    assert (await c_emp.get("/api/v1/users")).status_code == 403
    adm_res = await c_adm.get("/api/v1/users")
    assert adm_res.status_code == 200
    for u in adm_res.json()["items"]:
        assert "password_hash" not in u
        assert "token_hash" not in u

    await c_emp.aclose()
    await c_adm.aclose()


@pytest.mark.asyncio
async def test_10_draft_author_isolation_and_concurrent_distribution():
    c_auth1, csrf_a1, _ = await login_as("author1")
    c_auth2, _, _ = await login_as("author2")
    c_mgr, csrf_mgr, _ = await login_as("manager1")
    c_emp1, _, emp1 = await login_as("emp1")

    # Author1 creates draft
    d_res = await c_auth1.post(
        "/api/v1/drafts",
        json={"source_type": "sms", "body": "پیش‌نویس تستی برای همزمانی توزیع", "priority": "urgent"},
        headers={"X-CSRF-Token": csrf_a1, "Origin": "http://localhost:3000"},
    )
    assert d_res.status_code == 200
    draft_id = d_res.json()["id"]
    version = d_res.json()["version"]

    # Author2 only sees own drafts (not author1's)
    a2_list = (await c_auth2.get("/api/v1/drafts")).json()["items"]
    assert all(d["id"] != draft_id for d in a2_list)

    # Manager edits draft -> edited_at set, manager_note hidden from author1
    up_res = await c_mgr.patch(
        f"/api/v1/drafts/{draft_id}",
        json={
            "body": "پیش‌نویس تستی ویرایش‌شده توسط مدیر",
            "priority": "urgent",
            "action_flag": "action",
            "manager_note": "یادداشت داخلی مدیر",
            "mark_ready": True,
            "version": version,
        },
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    assert up_res.status_code == 200
    assert up_res.json()["status"] == "ready_to_distribute"
    new_ver = up_res.json()["version"]

    a1_list = (await c_auth1.get("/api/v1/drafts")).json()["items"]
    a1_item = next(d for d in a1_list if d["id"] == draft_id)
    assert a1_item["manager_note"] is None

    # Concurrent distribution attempt -> only 1 succeeds, second returns 409
    r1, r2 = await asyncio.gather(
        c_mgr.post(
            f"/api/v1/drafts/{draft_id}/distribute",
            json={"receiver_ids": [emp1["id"]], "version": new_ver},
            headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
        ),
        c_mgr.post(
            f"/api/v1/drafts/{draft_id}/distribute",
            json={"receiver_ids": [emp1["id"]], "version": new_ver},
            headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
        ),
    )
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 409]
    created_task_id = r1.json()["task_id"] if r1.status_code == 200 else r2.json()["task_id"]

    # Author1 still cannot access converted SmsTask
    assert (await c_auth1.get(f"/api/v1/tasks/{created_task_id}")).status_code == 403

    # Closing draft does NOT create a task
    d2 = await c_auth1.post(
        "/api/v1/drafts",
        json={"source_type": "sms", "body": "پیش‌نویس بسته‌شدنی بدون پرونده", "priority": "normal"},
        headers={"X-CSRF-Token": csrf_a1, "Origin": "http://localhost:3000"},
    )
    d2_id, d2_ver = d2.json()["id"], d2.json()["version"]
    cl_res = await c_mgr.post(
        f"/api/v1/drafts/{d2_id}/close",
        json={"manager_note": "تکراری", "version": d2_ver},
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    assert cl_res.status_code == 200
    assert cl_res.json()["status"] == "closed"

    for cl in (c_auth1, c_auth2, c_mgr, c_emp1):
        await cl.aclose()


@pytest.mark.asyncio
async def test_11_task_get_readonly_idempotent_view_and_privacy_isolation():
    c_mgr, csrf_mgr, _ = await login_as("manager1")
    c_emp1, csrf_e1, emp1 = await login_as("emp1")
    c_emp2, csrf_e2, emp2 = await login_as("emp2")
    c_emp3, _, _ = await login_as("emp3")

    # Manager creates task assigned to emp1 & emp2 with manager_note
    ct = await c_mgr.post(
        "/api/v1/tasks/direct",
        json={
            "source_type": "phone",
            "requester_name": "متقاضی تست حریم خصوصی",
            "requester_phone": "۰۹۱۷۰۰۰۰۲۲۲",
            "body": "متن پرونده برای آزمون مشاهده و یادداشت خصوصی",
            "priority": "urgent",
            "manager_note": "نکته محرمانه مدیر",
            "receiver_ids": [emp1["id"], emp2["id"]],
        },
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    assert ct.status_code == 200
    tid = ct.json()["task_id"]

    # emp3 has NO access -> 403
    assert (await c_emp3.get(f"/api/v1/tasks/{tid}")).status_code == 403
    assert (await c_emp3.post(f"/api/v1/tasks/{tid}/view", headers={"X-CSRF-Token": csrf_mgr})).status_code == 403

    # Manager GET supervision does NOT change view_count or pending status
    det_mgr = await c_mgr.get(f"/api/v1/tasks/{tid}")
    assert det_mgr.status_code == 200
    assert det_mgr.json()["view_count"] == 0
    assert det_mgr.json()["status"] == "pending"
    assert det_mgr.json()["manager_note"] == "نکته محرمانه مدیر"

    # emp1 GET detail is read-only & hides manager_note
    det_e1 = await c_emp1.get(f"/api/v1/tasks/{tid}")
    assert det_e1.json()["view_count"] == 0
    assert det_e1.json()["manager_note"] is None

    # emp1 POST /view with Idempotency-Key transitions pending -> in_progress & counts ONCE
    v1 = await c_emp1.post(
        f"/api/v1/tasks/{tid}/view",
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000", "Idempotency-Key": "open-1"},
    )
    v2 = await c_emp1.post(
        f"/api/v1/tasks/{tid}/view",
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000", "Idempotency-Key": "open-1"},
    )
    assert v1.json()["view_count"] == 1
    assert v1.json()["status"] == "in_progress"
    assert v2.json()["view_count"] == 1

    # emp1 adds default private note + private action
    await c_emp1.post(
        f"/api/v1/tasks/{tid}/notes",
        json={"body": "یادداشت محرمانه کارمند یک"},
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    await c_emp1.post(
        f"/api/v1/tasks/{tid}/notes",
        json={"body": "یادداشت مشترک برای تیم", "visibility": "shared_active_manager"},
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    det_after_note = (await c_emp1.get(f"/api/v1/tasks/{tid}")).json()
    assert det_after_note["first_action_at"] is None  # note does NOT fill first_action_at!

    await c_emp1.post(
        f"/api/v1/tasks/{tid}/action",
        json={
            "status": "in_progress",
            "report_text": "گزارش اقدام خصوصی محرمانه ویژه خود کارمند یک",
            "is_private": True,
            "version": det_after_note["version"],
        },
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )

    # emp2 sees shared note, NEVER sees emp1 private note or private action or private search hit!
    det_e2 = (await c_emp2.get(f"/api/v1/tasks/{tid}")).json()
    note_bodies = [n["body"] for n in det_e2["notes"]]
    assert "یادداشت مشترک برای تیم" in note_bodies
    assert "یادداشت محرمانه کارمند یک" not in note_bodies
    assert all("محرمانه ویژه خود کارمند" not in a["report_text"] for a in det_e2["actions"])

    search_leak = (await c_emp2.get("/api/v1/tasks?q=محرمانه ویژه خود کارمند")).json()["items"]
    assert all(it["id"] != tid for it in search_leak)

    for cl in (c_mgr, c_emp1, c_emp2, c_emp3):
        await cl.aclose()


@pytest.mark.asyncio
async def test_12_secondary_forward_cap_two_removes_sender_access_and_preserves_my_actions():
    c_mgr, csrf_mgr, _ = await login_as("manager1")
    c_emp1, csrf_e1, emp1 = await login_as("emp1")
    c_emp2, _, emp2 = await login_as("emp2")
    c_emp3, csrf_e3, emp3 = await login_as("emp3")
    c_emp4, _, emp4 = await login_as("emp4")

    ct = await c_mgr.post(
        "/api/v1/tasks/direct",
        json={
            "source_type": "sms",
            "requester_name": "آزمون انتقال",
            "requester_phone": "09170000333",
            "body": "پرونده آزمون ارجاع ثانویه و سقف دو نفر",
            "priority": "medium",
            "receiver_ids": [emp1["id"], emp2["id"]],
        },
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    tid = ct.json()["task_id"]

    # Create personal folder & reminder for emp1 before forwarding
    f_res = await c_emp1.post(
        "/api/v1/folders",
        json={"name": "فولدر موقت انتقال"},
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    fid = f_res.json()["id"]
    await c_emp1.put(
        f"/api/v1/tasks/{tid}/folder",
        json={"folder_id": fid},
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    await c_emp1.post(
        f"/api/v1/tasks/{tid}/reminders",
        json={"jalali_date": "1406/01/10", "tehran_time": "10:00", "note": "یادآور قبل انتقال"},
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )

    det = (await c_emp1.get(f"/api/v1/tasks/{tid}")).json()

    # Forwarding to 2 new colleagues when emp2 remains active would make 3 active -> MUST REJECT (409) atomically
    bad_fwd = await c_emp1.post(
        f"/api/v1/tasks/{tid}/action",
        json={
            "status": "in_progress",
            "report_text": "تلاش ارجاع بیش از سقف",
            "forward_to_ids": [emp3["id"], emp4["id"]],
            "version": det["version"],
        },
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    assert bad_fwd.status_code == 409

    # Final status with forward_to_ids -> 422
    bad_final = await c_emp1.post(
        f"/api/v1/tasks/{tid}/action",
        json={
            "status": "success",
            "report_text": "خاتمه همراه با انتقال غیرمجاز",
            "forward_to_ids": [emp3["id"]],
            "version": det["version"],
        },
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    assert bad_final.status_code == 422

    # Valid secondary forward to 1 colleague (emp3) -> emp1 removed, emp2 preserved, emp3 added
    ok_fwd = await c_emp1.post(
        f"/api/v1/tasks/{tid}/action",
        json={
            "status": "in_progress",
            "report_text": "اقدام اولیه انجام و به همکار واحد منتقل شد",
            "forward_to_ids": [emp3["id"]],
            "version": det["version"],
        },
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    assert ok_fwd.status_code == 200
    assert ok_fwd.json()["sender_removed"] is True

    # Sender emp1 loses access to task detail immediately
    assert (await c_emp1.get(f"/api/v1/tasks/{tid}")).status_code == 403
    # Sender's personal folder no longer includes the transferred task
    folders_after = (await c_emp1.get("/api/v1/folders")).json()["items"]
    assert next(f for f in folders_after if f["id"] == fid)["count"] == 0

    # Sender can view own action history on separate safe route without task body/notes
    my_acts = (await c_emp1.get("/api/v1/tasks/my-actions")).json()["items"]
    assert any(a["task_id"] == tid and "اقدام اولیه انجام" in a["report_text"] for a in my_acts)
    assert all("body" not in a and "receivers" not in a for a in my_acts)

    # emp3 completes task as success -> awards success score once; manager reopen preserves first_action_at & prevents duplicate success score
    det3 = (await c_emp3.get(f"/api/v1/tasks/{tid}")).json()
    first_act_ts = det3["first_action_at"]
    assert first_act_ts is not None
    fin = await c_emp3.post(
        f"/api/v1/tasks/{tid}/action",
        json={"status": "success", "report_text": "پرونده با موفقیت کامل حل شد", "version": det3["version"]},
        headers={"X-CSRF-Token": csrf_e3, "Origin": "http://localhost:3000"},
    )
    assert fin.status_code == 200

    reopen = await c_mgr.post(
        f"/api/v1/tasks/{tid}/reopen",
        json={"reason": "بررسی مجدد", "receiver_ids": [emp3["id"]], "version": fin.json()["version"]},
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    assert reopen.status_code == 200
    det_reopened = (await c_mgr.get(f"/api/v1/tasks/{tid}")).json()
    assert det_reopened["first_action_at"] == first_act_ts

    # Close as success again -> no duplicate auto_success rating
    await c_emp3.post(
        f"/api/v1/tasks/{tid}/action",
        json={"status": "success", "report_text": "تکمیل مجدد", "version": det_reopened["version"]},
        headers={"X-CSRF-Token": csrf_e3, "Origin": "http://localhost:3000"},
    )
    async with app_db.AsyncSessionLocal() as db:
        succ_rows = (
            await db.execute(
                select(UserRating).where(UserRating.task_id == tid, UserRating.source == "auto_success")
            )
        ).scalars().all()
        assert len(succ_rows) == 1

    for cl in (c_mgr, c_emp1, c_emp2, c_emp3, c_emp4):
        await cl.aclose()


@pytest.mark.asyncio
async def test_13_reminder_worker_fires_once_and_cancels_ineligible():
    c_mgr, csrf_mgr, _ = await login_as("manager1")
    c_emp5, csrf_e5, emp5 = await login_as("emp5")
    c_emp6, _, emp6 = await login_as("emp6")

    ct = await c_mgr.post(
        "/api/v1/tasks/direct",
        json={
            "source_type": "sms",
            "requester_name": "آزمون یادآور",
            "requester_phone": "09170000444",
            "body": "پرونده آزمون یادآور سررسید",
            "priority": "normal",
            "receiver_ids": [emp5["id"]],
        },
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    tid = ct.json()["task_id"]

    # Insert one due reminder for emp5 and one due reminder for emp6 (who is NOT assigned -> ineligible!)
    past_due = utc_now()
    async with app_db.AsyncSessionLocal() as db:
        r_ok = TaskReminder(
            task_id=tid,
            receiver_id=emp5["id"],
            due_at=past_due,
            note="پیگیری فوری",
            idempotency_key=f"test-rem-ok-{tid}",
        )
        r_inelig = TaskReminder(
            task_id=tid,
            receiver_id=emp6["id"],
            due_at=past_due,
            note="نباید ارسال شود",
            idempotency_key=f"test-rem-bad-{tid}",
        )
        db.add_all([r_ok, r_inelig])
        await db.commit()

    fired_1 = await process_due_reminders_once()
    fired_2 = await process_due_reminders_once()
    assert fired_1 == 1
    assert fired_2 == 0  # never double-fires!

    notifs_e5 = (await c_emp5.get("/api/v1/notifications")).json()["items"]
    notifs_e6 = (await c_emp6.get("/api/v1/notifications")).json()["items"]
    assert any(n["task_id"] == tid and n["type"] == "reminder" for n in notifs_e5)
    assert all(n["task_id"] != tid for n in notifs_e6)

    for cl in (c_mgr, c_emp5, c_emp6):
        await cl.aclose()


@pytest.mark.asyncio
async def test_14_exports_word_rtl_excel_rtl_formula_safe_csv_bom():
    c_mgr, _, _ = await login_as("manager1")
    # Also verify formula neutralization helper directly
    assert sanitize_spreadsheet_cell("=CMD|'/C calc'!A0") == "'=CMD|'/C calc'!A0"
    assert sanitize_spreadsheet_cell("+1+1") == "'+1+1"

    w_res = await c_mgr.get("/api/v1/exports/word?view_mode=supervision")
    assert w_res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(w_res.content)) as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        assert "w:bidi" in doc_xml
        assert "w:bidiVisual" in doc_xml

    x_res = await c_mgr.get("/api/v1/exports/excel?view_mode=supervision")
    assert x_res.status_code == 200
    wb = load_workbook(io.BytesIO(x_res.content))
    assert wb.active.views.sheetView[0].rightToLeft is True

    csv_res = await c_mgr.get("/api/v1/exports/csv?view_mode=supervision")
    assert csv_res.status_code == 200
    assert csv_res.content.startswith(b"\xef\xbb\xbf")

    await c_mgr.aclose()


@pytest.mark.asyncio
async def test_15_trash_restore_inactive_flag_purge_2step_and_archive_isolation():
    c_mgr, csrf_mgr, _ = await login_as("manager1")
    c_adm, csrf_adm, _ = await login_as("admin")
    c_emp7, _, emp7 = await login_as("emp7")

    # Create a task for emp7, soft delete, deactivate emp7, restore -> needs_reassignment=True
    ct = await c_mgr.post(
        "/api/v1/tasks/direct",
        json={
            "source_type": "sms",
            "requester_name": "تست سطل زباله",
            "requester_phone": "09170000555",
            "body": "پرونده آزمون بازیابی سطل و غیرفعالی گیرنده",
            "priority": "normal",
            "receiver_ids": [emp7["id"]],
        },
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    tid = ct.json()["task_id"]

    await c_mgr.post(
        f"/api/v1/tasks/{tid}/trash",
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    # Deactivate emp7
    adm_users = (await c_adm.get("/api/v1/users")).json()["items"]
    u7 = next(u for u in adm_users if u["id"] == emp7["id"])
    await c_adm.post(
        f"/api/v1/users/{emp7['id']}/status",
        json={"is_active": False, "version": u7["version"]},
        headers={"X-CSRF-Token": csrf_adm, "Origin": "http://localhost:3000"},
    )

    trash_items = (await c_adm.get("/api/v1/trash?target_type=task")).json()["items"]
    t_item = next(it for it in trash_items if it["id"] == tid)

    rest_res = await c_adm.post(
        f"/api/v1/trash/{tid}/restore",
        json={"target_type": "task", "version": t_item["version"]},
        headers={"X-CSRF-Token": csrf_adm, "Origin": "http://localhost:3000"},
    )
    assert rest_res.status_code == 200
    assert rest_res.json()["needs_reassignment"] is True

    # Soft delete again and test 2-step purge requires valid phrase & password
    await c_mgr.post(
        f"/api/v1/tasks/{tid}/trash",
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    bad_purge = await c_adm.post(
        "/api/v1/trash/purge",
        json={"target_type": "task", "ids": [tid], "confirm_phrase": "غلط", "password": "TestPass@1405", "expected_count": 1},
        headers={"X-CSRF-Token": csrf_adm, "Origin": "http://localhost:3000"},
    )
    assert bad_purge.status_code == 422
    ok_purge = await c_adm.post(
        "/api/v1/trash/purge",
        json={"target_type": "task", "ids": [tid], "confirm_phrase": "حذف دائم", "password": "TestPass@1405", "expected_count": 1},
        headers={"X-CSRF-Token": csrf_adm, "Origin": "http://localhost:3000"},
    )
    assert ok_purge.status_code == 200
    assert ok_purge.json()["purged_count"] == 1

    # Archive test: create completed task, archive it, verify absent from active inbox, restore
    ct2 = await c_mgr.post(
        "/api/v1/tasks/direct",
        json={
            "source_type": "sms",
            "requester_name": "تست آرشیو",
            "requester_phone": "09170000666",
            "body": "پرونده آزمون آرشیو کاری",
            "priority": "normal",
            "receiver_ids": [emp7["id"] if False else (await c_mgr.get("/api/v1/auth/me")).json()["user"]["id"]],
        },
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    tid2 = ct2.json()["task_id"]
    d2 = (await c_mgr.get(f"/api/v1/tasks/{tid2}")).json()
    await c_mgr.post(
        f"/api/v1/tasks/{tid2}/action",
        json={"status": "success", "report_text": "تکمیل برای آرشیو", "version": d2["version"]},
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    prev = await c_mgr.post(
        "/api/v1/archive/preview",
        json={"target_type": "task", "statuses": ["success"]},
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    assert prev.json()["matching_count"] >= 1
    await c_mgr.post(
        "/api/v1/archive/clear-done",
        json={"target_type": "task", "statuses": ["success"], "reason": "پایان ماه"},
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    sup_items = (await c_mgr.get("/api/v1/tasks?view_mode=supervision&tab=done")).json()["items"]
    assert all(it["id"] != tid2 for it in sup_items)
    await c_mgr.post(
        "/api/v1/archive/restore",
        json={"target_type": "task", "ids": [tid2]},
        headers={"X-CSRF-Token": csrf_mgr, "Origin": "http://localhost:3000"},
    )
    sup_items_after = (await c_mgr.get("/api/v1/tasks?view_mode=supervision&tab=done")).json()["items"]
    assert any(it["id"] == tid2 for it in sup_items_after)

    for cl in (c_mgr, c_adm, c_emp7):
        await cl.aclose()


@pytest.mark.asyncio
async def test_16_backup_no_secrets_and_dry_run_no_db_mutation():
    c_adm, csrf_adm, _ = await login_as("admin")
    exp = await c_adm.get("/api/v1/backups/export")
    assert exp.status_code == 200
    raw = exp.text
    assert "password_hash" not in raw
    assert "token_hash" not in raw
    backup = exp.json()
    assert backup["schema_version"] == "2.0"

    # Modify backup in-memory with one synthetic future task ID to test dry-run makes ZERO changes
    async with app_db.AsyncSessionLocal() as db:
        before_count = int((await db.execute(select(func.count(SmsTask.id)))).scalar() or 0)

    backup_copy = dict(backup)
    backup_copy["data"] = dict(backup["data"])
    backup_copy["data"]["sms_tasks"] = list(backup["data"]["sms_tasks"]) + [
        {
            "id": 999991,
            "source_type": "sms",
            "requester_name": "نمونه پیش‌نمایش",
            "requester_phone_norm": "09170000999",
            "body": "نباید در dry-run ذخیره شود",
            "priority": "normal",
            "status": "pending",
            "action_flag": "action",
            "created_by": None,
            "is_deleted": False,
        }
    ]
    dry = await c_adm.post(
        "/api/v1/backups/dry-run",
        json=backup_copy,
        headers={"X-CSRF-Token": csrf_adm, "Origin": "http://localhost:3000"},
    )
    assert dry.status_code == 200
    assert dry.json()["valid"] is True
    assert dry.json()["counts"]["new_tasks_to_insert"] == 1

    async with app_db.AsyncSessionLocal() as db:
        after_count = int((await db.execute(select(func.count(SmsTask.id)))).scalar() or 0)
    assert before_count == after_count
    await c_adm.aclose()


@pytest.mark.asyncio
async def test_17_append_only_audit_log_and_task_events_db_enforcement():
    async with app_db.AsyncSessionLocal() as db:
        row = AuditLog(action="test.append", target_type="system", target_id="1")
        db.add(row)
        await db.commit()

        with pytest.raises(Exception):
            await db.execute(text("UPDATE audit_log SET action = 'tampered' WHERE id = :id"), {"id": row.id})
        await db.rollback()

        with pytest.raises(Exception):
            await db.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": row.id})
        await db.rollback()

        # Verify task_events forbids UPDATE
        ev_id = (await db.execute(select(TaskEvent.id).limit(1))).scalar_one_or_none()
        if ev_id:
            with pytest.raises(Exception):
                await db.execute(text("UPDATE task_events SET event_type = 'tampered' WHERE id = :id"), {"id": ev_id})
            await db.rollback()


@pytest.mark.asyncio
async def test_18_visits_workflow_and_last_admin_protection():
    c_emp, csrf_e, _ = await login_as("emp2")
    c_mgr, csrf_m, _ = await login_as("manager1")
    c_adm, csrf_a, adm_user = await login_as("admin")

    v_res = await c_emp.post(
        "/api/v1/visits",
        json={
            "person_or_org": "آقای نمونه چهارم",
            "phone": "۰۹۱۷۰۰۰۰۷۷۷",
            "request_desc": "درخواست پیگیری نامه",
            "followup_desc": "هماهنگی با دبیرخانه",
            "action_taken": "ثبت در دفتر",
        },
        headers={"X-CSRF-Token": csrf_e, "Origin": "http://localhost:3000"},
    )
    assert v_res.status_code == 200
    assert v_res.json()["message"] == "گزارش برای بررسی ارسال شد"
    vid = v_res.json()["id"]

    # Reject requires reason
    bad_rev = await c_mgr.post(
        f"/api/v1/visits/{vid}/review",
        json={"decision": "rejected", "review_note": "", "version": 1},
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    assert bad_rev.status_code == 422

    ok_rev = await c_mgr.post(
        f"/api/v1/visits/{vid}/review",
        json={"decision": "approved", "review_note": "تأیید شد", "version": 1},
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    assert ok_rev.status_code == 200

    # Last admin protection: multi1 also has admin role; deactivate multi1 first, then admin cannot be deactivated
    adm_list = (await c_adm.get("/api/v1/users")).json()["items"]
    multi = next(u for u in adm_list if u["username"] == "multi1")
    await c_adm.post(
        f"/api/v1/users/{multi['id']}/status",
        json={"is_active": False, "version": multi["version"]},
        headers={"X-CSRF-Token": csrf_a, "Origin": "http://localhost:3000"},
    )
    adm_self = next(u for u in (await c_adm.get("/api/v1/users")).json()["items"] if u["id"] == adm_user["id"])
    last_adm_block = await c_adm.post(
        f"/api/v1/users/{adm_user['id']}/status",
        json={"is_active": False, "version": adm_self["version"]},
        headers={"X-CSRF-Token": csrf_a, "Origin": "http://localhost:3000"},
    )
    assert last_adm_block.status_code == 409

    for cl in (c_emp, c_mgr, c_adm):
        await cl.aclose()


@pytest.mark.asyncio
async def test_19_chat_reads_and_reports_no_double_counting():
    c_emp1, csrf_e1, emp1 = await login_as("emp1")
    c_emp2, csrf_e2, emp2 = await login_as("emp2")

    msg = await c_emp1.post(
        "/api/v1/chat",
        json={"body": "پیام تست خوانده‌شدن", "client_msg_id": "cli-msg-1"},
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    assert msg.status_code == 200
    mid = msg.json()["id"]

    # Explicit read receipt by emp2
    rd = await c_emp2.post(
        "/api/v1/chat/reads",
        json={"message_ids": [mid]},
        headers={"X-CSRF-Token": csrf_e2, "Origin": "http://localhost:3000"},
    )
    assert rd.status_code == 200
    hist = (await c_emp1.get("/api/v1/chat?channel=public")).json()["items"]
    m_item = next(x for x in hist if x["id"] == mid)
    assert m_item["read_count"] == 1

    # Summary & staff report endpoints succeed and return consistent totals
    c_mgr, _, _ = await login_as("manager1")
    sum_res = await c_mgr.get("/api/v1/reports/summary")
    staff_res = await c_mgr.get("/api/v1/reports/staff")
    assert sum_res.status_code == 200
    assert staff_res.status_code == 200
    assert sum_res.json()["total"] >= 1

    for cl in (c_emp1, c_emp2, c_mgr):
        await cl.aclose()


@pytest.mark.asyncio
async def test_20_postgres_explain_uses_indexes():
    async with app_db.AsyncSessionLocal() as db:
        await db.execute(text("SET LOCAL enable_seqscan = off"))
        exp1 = (
            await db.execute(
                text("EXPLAIN SELECT id FROM sms_tasks WHERE is_deleted = false AND status = 'pending' ORDER BY created_at DESC LIMIT 20")
            )
        ).scalars().all()
        exp2 = (
            await db.execute(
                text("EXPLAIN SELECT id FROM sms_tasks WHERE body_normalized LIKE '%روشنایی%'")
            )
        ).scalars().all()
        assert any("Index" in line or "Bitmap" in line for line in exp1)
        assert any("ix_sms_tasks_body_trgm" in line or "Bitmap" in line or "Index" in line for line in exp2)
