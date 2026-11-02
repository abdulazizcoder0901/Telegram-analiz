"""Postlarni davr va tur bo'yicha filtrlash, solishtirish davri."""

from __future__ import annotations

import calendar
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

from .analyzer import MEDIA_LABELS
from .loader import Chat

# Tugmalar tartibi (sayt panelidagi kabi).
PRESETS: list[tuple[str, str]] = [
    ("today", "Bugun"),
    ("yesterday", "Kecha"),
    ("7", "7 kun"),
    ("14", "14 kun"),
    ("30", "30 kun"),
    ("this_month", "Shu oy"),
    ("last_month", "O'tgan oy"),
]
EXTRA_PRESETS = {"90": "90 kun", "365": "1 yil", "all": "Butun davr"}
PRESET_LABELS = dict(PRESETS) | EXTRA_PRESETS

MONTHS_SHORT = ["", "yan", "fev", "mar", "apr", "may", "iyun", "iyul", "avg", "sen", "okt", "noy", "dek"]
MONTHS_FULL = ["", "yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust",
               "sentabr", "oktabr", "noyabr", "dekabr"]

TEXT_KEY = "text"  # media_type=None bo'lgan (faqat matnli) postlar


def type_key(media_type: str | None) -> str:
    return media_type or TEXT_KEY


def type_label(key: str) -> str:
    return MEDIA_LABELS.get(None if key == TEXT_KEY else key, key)


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def prev_month(d: date) -> tuple[int, int]:
    return (d.year - 1, 12) if d.month == 1 else (d.year, d.month - 1)


def shift_month(d: date, months: int = -1) -> date:
    """Sanani N oy oldinga/orqaga suradi (31-oktabr → 30-sentabr)."""
    y, m = d.year, d.month + months
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def preset_bounds(key: str, today: date) -> tuple[date | None, date | None]:
    if key == "today":
        return today, today
    if key == "yesterday":
        y = today - timedelta(days=1)
        return y, y
    if key.isdigit():
        return today - timedelta(days=int(key) - 1), today
    if key == "this_month":
        return today.replace(day=1), today
    if key == "last_month":
        return month_bounds(*prev_month(today))
    return None, None  # "all"


def format_range(start: date | None, end: date | None, today: date | None = None) -> str:
    """(2026-11-01, 2026-11-03) → '1–3-noy'; turli oylar → '28-okt – 3-noy'."""
    if not start and not end:
        return "butun davr"
    today = today or date.today()
    start = start or end
    end = end or start

    def year(d: date) -> str:
        return "" if d.year == today.year else f" {d.year}"

    if start == end:
        return f"{start.day}-{MONTHS_SHORT[start.month]}{year(start)}"
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}–{end.day}-{MONTHS_SHORT[end.month]}{year(end)}"
    return f"{start.day}-{MONTHS_SHORT[start.month]}{year(start)} – {end.day}-{MONTHS_SHORT[end.month]}{year(end)}"


@dataclass
class Filters:
    preset: str | None = None       # "7", "this_month", ... yoki None
    month: tuple[int, int] | None = None
    date_from: date | None = None
    date_to: date | None = None
    types: list[str] = field(default_factory=list)

    @property
    def period(self) -> str:
        """Eski nom (CLI uchun): preset, 'month', 'custom' yoki 'all'."""
        if self.preset:
            return self.preset
        if self.month:
            return "month"
        if self.date_from or self.date_to:
            return "custom"
        return "all"

    @property
    def active(self) -> bool:
        return self.period != "all" or bool(self.types)

    def bounds(self, today: date) -> tuple[date | None, date | None]:
        if self.preset:
            return preset_bounds(self.preset, today)
        if self.month:
            start, end = month_bounds(*self.month)
            return start, min(end, today) if start <= today else end
        return self.date_from, self.date_to

    def comparison(self, today: date) -> tuple[date, date] | None:
        """Solishtiriladigan davr: shu oy → o'tgan oy, oy → oldingi oy, N kun → oldingi N kun."""
        start, end = self.bounds(today)
        if not start or not end:
            return None
        if self.preset == "this_month":
            return month_bounds(*prev_month(today))
        if self.preset == "last_month" or self.month:
            return month_bounds(*prev_month(start))
        length = (end - start).days + 1
        return start - timedelta(days=length), start - timedelta(days=1)

    def describe(self, today: date) -> list[str]:
        parts = []
        if self.period != "all":
            parts.append(format_range(*self.bounds(today), today))
        if self.types:
            parts.append(", ".join(type_label(t) for t in self.types))
        return parts


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _parse_month(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    try:
        y, m = (int(x) for x in value.strip().split("-")[:2])
        date(y, m, 1)
        return y, m
    except (ValueError, TypeError):
        return None


def parse_filters(period: str | None = None, date_from: str | None = None,
                  date_to: str | None = None, types: list[str] | str | None = None,
                  month: str | None = None) -> Filters:
    """Ustuvorlik: aniq sanalar > oy > tayyor davr (preset)."""
    start, end = _parse_date(date_from), _parse_date(date_to)
    if start and end and start > end:
        start, end = end, start
    if isinstance(types, str):
        types = [types]
    clean = list(dict.fromkeys(t.strip() for t in types or [] if t and t.strip() and t.strip() != "all"))
    if start or end:
        return Filters(date_from=start, date_to=end, types=clean)
    parsed_month = _parse_month(month)
    if parsed_month:
        return Filters(month=parsed_month, types=clean)
    if period in PRESET_LABELS and period != "all":
        return Filters(preset=period, types=clean)
    return Filters(types=clean)


def filter_range(chat: Chat, start: date | None, end: date | None, types: list[str] | None = None) -> Chat:
    wanted = set(types or [])

    def keep(m) -> bool:
        d = m.date.date()
        if start and d < start:
            return False
        if end and d > end:
            return False
        if wanted and type_key(m.media_type) not in wanted:
            return False
        return True

    return replace(chat, messages=[m for m in chat.messages if keep(m)])


def apply_filters(chat: Chat, f: Filters, today: date | None = None) -> Chat:
    today = today or datetime.now().date()
    return filter_range(chat, *f.bounds(today), f.types)


def type_options(chat: Chat) -> list[tuple[str, str, int]]:
    """Ma'lumotda bor post turlari: (kalit, nom, soni), ko'pidan kamiga."""
    counts = Counter(type_key(m.media_type) for m in chat.messages if m.kind == "message")
    return [(k, type_label(k), n) for k, n in counts.most_common()]


def coverage_warning(chat: Chat, f: Filters, today: date, complete: bool = False) -> str | None:
    """Tanlangan davr yig'ilgan postlardan oldinroq boshlansa, ogohlantirish matni."""
    if complete:
        return None
    start, _ = f.bounds(today)
    msgs = [m for m in chat.messages if m.kind == "message"]
    if not start or not msgs:
        return None
    earliest = msgs[0].date.date()
    if start < earliest:
        return (f"Yig'ilgan {len(msgs)} ta post faqat {earliest} dan boshlanadi, tanlangan davr esa "
                f"{start} dan — natija to'liq emas.")
    return None
