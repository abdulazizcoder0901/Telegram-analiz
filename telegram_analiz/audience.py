"""Qo'shilgan va chiqib ketganlarni "yangi" / "eski" auditoriyaga ajratish.

Manba — admin log'dan yig'ilgan hodisalar (``history.MemberLog``): har bir obunachi (xeshlangan ID)
uchun qo'shilgan va chiqqan vaqtlari. Telegram jurnalni faqat 48 soat saqlaydi, shuning uchun
kuzatuv boshlanishidan (``tracking_since``) oldingi tarix noma'lum.
"""

from __future__ import annotations

from datetime import date, datetime, timezone, tzinfo
from typing import Any


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _pct(n: int, total: int) -> float:
    return round(100 * n / total, 1) if total else 0.0


def classify(members: dict[str, dict[str, list[str]]], start: date | None, end: date | None,
             tracking_since: str | None, tz: tzinfo | None = None) -> dict[str, Any]:
    """Davrdagi qo'shilish va chiqishlarni guruhlarga ajratadi (son va foiz)."""
    tz = tz or timezone.utc
    since_dt = _parse(tracking_since) if tracking_since else None
    since_day = since_dt.astimezone(tz).date() if since_dt else None

    def in_range(d: date) -> bool:
        return (start is None or d >= start) and (end is None or d <= end)

    joined = {"new": 0, "returning": 0}
    joined_then_left = 0
    left = {"in_period": 0, "old": 0, "unknown": 0}

    for row in members.values():
        events = sorted([(_parse(t), "join") for t in row.get("j", [])] +
                        [(_parse(t), "leave") for t in row.get("l", [])])
        for i, (when, kind) in enumerate(events):
            day = when.astimezone(tz).date()
            if not in_range(day):
                continue
            earlier = events[:i]
            if kind == "join":
                joined["returning" if earlier else "new"] += 1
                if any(k == "leave" for _, k in events[i + 1:]):
                    joined_then_left += 1
            else:
                last_join = next((w for w, k in reversed(earlier) if k == "join"), None)
                if last_join is not None:
                    jday = last_join.astimezone(tz).date()
                    left["in_period" if start is None or jday >= start else "old"] += 1
                elif since_day is not None and start is not None and since_day <= start:
                    left["old"] += 1  # kuzatuvdan oldin (= davr boshidan oldin) qo'shilgan
                else:
                    left["unknown"] += 1

    jt, lt = sum(joined.values()), sum(left.values())
    return {
        "tracking_since": since_dt.astimezone(tz).isoformat(timespec="minutes") if since_dt else None,
        "complete": bool(since_day and start and since_day <= start),
        "joined": {
            "total": jt,
            "groups": [
                {"key": "new", "label": "Birinchi marta qo'shilganlar", "n": joined["new"], "pct": _pct(joined["new"], jt)},
                {"key": "returning", "label": "Qaytganlar (oldin chiqib ketgan)", "n": joined["returning"],
                 "pct": _pct(joined["returning"], jt)},
            ],
            "then_left": {"n": joined_then_left, "pct": _pct(joined_then_left, jt)},
        },
        "left": {
            "total": lt,
            "groups": [
                {"key": "in_period", "label": "Shu davrda qo'shilganlar (yangi auditoriya)", "n": left["in_period"],
                 "pct": _pct(left["in_period"], lt)},
                {"key": "old", "label": "Eski obunachilar (davrdan oldin qo'shilgan)", "n": left["old"],
                 "pct": _pct(left["old"], lt)},
                {"key": "unknown", "label": "Noma'lum (kuzatuv boshlanishidan oldin qo'shilgan bo'lishi mumkin)",
                 "n": left["unknown"], "pct": _pct(left["unknown"], lt)},
            ],
        },
    }


def events_by_day(events: list[dict[str, str]], tz: tzinfo | None = None) -> dict[str, dict[str, int]]:
    """Tekshiruv uchun: jurnaldagi hodisalar kunlar bo'yicha (grafik bilan solishtirish)."""
    tz = tz or timezone.utc
    out: dict[str, dict[str, int]] = {}
    for e in events:
        day = _parse(e["at"]).astimezone(tz).date().isoformat()
        row = out.setdefault(day, {"join": 0, "leave": 0})
        row[e["t"]] += 1
    return dict(sorted(out.items()))
