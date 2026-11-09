"""Oylik planlar: ko'rsatkichlar ro'yxati, haqiqiy qiymatlar (fakt) va saqlash."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any

# kalit → (nom, turi, yo'nalishi, manba)
#   turi: "sum" — oy davomida yig'iladi (temp va prognoz hisoblanadi), "avg" — o'rtacha qiymat
#   yo'nalishi: "up" — ko'pi yaxshi, "down" — plan yuqori chegara (kami yaxshi)
METRICS: dict[str, dict[str, str]] = {
    "joined": {"label": "Qo'shilgan obunachilar", "kind": "sum", "dir": "up", "source": "admin"},
    "net": {"label": "Sof o'sish (obunachi)", "kind": "sum", "dir": "up", "source": "admin"},
    "left": {"label": "Chiqib ketganlar (ko'pi bilan)", "kind": "sum", "dir": "down", "source": "admin"},
    "end_total": {"label": "Obunachilar soni (oy oxiriga)", "kind": "level", "dir": "up", "source": "admin"},
    "posts": {"label": "Postlar soni", "kind": "sum", "dir": "up", "source": "posts"},
    "views": {"label": "Ko'rishlar jami", "kind": "sum", "dir": "up", "source": "posts"},
    "avg_views": {"label": "O'rtacha ko'rish (post)", "kind": "avg", "dir": "up", "source": "posts"},
    "reactions": {"label": "Reaksiyalar", "kind": "sum", "dir": "up", "source": "posts"},
    "custom": {"label": "Boshqa (faktni o'zim kiritaman)", "kind": "sum", "dir": "up", "source": "manual"},
}

# Bo'sh plan uchun taklif qilinadigan qatorlar (qiymatlari bo'sh).
SUGGESTED = [
    {"metric": "joined", "name": "", "plan": None},
    {"metric": "custom", "name": "Sifatli lidlar", "plan": None, "actual": None},
]

MAX_ITEMS = 20


class PlanError(ValueError):
    pass


def month_key(year: int, month: int) -> str:
    return f"{year}-{month:02d}"


def parse_month_key(value: str) -> tuple[int, int]:
    try:
        y, m = (int(x) for x in value.split("-")[:2])
        date(y, m, 1)
        return y, m
    except (ValueError, TypeError, AttributeError) as exc:
        raise PlanError(f"Oy noto'g'ri: {value!r}") from exc


def month_progress(year: int, month: int, today: date) -> dict[str, int]:
    """Oyning necha kuni o'tgani (bugun kiradi)."""
    total = calendar.monthrange(year, month)[1]
    if (year, month) < (today.year, today.month):
        elapsed = total
    elif (year, month) > (today.year, today.month):
        elapsed = 0
    else:
        elapsed = today.day
    return {"days_total": total, "days_elapsed": elapsed}


def storage_key(channel: str, month: str) -> str:
    return f"tg:{channel.lstrip('@').lower()}:plan:{month}"


def _number(value: Any, field: str, allow_none: bool = True) -> float | None:
    if value in (None, ""):
        if allow_none:
            return None
        raise PlanError(f"{field}: qiymat kerak")
    try:
        n = float(str(value).replace(" ", "").replace(",", "."))
    except ValueError as exc:
        raise PlanError(f"{field}: son bo'lishi kerak") from exc
    if not (0 <= n <= 1e10):
        raise PlanError(f"{field}: 0 dan katta bo'lishi kerak")
    return int(n) if n.is_integer() else round(n, 2)


def clean_items(items: Any) -> list[dict[str, Any]]:
    """Brauzerdan kelgan plan qatorlarini tekshiradi va tozalaydi."""
    if not isinstance(items, list):
        raise PlanError("items ro'yxat bo'lishi kerak")
    if len(items) > MAX_ITEMS:
        raise PlanError(f"Ko'pi bilan {MAX_ITEMS} ta ko'rsatkich")
    out = []
    for i, raw in enumerate(items, 1):
        if not isinstance(raw, dict):
            raise PlanError(f"{i}-qator noto'g'ri")
        metric = str(raw.get("metric") or "")
        if metric not in METRICS:
            raise PlanError(f"{i}-qator: noma'lum ko'rsatkich {metric!r}")
        name = str(raw.get("name") or "").strip()[:60]
        if metric == "custom" and not name:
            raise PlanError(f"{i}-qator: ko'rsatkich nomini yozing (masalan, Sifatli lidlar)")
        plan = _number(raw.get("plan"), f"{i}-qator plan", allow_none=False)
        item = {"metric": metric, "name": name, "plan": plan}
        if metric == "custom":
            item["actual"] = _number(raw.get("actual"), f"{i}-qator fakt")
        out.append(item)
    return out


def actuals_for_month(result: dict[str, Any] | None, followers: dict[str, Any] | None) -> dict[str, Any]:
    """analyze() natijasi va obunachilar xulosasidan avtomatik faktlar (yo'q bo'lsa None)."""
    t = (result or {}).get("totals") or {}
    ch = (result or {}).get("channel") or {}
    has_posts = result is not None
    f = followers or {}
    return {
        "posts": t.get("messages", 0) if has_posts else None,
        "views": ch.get("total_views", 0) if has_posts else None,
        "avg_views": ch.get("avg_views") if has_posts and t.get("messages") else None,
        "reactions": t.get("reactions", 0) if has_posts else None,
        "joined": f.get("joined") if followers else None,
        "left": f.get("left") if followers else None,
        "net": (f.get("total_change") if f.get("total_change") is not None else f.get("net")) if followers else None,
        "end_total": f.get("end_total") if followers else None,
    }
