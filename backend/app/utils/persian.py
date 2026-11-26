import re
from typing import Optional

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
ASCII_DIGITS = "0123456789"

_DIGIT_TRANS = str.maketrans(
    PERSIAN_DIGITS + ARABIC_DIGITS,
    ASCII_DIGITS * 2,
)

_TO_PERSIAN_TRANS = str.maketrans(
    ASCII_DIGITS + ARABIC_DIGITS,
    PERSIAN_DIGITS * 2,
)

# Normalize Arabic Yeh/Kaf, ZWNJ, and whitespace for search indexing WITHOUT touching original text
_CHAR_TRANS = str.maketrans({
    "ي": "ی",
    "ى": "ی",
    "ئ": "ی",
    "ك": "ک",
    "ة": "ه",
    "ۀ": "ه",
    "أ": "ا",
    "إ": "ا",
    "آ": "ا",
    "\u200c": " ",  # ZWNJ -> space in search index
    "\u200d": "",
    "\u0640": "",   # Tatweel
    "\xa0": " ",
})

_DIACRITICS_RE = re.compile(r"[\u064B-\u065F\u0670]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_digits_ascii(text: str) -> str:
    return text.translate(_DIGIT_TRANS)


def to_persian_digits(value: object) -> str:
    return str(value).translate(_TO_PERSIAN_TRANS)


def normalize_persian_for_search(text: Optional[str]) -> str:
    if not text:
        return ""
    cleaned = _DIACRITICS_RE.sub("", text)
    cleaned = cleaned.translate(_DIGIT_TRANS).translate(_CHAR_TRANS)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip().lower()
    return cleaned


def normalize_iran_phone(raw: str) -> str:
    """
    Normalize & validate Iranian mobile (09xxxxxxxxx) or landline (0[1-8]xxxxxxxxx).
    Accepts Persian/Arabic digits, +98, 0098, spaces, dashes, parentheses.
    Returns canonical 11-digit ASCII string starting with 0, or raises ValueError in Persian.
    """
    if not raw or not raw.strip():
        raise ValueError("شمارهٔ تماس الزامی است.")
    ascii_str = normalize_digits_ascii(raw.strip())
    # Strip spaces, dashes, dots, parens
    compact = re.sub(r"[\s\-\.\(\)]+", "", ascii_str)
    if compact.startswith("+98"):
        compact = "0" + compact[3:]
    elif compact.startswith("0098"):
        compact = "0" + compact[4:]
    elif compact.startswith("98") and len(compact) == 12:
        compact = "0" + compact[2:]
    elif compact.startswith("9") and len(compact) == 10:
        compact = "0" + compact

    if not compact.isdigit():
        raise ValueError("شمارهٔ تماس فقط باید شامل ارقام معتبر باشد.")

    # Mobile: 09xxxxxxxxx (11 digits)
    if re.fullmatch(r"09\d{9}", compact):
        return compact
    # Landline: 0[1-8]xxxxxxxxx (11 digits, e.g. 0763xxxxxxx) or 8-digit local with area? Enforce standard 11-digit 0[1-8]\d{9}
    if re.fullmatch(r"0[1-8]\d{9}", compact):
        return compact

    raise ValueError("شمارهٔ تماس معتبر نیست (مثال موبایل: ۰۹۱۲۰۰۰۰۰۰۰ یا ثابت با کد شهر: ۰۷۶۳۰۰۰۰۰۰۰).")


def sanitize_spreadsheet_cell(value: Optional[str]) -> str:
    """Prevent CSV/Excel formula injection (DDE/CSV injection)."""
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r", "\n"):
        return "'" + s
    return s
