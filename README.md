# هرمزگان بیدار — نسخهٔ ۲

سامانهٔ داخلی، امن، سریع و تمام‌فارسی (RTL) برای ثبت، بررسی، ارجاع، پیگیری و گزارش‌گیری درخواست‌ها و مراجعات مردمی دفتر.

---

## ۱. معماری فنی

- **بک‌اند**: Python 3.11 + FastAPI + Pydantic v2 + SQLAlchemy Async (`asyncpg`) + PostgreSQL 15 (`pg_trgm`) + Alembic + Argon2id (`argon2-cffi`) + `jdatetime` + `python-docx` + `openpyxl`.
- **فرانت‌اند**: React 19 + TypeScript + Vite 8 + Tailwind CSS v4 + `@tanstack/react-query` + فونت محلی `Vazirmatn` + `lucide-react` + PWA (`vite-plugin-pwa`).
- **همگام‌سازی زنده**: WebSocket (`/api/v1/ws`) با الگوی `Transactional Outbox + PostgreSQL LISTEN/NOTIFY` و دریافت تغییرات ازدست‌رفته از طریق `since_event_id`.
- **زمان‌بندی و یادآورها**: Worker پس‌زمینه روی جدول `task_reminders` با قفل `FOR UPDATE SKIP LOCKED` (ضمانت اجرای تک‌باره بدون تکرار بین چند ورکر).
- **امنیت نشست و شبکه**: کوکی‌های `HttpOnly; SameSite=Lax` با توکن تصادفی ۲۵۶بیتی (ذخیرهٔ هش SHA-256 در جدول `sessions`)، توکن `X-CSRF-Token` و اعتبارسنجی `Origin`، محدودیت نرخ ورود روی PostgreSQL و مسدودسازی کش `/api/*` در Service Worker.

---

## ۲. نقش‌های دسترسی (RBAC چندنقشی)

نقش‌ها به‌صورت افزایشی در جدول `user_roles` نگهداری می‌شوند و کاربر می‌تواند هم‌زمان چند نقش داشته باشد:
- `admin` (مدیر سامانه): مدیریت کاربران، سطل زباله، گزارش ورود و خروج، پشتیبان‌گیری JSON و بازیابی، بایگانی، و متریک‌های فنی. (عدم دسترسی خودکار به محتوای پیام‌های کارتابل مگر با نقش `employee`/`expert`/`manager`).
- `manager` (مدیر دفتر / ارجاع): ایجاد مستقیم پیام، ویرایش و توزیع پیش‌نویس‌ها، حالت نظارت کل دفتر، بازگشایی پروندهٔ مختومه، بررسی مراجعات، بایگانی، اعلامیه‌ها و امتیازدهی دستی.
- `author` (نگارنده): ثبت پیش‌نویس و مشاهدهٔ وضعیت پیش‌نویس‌های ثبت‌شده توسط خودش.
- `employee` / `expert` (کارمند / کارشناس): صندوق پیگیری کارتابل شخصی، ثبت اقدام، ارجاع ثانویه (سقف ۲ گیرنده)، یادداشت شخصی/اشتراکی، یادآور، ثبت مراجعات و چت عمومی.

---

## ۳. راه‌اندازی محلی (توسعه و پیش‌نمایش)

1. اطمینان از فعال‌بودن PostgreSQL 15 و اجرای مایگریشن‌های Alembic:
   ```bash
   cd backend
   .venv/bin/alembic upgrade head
   ```
2. بارگذاری داده‌های آزمایشی (صرفاً در محیط `development`):
   ```bash
   .venv/bin/python -m app.seed --mode demo
   ```
3. اجرای هم‌زمان سرور Express (پورت ۳۰۰۰)، FastAPI (پورت ۸۰۰۰) و Vite:
   ```bash
   npm run dev
   ```

---

## ۴. استقرار با Docker و Nginx (Production)

1. فایل `.env` را از روی `.env.example` بسازید و مقادیر `SECRET_KEY` (حداقل ۳۲ کاراکتر تصادفی)، رمزهای پایگاه داده، `ALLOWED_ORIGINS` و `ADMIN_INITIAL_PASSWORD` را تنظیم کنید (`DEMO_SEED_ENABLED=false` و `COOKIE_SECURE=true` پشت HTTPS).
2. ساخت و اجرای سرویس‌ها:
   ```bash
   docker compose up -d --build
   ```
3. ایجاد نخستین مدیر سامانه بدون رمز پیش‌فرض نمونه:
   ```bash
   docker compose exec api python -m app.seed --mode production
   ```
4. **توصیهٔ Nginx و TLS بیرونی**: پشت Reverse Proxy سازمان (TLS 1.3)، هدرهای `Upgrade` و `Connection "upgrade"` را به سرویس `web` (یا مستقیم برای `/api/v1/ws`) عبور دهید و `proxy_read_timeout 3600s` را حفظ کنید.

---

## ۵. عملیات نگهداری، بکاپ رمزنگاری‌شده و مهاجرت داده

- **پشتیبان‌گیری PostgreSQL و تمرین بازیابی (Drill)**:
  ```bash
  # تهیه بکاپ فشرده و رمزنگاری با GPG/Age
  pg_dump -Fc -U hb_admin hormozgan_bidar | gpg --symmetric --cipher-algo AES256 -o backup-$(date +%F).dump.gpg

  # آزمایش بازیابی در پایگاه داده موقت
  gpg --decrypt backup-YYYY-MM-DD.dump.gpg | pg_restore -U hb_admin -d hormozgan_bidar_drill --clean --if-exists
  ```
- **بکاپ کاربردی JSON v2 و Dry-Run**: از منوی «پشتیبان‌گیری» در پنل مدیر سامانه قابل دریافت و بررسی بدون تغییر دیتابیس (`POST /api/v1/backups/dry-run`) است.
- **مهاجرت از نسخهٔ قدیمی**: پیش از انتقال داده‌های قدیمی، شماره‌های تماس به فرمت `09xxxxxxxxx` نرمال‌سازی، متن‌های عربی/فارسی یکدست‌سازی، شناسه‌ها حفظ و تمام کاربران ملزم به تنظیم رمز عبور جدید با Argon2id می‌شوند.

---

## ۶. جداکردن مفروضات قابل‌پیکربندی از تصمیم‌های معماری ثابت

- **قابل‌پیکربندی (از طریق متغیرهای محیطی)**: امتیاز ورود روزانه (`AUTO_SCORE_DAILY_LOGIN=1`)، امتیاز اقدام به‌موقع (`AUTO_SCORE_TIMELY_ACTION=4`)، امتیاز اتمام موفق (`AUTO_SCORE_SUCCESS=5`)، سقف SLA برحسب ساعت (`SLA_HOURS_URGENT=2`، `SLA_HOURS_MEDIUM=24`، `SLA_HOURS_NORMAL=72`)، سقف ردیف خروجی (`EXPORT_MAX_ROWS=10000`) و زمان انقضای نشست (`SESSION_IDLE_MINUTES=120`، `SESSION_ABSOLUTE_HOURS=24`).
- **تصمیم‌های معماری ثابت**: یکتایی منبع حقیقت در PostgreSQL 15، رمزنگاری Argon2id، احراز هویت مبتنی بر کوکی `HttpOnly` + CSRF + Origin، پوشهٔ شخصی به‌ازای هر کاربر (`۱` پوشه برای هر کارتابل)، سقف `۲` گیرنده در ارجاع ثانویه، عدم افشای کد ملی/شماره تماس/IP در دایرکتوری یا اعلان‌ها، و ممنوعیت کش API در Service Worker.
