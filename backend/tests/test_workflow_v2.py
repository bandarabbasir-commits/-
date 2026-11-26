import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text

import app.db as app_db
from app.main import app
from app.models import ArchivedTask, TaskAssignment
from tests.conftest import login_as


@pytest.mark.asyncio
async def test_v2_inbox_metadata_forward_reason_manager_edit_and_single_archive():
    c_mgr, csrf_m, mgr = await login_as("manager1")
    c_emp1, csrf_e1, emp1 = await login_as("emp1")
    c_emp2, csrf_e2, emp2 = await login_as("emp2")

    # 1. Manager creates urgent direct task assigned to emp1
    create_res = await c_mgr.post(
        "/api/v1/tasks/direct",
        json={
            "source_type": "sms",
            "requester_name": "مریم بندرعباسی",
            "requester_phone": "09171112233",
            "body": "پیگیری فوری آب‌گرفتگی معابر محله سورو",
            "priority": "urgent",
            "action_flag": "action",
            "manager_note": "بررسی ظرف دو ساعت",
            "receiver_ids": [emp1["id"]],
        },
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    assert create_res.status_code == 200
    tid = create_res.json()["task_id"]

    # 2. emp1 sees sender_name, assigned_at_label, reminder_count in inbox
    inbox_e1 = await c_emp1.get("/api/v1/tasks?view_mode=my")
    assert inbox_e1.status_code == 200
    row_e1 = next(it for it in inbox_e1.json()["items"] if it["id"] == tid)
    assert row_e1["sender_name"] == mgr["display_name"]
    assert row_e1["assigned_at_label"] and row_e1["assigned_at_label"] != "—"
    assert row_e1["reminder_count"] == 0

    # 3. emp1 adds a reminder -> reminder_count increments to 1
    rem_res = await c_emp1.post(
        f"/api/v1/tasks/{tid}/reminders",
        json={"jalali_date": "1405/09/10", "tehran_time": "10:30", "note": "تماس پیگیری با متقاضی"},
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    assert rem_res.status_code == 200

    inbox_e1_after_rem = await c_emp1.get("/api/v1/tasks?view_mode=my")
    row_e1_rem = next(it for it in inbox_e1_after_rem.json()["items"] if it["id"] == tid)
    assert row_e1_rem["reminder_count"] == 1

    # 4. emp1 views task & performs secondary forward with explicit forward_reason to emp2
    view_res = await c_emp1.post(
        f"/api/v1/tasks/{tid}/view",
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    assert view_res.status_code == 200
    detail_v = (await c_emp1.get(f"/api/v1/tasks/{tid}")).json()["version"]

    fwd_res = await c_emp1.post(
        f"/api/v1/tasks/{tid}/action",
        json={
            "status": "in_progress",
            "report_text": "هماهنگی اولیه انجام شد و به همکار تخصصی ارجاع گردید.",
            "is_private": False,
            "forward_to_ids": [emp2["id"]],
            "forward_reason": "نیاز به بازدید فنی کارشناس منطقه",
            "version": detail_v,
        },
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    assert fwd_res.status_code == 200
    assert fwd_res.json()["sender_removed"] is True

    # emp2 sees forward_reason and sender_name == emp1 in detail
    detail_e2 = (await c_emp2.get(f"/api/v1/tasks/{tid}")).json()
    assert detail_e2["sender_name"] == emp1["display_name"]
    assert any(r["id"] == emp2["id"] and r["forward_reason"] == "نیاز به بازدید فنی کارشناس منطقه" for r in detail_e2["receivers"])
    assert any(ev["event_type"] == "forwarded" and ev["details"].get("reason") == "نیاز به بازدید فنی کارشناس منطقه" for ev in detail_e2["timeline"])

    # 5. Manager uses PATCH /api/v1/tasks/{tid} to edit priority, note, and reassign to emp1
    mgr_patch = await c_mgr.patch(
        f"/api/v1/tasks/{tid}",
        json={
            "priority": "medium",
            "action_flag": "followup",
            "manager_note": "تغییر اولویت و ارجاع مجدد به کارمند اول",
            "receiver_ids": [emp1["id"]],
            "version": detail_e2["version"],
        },
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    assert mgr_patch.status_code == 200
    assert mgr_patch.json()["priority"] == "medium"

    # Non-manager cannot call manager PATCH
    forbidden_patch = await c_emp1.patch(
        f"/api/v1/tasks/{tid}",
        json={"priority": "urgent", "action_flag": "action", "manager_note": "", "version": mgr_patch.json()["version"]},
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    assert forbidden_patch.status_code == 403

    # Cannot archive an open task
    bad_arch = await c_mgr.post(
        f"/api/v1/tasks/{tid}/archive",
        json={"reason": "زودهنگام"},
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    assert bad_arch.status_code == 422

    # 6. emp1 closes task as success -> manager archives closed task via POST /archive
    close_res = await c_emp1.post(
        f"/api/v1/tasks/{tid}/action",
        json={
            "status": "success",
            "report_text": "مشکل معبر به صورت کامل برطرف شد.",
            "version": mgr_patch.json()["version"],
        },
        headers={"X-CSRF-Token": csrf_e1, "Origin": "http://localhost:3000"},
    )
    assert close_res.status_code == 200

    arch_res = await c_mgr.post(
        f"/api/v1/tasks/{tid}/archive",
        json={"reason": "بایگانی تک‌موردی پس از خاتمه"},
        headers={"X-CSRF-Token": csrf_m, "Origin": "http://localhost:3000"},
    )
    assert arch_res.status_code == 200

    async with app_db.AsyncSessionLocal() as db:
        arch_row = (await db.execute(select(ArchivedTask).where(ArchivedTask.task_id == tid))).scalar_one_or_none()
        assert arch_row is not None
        assert arch_row.reason == "بایگانی تک‌موردی پس از خاتمه"

    await c_mgr.aclose()
    await c_emp1.aclose()
    await c_emp2.aclose()


@pytest.mark.asyncio
async def test_v2_bootstrap_status_reflects_seeded_users():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:3000") as client:
        st = await client.get("/api/v1/auth/bootstrap-status")
        assert st.status_code == 200
        assert st.json()["needs_setup"] is False

        # Calling bootstrap-admin when users exist is blocked with 409
        csrf = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
        bad = await client.post(
            "/api/v1/auth/bootstrap-admin",
            json={"username": "adm2", "display_name": "مدیر دوم", "password": "StrongPassword@1405"},
            headers={"X-CSRF-Token": csrf, "Origin": "http://localhost:3000"},
        )
        assert bad.status_code == 409
