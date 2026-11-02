"""Postlarni davr va tur bo'yicha filtrlash."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

from .analyzer import MEDIA_LABELS
from .loader import Chat

PERIODS: dict[str, tuple[str, int | None]] = {
    "all": ("Butun davr", None),
    "7": ("Oxirgi 7 kun", 7),
    "30": ("Oxirgi 30 kun", 30),
    "90": ("Oxirgi 90 kun", 90),
    "365": ("Oxirgi 1 yil", 365),
    "custom": ("Tanlangan sanalar", None),
}

TEXT_KEY = "text"  # media_type=None bo'lgan (faqat matnli) postlar


def type_key(media_type: str | None) -> str:
    return media_type or TEXT_KEY


def type_label(key: str) -> str:
    return MEDIA_LABELS.get(None if key == TEXT_KEY else key, key)


@dataclass
class Filters:
    period: str = "all"
    date_from: date | None = None
    date_to: date | None = None
    types: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.period != "all" or bool(self.types)

    def bounds(self, today: date) -> tuple[date | None, date | None]:
        if self.period == "custom":
            return self.date_from, self.date_to
        days = PERIODS.get(self.period, ("", None))[1]
        if days is None:
            return None, None
        return today - timedelta(days=days - 1), today

    def describe(self, today: date) -> list[str]:
        parts = []
        start, end = self.bounds(today)
        if self.period == "custom":
            parts.append(f"{start or '…'} — {end or '…'}")
        elif self.period != "all":
            parts.append(PERIODS[self.period][0].lower())
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


def parse_filters(period: str | None = None, date_from: str | None = None,
                  date_to: str | None = None, types: list[str] | str | None = None) -> Filters:
    start, end = _parse_date(date_from), _parse_date(date_to)
    if start and end and start > end:
        start, end = end, start
    if start or end:
        period = "custom"
    elif period not in PERIODS or period == "custom":
        period = "all"
    if isinstance(types, str):
        types = [types]
    clean = [t.strip() for t in types or [] if t and t.strip() and t.strip() != "all"]
    return Filters(period=period, date_from=start, date_to=end, types=list(dict.fromkeys(clean)))


def apply_filters(chat: Chat, f: Filters, today: date | None = None) -> Chat:
    today = today or datetime.now().date()
    start, end = f.bounds(today)
    wanted = set(f.types)

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


def type_options(chat: Chat) -> list[tuple[str, str, int]]:
    """Ma'lumotda bor post turlari: (kalit, nom, soni), ko'pidan kamiga."""
    counts = Counter(type_key(m.media_type) for m in chat.messages if m.kind == "message")
    return [(k, type_label(k), n) for k, n in counts.most_common()]


def coverage_warning(chat: Chat, f: Filters, today: date) -> str | None:
    """Tanlangan davr yig'ilgan postlardan oldinroq boshlansa, ogohlantirish matni."""
    start, _ = f.bounds(today)
    msgs = [m for m in chat.messages if m.kind == "message"]
    if not start or not msgs:
        return None
    earliest = msgs[0].date.date()
    if start < earliest:
        return (f"Yig'ilgan {len(msgs)} ta post faqat {earliest} dan boshlanadi, tanlangan davr esa "
                f"{start} dan. To'liq natija uchun postlar sonini oshiring.")
    return None
