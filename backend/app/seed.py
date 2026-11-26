import argparse
import asyncio
import getpass
import os
import sys
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure backend/ is on sys.path when invoked as script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.models import (
    ChatMessage,
    Draft,
    PersonalFolder,
    FolderItem,
    PublicVisit,
    SmsTask,
    TaskAction,
    TaskAssignment,
    TaskNote,
    TaskReminder,
    User,
    UserRating,
    UserRole,
)
from app.services import add_task_event
from app.utils.jalali import tehran_today_date, utc_now
from app.utils.persian import normalize_persian_for_search
from app.utils.security import compute_avatar_color, hash_password


DEMO_STAFF = [
    ("admin", "کیانوش فرهادی", "مدیر زیرساخت و سامانه", "فناوری اطلاعات", "expert", "technical", ["admin"]),
    ("manager1", "مهشید رستگار", "مدیر کل دفتر پیگیری", "مدیریت دفتر", "supervisor", "referral", ["manager", "employee"]),
    ("author1", "سارا شریفی", "کارشناس ثبت و دبیرخانه", "دبیرخانه", "employee", "office", ["author"]),
    ("emp1", "آرش کمانگر", "کارشناس پیگیری عمرانی", "رسیدگی و پیگیری", "expert", "followup", ["expert"]),
    ("emp2", "نگار پناهی", "کارشناس امور شهری", "رسیدگی و پیگیری", "employee", "followup", ["employee"]),
    ("emp3", "پویا دریاباری", "کارشناس خدمات رفاهی", "رسیدگی و پیگیری", "employee", "followup", ["employee"]),
    ("sup1", "بهرام نیک‌نهاد", "سرپرست میز خدمت", "روابط عمومی", "supervisor", "followup", ["employee"]),
    ("emp4", "مینا تابش", "کارشناس امور آب و برق", "رسیدگی و پیگیری", "expert", "followup", ["expert"]),
    ("emp5", "سهراب قاسمی", "مسئول پیگیری روستایی", "رسیدگی و پیگیری", "employee", "followup", ["employee"]),
    ("emp6", "الهام رادمنش", "کارشناس پاسخ‌گویی", "روابط عمومی", "employee", "office", ["employee"]),
    ("author2", "فرزاد مرادی", "متصدی ورود پیام‌ها", "دبیرخانه", "employee", "office", ["author"]),
    ("emp7", "داریوش برومند", "کارشناس فنی شبکه", "فناوری اطلاعات", "expert", "technical", ["expert"]),
    ("multi1", "شایان مهران‌فر", "معاون هماهنگی و نظارت", "مدیریت دفتر", "supervisor", "referral", ["manager", "admin"]),
]

SYNTHETIC_REQUESTS = [
    ("sms", "شهروند فرضی یک", "09170000001", "پیگیری وضعیت روشنایی معابر بلوار فرضی شرقی و نیاز به بازبینی پایه‌های فرسوده", "urgent", "action"),
    ("phone", "شهروند فرضی دو", "09170000002", "درخواست بررسی افت فشار آب در کوچهٔ نمونه ۱۲ در ساعات عصر", "medium", "followup"),
    ("in_person", "شهروند فرضی سه", "07630000003", "مراجعه جهت استعلام وضعیت مجوز کارگاه صنایع دستی روستای نمونه", "normal", "action"),
    ("social", "شهروند فرضی چهار", "09170000004", "گزارش آب‌گرفتگی سطحی در تقاطع نمونه و درخواست پاک‌سازی کانال", "urgent", "action"),
    ("sms", "شهروند فرضی پنج", "09170000005", "پیشنهاد نصب تابلوهای راهنمای مسیر در ورودی پارک ساحلی نمونه", "normal", "followup"),
    ("sms", "شهروند فرضی شش", "09170000006", "پیگیری زمان‌بندی سرویس ایاب‌وذهاب دانش‌آموزان منطقهٔ حاشیه‌ای نمونه", "medium", "action"),
]


async def upsert_user(
    db: AsyncSession,
    username: str,
    display_name: str,
    password: str,
    job_title: str,
    department: str,
    display_access_level: str,
    org_role_type: str,
    roles: list[str],
) -> User:
    uname_lower = username.lower()
    res = await db.execute(select(User).where(User.username_lower == uname_lower))
    user = res.scalar_one_or_none()
    if user is None:
        user = User(
            username=username,
            username_lower=uname_lower,
            display_name=display_name,
            password_hash=hash_password(password),
            job_title=job_title,
            department=department,
            display_access_level=display_access_level,
            org_role_type=org_role_type,
            avatar_color=compute_avatar_color(uname_lower + display_name),
        )
        db.add(user)
        await db.flush()
        for r in set(roles):
            db.add(UserRole(user_id=user.id, role=r))
    return user


async def seed_production() -> None:
    settings = get_settings()
    pw = settings.admin_initial_password or os.environ.get("ADMIN_INITIAL_PASSWORD", "")
    if not pw:
        if sys.stdin.isatty():
            pw = getpass.getpass("رمز عبور ادمین اولیه را وارد کنید (حداقل ۸ کاراکتر): ")
        else:
            raise RuntimeError("در حالت تولید باید ADMIN_INITIAL_PASSWORD از محیط تزریق شود.")
    if len(pw) < 8:
        raise RuntimeError("رمز عبور ادمین باید حداقل ۸ کاراکتر باشد.")

    async with AsyncSessionLocal() as db:
        await upsert_user(
            db,
            username=settings.admin_initial_username,
            display_name="مدیر اولیه سامانه",
            password=pw,
            job_title="مدیر سامانه",
            department="فناوری اطلاعات",
            display_access_level="expert",
            org_role_type="technical",
            roles=["admin"],
        )
        await db.commit()
    print("Seed تولید با موفقیت انجام شد (فقط ادمین اولیه).")


async def seed_demo(benchmark_25k: bool = False) -> None:
    demo_pw = os.environ.get("DEMO_USER_PASSWORD", "Hormozgan@1405")
    now = utc_now()
    async with AsyncSessionLocal() as db:
        users_by_name: dict[str, User] = {}
        for uname, dname, jtitle, dept, lvl, otype, roles in DEMO_STAFF:
            u = await upsert_user(db, uname, dname, demo_pw, jtitle, dept, lvl, otype, roles)
            users_by_name[uname] = u
        await db.flush()

        existing_tasks = int((await db.execute(select(func.count(SmsTask.id)))).scalar() or 0)
        if existing_tasks == 0:
            mgr = users_by_name["manager1"]
            emp1 = users_by_name["emp1"]
            emp2 = users_by_name["emp2"]
            emp3 = users_by_name["emp3"]
            author1 = users_by_name["author1"]

            created_tasks: list[SmsTask] = []
            for idx, (src, rname, rphone, body, prio, flag) in enumerate(SYNTHETIC_REQUESTS):
                t = SmsTask(
                    source_type=src,
                    requester_name=rname,
                    requester_phone_norm=rphone,
                    body=body,
                    body_normalized=normalize_persian_for_search(body),
                    priority=prio,
                    status="pending" if idx in (0, 3, 5) else ("in_progress" if idx in (1, 4) else "success"),
                    action_flag=flag,
                    manager_note="نیازمند بررسی دقیق در بازهٔ تعیین‌شده" if idx % 2 == 0 else "",
                    created_by=mgr.id,
                    created_at=now - timedelta(hours=idx * 6 + 1),
                    first_action_at=(now - timedelta(hours=idx * 4)) if idx in (1, 2, 4) else None,
                    closed_at=(now - timedelta(hours=2)) if idx == 2 else None,
                    closed_by=emp2.id if idx == 2 else None,
                    view_count=2 if idx in (1, 2, 4) else 0,
                    idempotency_key=f"demo-task-{idx+1}",
                )
                db.add(t)
                await db.flush()
                created_tasks.append(t)

                target_emp = emp1 if idx % 2 == 0 else emp2
                is_open = t.status in ("pending", "in_progress")
                db.add(
                    TaskAssignment(
                        task_id=t.id,
                        sender_id=mgr.id,
                        receiver_id=target_emp.id,
                        priority_at_assignment=t.priority,
                        assigned_at=t.created_at,
                        ended_at=t.closed_at if not is_open else None,
                        end_reason="closed" if not is_open else None,
                        is_active=is_open,
                    )
                )
                if idx == 0:
                    # Also assign emp3 as second active assignee on task 1 to showcase 2-assignee flow
                    db.add(
                        TaskAssignment(
                            task_id=t.id,
                            sender_id=mgr.id,
                            receiver_id=emp3.id,
                            priority_at_assignment=t.priority,
                            assigned_at=t.created_at,
                            is_active=True,
                        )
                    )
                await add_task_event(
                    db,
                    t.id,
                    mgr,
                    {"manager"},
                    "direct_created",
                    {"receivers": target_emp.display_name},
                )
                if idx in (1, 2, 4):
                    act = TaskAction(
                        task_id=t.id,
                        actor_id=target_emp.id,
                        status_after=t.status,
                        report_text="تماس اولیه برقرار شد و پرونده در دستور کار واحد فنی قرار گرفت.",
                        report_normalized=normalize_persian_for_search(
                            "تماس اولیه برقرار شد و پرونده در دستور کار واحد فنی قرار گرفت."
                        ),
                        is_private=False,
                        created_at=t.first_action_at or now,
                    )
                    db.add(act)
                    await db.flush()
                    t.latest_report_summary = act.report_text
                    t.latest_action_id = act.id

            # Personal folder sample for emp1
            pf = PersonalFolder(user_id=emp1.id, name="پیگیری‌های فوری")
            db.add(pf)
            await db.flush()
            db.add(FolderItem(folder_id=pf.id, task_id=created_tasks[0].id, user_id=emp1.id))

            # Private & shared note sample
            db.add(
                TaskNote(
                    task_id=created_tasks[0].id,
                    owner_id=emp1.id,
                    body="یادداشت خصوصی کارشناس جهت پیگیری تلفنی فردا",
                    visibility="private",
                )
            )
            # Reminder sample (future)
            db.add(
                TaskReminder(
                    task_id=created_tasks[0].id,
                    receiver_id=emp1.id,
                    due_at=now + timedelta(hours=24),
                    note="بررسی پاسخ واحد اجرایی",
                    idempotency_key="demo-rem-1",
                )
            )

            # Sample drafts
            draft_bodies = [
                ("پیامک نمونه پیش‌نویس اول جهت بررسی روشنایی معبر فرضی", "urgent", "new"),
                ("تماس تلفنی نمونه جهت بررسی وضعیت شبکهٔ آب محلهٔ فرضی", "medium", "ready_to_distribute"),
            ]
            for d_idx, (dbody, dprio, dstatus) in enumerate(draft_bodies):
                db.add(
                    Draft(
                        author_id=author1.id,
                        source_type="sms",
                        requester_name=f"متقاضی نمونه {d_idx + 1}",
                        requester_phone_norm=f"0917000010{d_idx + 1}",
                        body=dbody,
                        body_normalized=normalize_persian_for_search(dbody),
                        priority=dprio,
                        status=dstatus,
                        idempotency_key=f"demo-draft-{d_idx + 1}",
                    )
                )

            # Sample public visit
            db.add(
                PublicVisit(
                    creator_id=emp1.id,
                    person_or_org="شرکت تعاونی نمونه هرمز",
                    phone_norm="07630001122",
                    request_desc="درخواست هماهنگی جلسهٔ بررسی زیرساخت کارگاهی",
                    followup_desc="ارجاع به کارگروه تخصصی برای بررسی مدارک",
                    action_taken="پرونده تشکیل و رونوشت مدارک دریافت شد",
                    status="pending_review",
                )
            )

            # Sample chat & announcement
            db.add(
                ChatMessage(
                    channel="announcements",
                    sender_id=mgr.id,
                    body="همکاران گرامی، لطفاً پرونده‌های دارای اولویت فوری پیش از پایان وقت اداری تعیین تکلیف شوند.",
                    client_msg_id="demo-ann-1",
                )
            )
            db.add(
                ChatMessage(
                    channel="public",
                    sender_id=emp1.id,
                    body="سلام همکاران، هماهنگی بازدید میدانی پرونده‌های امروز انجام شد.",
                    client_msg_id="demo-pub-1",
                )
            )

            # Sample ratings
            today_t = tehran_today_date()
            for idx, uname in enumerate(["emp1", "emp2", "emp3", "emp4"]):
                u = users_by_name[uname]
                db.add(
                    UserRating(
                        user_id=u.id,
                        score=5 - (idx % 2),
                        source="manual",
                        reason="پیگیری منظم و دقیق در هفتهٔ جاری",
                        awarded_by=mgr.id,
                        award_date_tehran=today_t,
                        idempotency_key=f"demo-rating-{uname}",
                    )
                )

        if benchmark_25k:
            # Generate 25,000 synthetic tasks for PostgreSQL EXPLAIN & load benchmarking
            existing_total = int((await db.execute(select(func.count(SmsTask.id)))).scalar() or 0)
            if existing_total < 25000:
                to_create = 25000 - existing_total
                mgr = users_by_name["manager1"]
                emp_ids = [users_by_name[f"emp{i}"].id for i in range(1, 7)]
                batch_size = 1000
                for start in range(0, to_create, batch_size):
                    tasks_batch = []
                    for j in range(start, min(start + batch_size, to_create)):
                        prio = ["urgent", "medium", "normal"][j % 3]
                        st = ["pending", "in_progress", "success", "failed"][j % 4]
                        body = f"درخواست آزمایشی بنچمارک شماره {j} برای بررسی زیرساخت شهری هرمزگان"
                        tasks_batch.append(
                            SmsTask(
                                source_type=["sms", "phone", "in_person", "social"][j % 4],
                                requester_name=f"متقاضی بنچمارک {j}",
                                requester_phone_norm="09170000099",
                                body=body,
                                body_normalized=normalize_persian_for_search(body),
                                priority=prio,
                                status=st,
                                action_flag="action",
                                created_by=mgr.id,
                                created_at=now - timedelta(minutes=j % 50000),
                                first_action_at=(now - timedelta(minutes=(j % 50000) - 30)) if st != "pending" else None,
                            )
                        )
                    db.add_all(tasks_batch)
                    await db.flush()
                    assigns = [
                        TaskAssignment(
                            task_id=t.id,
                            sender_id=mgr.id,
                            receiver_id=emp_ids[idx % len(emp_ids)],
                            priority_at_assignment=t.priority,
                            assigned_at=t.created_at,
                            is_active=t.status in ("pending", "in_progress"),
                        )
                        for idx, t in enumerate(tasks_batch)
                    ]
                    db.add_all(assigns)
                    await db.flush()
        await db.commit()
    print("Seed دمو با موفقیت انجام شد (۱۳ کاربر نمونه و داده‌های مصنوعی).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="اسکریپت seed سامانه هرمزگان بیدار")
    parser.add_argument("--mode", choices=["prod", "demo"], default="demo")
    parser.add_argument("--benchmark-25k", action="store_true")
    args = parser.parse_args()
    if args.mode == "prod":
        asyncio.run(seed_production())
    else:
        asyncio.run(seed_demo(benchmark_25k=args.benchmark_25k))
