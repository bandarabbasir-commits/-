from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo
import jdatetime

from app.utils.persian import normalize_digits_ascii, to_persian_digits

TEHRAN_TZ = ZoneInfo("Asia/Tehran")
UTC_TZ = timezone.utc

JALALI_MONTH_NAMES = [
    "",
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]


def utc_now() -> datetime:
    return datetime.now(UTC_TZ)


def to_tehran_dt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(TEHRAN_TZ)


def tehran_today_date():
    return to_tehran_dt(utc_now()).date()


def format_jalali_label(dt: Optional[datetime], include_time: bool = True) -> str:
    """Format UTC datetime in Tehran timezone as '۳۰ آبان ۱۴۰۵ — ۱۵:۴۲'."""
    if dt is None:
        return "—"
    t_dt = to_tehran_dt(dt)
    j_dt = jdatetime.datetime.fromgregorian(datetime=t_dt)
    month_name = JALALI_MONTH_NAMES[j_dt.month]
    date_part = f"{to_persian_digits(j_dt.day)} {month_name} {to_persian_digits(j_dt.year)}"
    if not include_time:
        return date_part
    time_part = f"{to_persian_digits(f'{j_dt.hour:02d}')}:{to_persian_digits(f'{j_dt.minute:02d}')}"
    return f"{date_part} — {time_part}"


def parse_jalali_date(date_str: str) -> jdatetime.date:
    """
    Parse Jalali date string like '1405-08-30' or '۱۴۰۵/۰۸/۳۰'.
    Strictly validates leap years (e.g. Esfand 30) and Nowruz boundaries via jdatetime.
    """
    if not date_str or not date_str.strip():
        raise ValueError("تاریخ شمسی خالی است.")
    norm = normalize_digits_ascii(date_str.strip()).replace("/", "-")
    parts = norm.split("-")
    if len(parts) != 3:
        raise ValueError("قالب تاریخ شمسی باید به شکل YYYY/MM/DD باشد.")
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return jdatetime.date(y, m, d)
    except Exception as exc:
        raise ValueError("تاریخ شمسی نامعتبر است (روز، ماه یا سال کبیسه را بررسی کنید).") from exc


def parse_jalali_datetime_tehran_to_utc(date_str: str, time_str: str = "09:00") -> datetime:
    """Convert Jalali date + HH:MM in Asia/Tehran to UTC aware datetime."""
    j_date = parse_jalali_date(date_str)
    norm_time = normalize_digits_ascii((time_str or "09:00").strip())
    t_parts = norm_time.split(":")
    if len(t_parts) != 2:
        raise ValueError("قالب ساعت باید HH:MM باشد.")
    try:
        hh, mm = int(t_parts[0]), int(t_parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
    except Exception as exc:
        raise ValueError("ساعت واردشده معتبر نیست.") from exc

    g_date = j_date.togregorian()
    tehran_dt = datetime(g_date.year, g_date.month, g_date.day, hh, mm, 0, tzinfo=TEHRAN_TZ)
    return tehran_dt.astimezone(UTC_TZ)


def jalali_range_to_utc_half_open(
    start_date_str: Optional[str],
    end_date_str: Optional[str],
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """
    Convert Jalali start/end date strings to half-open UTC range [start_utc, end_exclusive_utc).
    start_utc = Tehran 00:00:00 of start_date
    end_exclusive_utc = Tehran 00:00:00 of (end_date + 1 day)
    """
    start_utc: Optional[datetime] = None
    end_utc: Optional[datetime] = None

    if start_date_str and start_date_str.strip():
        j_start = parse_jalali_date(start_date_str)
        g_start = j_start.togregorian()
        t_start = datetime(g_start.year, g_start.month, g_start.day, 0, 0, 0, tzinfo=TEHRAN_TZ)
        start_utc = t_start.astimezone(UTC_TZ)

    if end_date_str and end_date_str.strip():
        j_end = parse_jalali_date(end_date_str)
        g_end = j_end.togregorian()
        t_end_next = datetime(g_end.year, g_end.month, g_end.day, 0, 0, 0, tzinfo=TEHRAN_TZ) + timedelta(days=1)
        end_utc = t_end_next.astimezone(UTC_TZ)

    if start_utc and end_utc and start_utc >= end_utc:
        raise ValueError("تاریخ شروع نباید بعد از تاریخ پایان باشد.")

    return start_utc, end_utc
