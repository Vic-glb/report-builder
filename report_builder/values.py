"""
Value parsing, with the same discipline as the sibling tools: a value that cannot
be read comes back as None. It is never replaced by zero, by today's date, or by
anything else that would look like real data further down.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

_ODD_SPACES = "    "

_PL_MONTHS = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
    "lipca": 7, "sierpnia": 8, "września": 9, "wrzesnia": 9, "października": 10,
    "pazdziernika": 10, "listopada": 11, "grudnia": 12,
}

_CURRENCY = re.compile(r"(z[łl]|pln|eur|usd|gbp|€|\$|£)", re.IGNORECASE)

_EXCEL_EPOCH = date(1899, 12, 30)
_SERIAL_MIN = (date(1990, 1, 1) - _EXCEL_EPOCH).days
_SERIAL_MAX = (date(2099, 12, 31) - _EXCEL_EPOCH).days


def clean(text: str) -> str:
    """Collapse odd Unicode spaces, normalise to NFC, and trim."""
    for character in _ODD_SPACES:
        text = text.replace(character, " ")
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_date(raw: str, dayfirst: bool = True) -> date | None:
    """Parse a date written in any of the usual spreadsheet formats.

    Handles ISO, dotted and slashed forms, Polish month names, two-digit years
    and Excel serial numbers. Returns None when nothing recognisable is found.
    """
    text = clean(raw)
    if not text:
        return None

    if re.fullmatch(r"\d+", text):
        serial = int(text)
        if _SERIAL_MIN <= serial <= _SERIAL_MAX:
            return _EXCEL_EPOCH + timedelta(days=serial)
        if len(text) == 8:
            return _build(text[0:4], text[4:6], text[6:8])
        return None

    words = re.split(r"[\s.]+", text.lower())
    for index, word in enumerate(words):
        month = _PL_MONTHS.get(word)
        if month and index >= 1:
            day = re.sub(r"\D", "", words[index - 1])
            year = re.sub(r"\D", "", words[index + 1]) if index + 1 < len(words) else ""
            built = _build(year, str(month), day)
            if built:
                return built

    match = re.search(r"(\d{1,4})[-./](\d{1,2})[-./](\d{2,4})", text)
    if not match:
        return None
    a, b, c = match.groups()
    if len(a) == 4:
        return _build(a, b, c)

    first = _build(c, b, a) if dayfirst else _build(c, a, b)
    second = _build(c, a, b) if dayfirst else _build(c, b, a)
    return first or second


def _build(year: str, month: str, day: str) -> date | None:
    try:
        y, m, d = int(year), int(month), int(day)
    except ValueError:
        return None
    if len(year) <= 2:
        y += 2000 if y < 70 else 1900
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_number(raw: str) -> Decimal | None:
    """Parse a number written with any thousands/decimal convention.

    Returns a `Decimal` so that money keeps the exact value it was written with,
    and None when the text is not a number.
    """
    text = clean(raw)
    if not text:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1].strip()
    text = _CURRENCY.sub("", text).replace("+", "").strip()
    if text.startswith("-"):
        negative, text = True, text[1:].strip()

    text = text.replace(" ", "")
    if not text or not re.fullmatch(r"[\d.,]+", text):
        return None

    has_comma, has_dot = "," in text, "." in text
    if has_comma and has_dot:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        text = _single(text, ",")
    elif has_dot:
        text = _single(text, ".")

    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return -value if negative else value


def _single(text: str, separator: str) -> str:
    head, _, tail = text.rpartition(separator)
    if separator in head:
        return text.replace(separator, "")
    if len(tail) == 3 and head and not head.startswith("0"):
        return text.replace(separator, "")
    return text.replace(separator, ".")


def as_datetime(value: date) -> datetime:
    """Excel stores dates as datetimes; convert without changing the day."""
    return datetime(value.year, value.month, value.day)
