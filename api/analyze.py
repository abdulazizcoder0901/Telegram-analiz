"""Vercel serverless funksiyasi: @junior_academy dashboardi.

    /api/analyze                      → oxirgi 30 kun
    /api/analyze?preset=this_month    → shu oy (today, yesterday, 7, 14, 30, this_month, last_month, all)
    /api/analyze?month=2026-10        → tanlangan oy
    /api/analyze?from=..&to=..        → aniq sanalar
    &type=photo                       → post turi
    &refresh=1                        → keshni chetlab o'tib qayta yig'ish
    &format=json                      → JSON
    &channel=@boshqa_kanal            → boshqa ochiq kanal
"""

from __future__ import annotations

import html
import os
import sys
import time
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_analiz.analyzer import analyze  # noqa: E402
from telegram_analiz.filters import (  # noqa: E402
    MONTHS_FULL,
    coverage_warning,
    filter_range,
    format_range,
    parse_filters,
    type_options,
)
from telegram_analiz.loader import ExportError  # noqa: E402
from telegram_analiz.report import CSS, render_toolbar, to_html, to_json  # noqa: E402
from telegram_analiz.scraper import _build_chat, fetch_page, normalize_channel, parse_page, parse_tz  # noqa: E402

DEFAULT_CHANNEL = "junior_academy"  # sayt ochilganda shu kanal ko'rsatiladi
DEFAULT_PRESET = "30"
TITLE = "Junior: Telegram"
MAX_POSTS = 2500
TIME_BUDGET = 45  # soniya; Vercel funksiyasi 60 soniyada to'xtatiladi
CACHE_TTL = 600  # yig'ilgan postlar iliq funksiya xotirasida 10 daqiqa saqlanadi
CDN_TTL = 900  # CDN sahifani 15 daqiqa keshlaydi
ACTION = "/api/analyze"

# (kanal, tz) → {"fetched": epoch, "posts": {id: Message}, "info": dict, "complete": bool}
_CACHE: dict[tuple[str, str], dict] = {}


def _error_page(message: str, status: int) -> tuple[int, str, str]:
    body = (
        "<!doctype html><html lang='uz'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Xato</title><style>{CSS}</style></head><body><main>"
        f"<div class='card'><h2>Tahlil qilib bo'lmadi</h2><p>{html.escape(message)}</p>"
        "<p><a href='/'>Qaytadan urinish</a></p></div></main></body></html>"
    )
    return status, "text/html; charset=utf-8", body


def _oldest_date(entry: dict) -> date | None:
    posts = entry["posts"]
    return min(m.date for m in posts.values()).date() if posts else None


def collect(channel: str, tz_raw: str, tz, since: date | None, refresh: bool, deadline: float) -> dict:
    """Postlarni ``since`` sanasigacha yig'adi; keshdagi postlardan davom etadi."""
    key = (channel, tz_raw)
    entry = _CACHE.get(key)
    now = time.time()
    if refresh or entry is None or now - entry["fetched"] > CACHE_TTL:
        page = fetch_page(channel, None, timeout=10)
        posts, info = parse_page(page, channel, tz)
        if not posts and not info.get("title"):
            raise ExportError(f"@{channel} topilmadi yoki ochiq kanal emas.")
        entry = {"fetched": now, "posts": {m.id: m for m in posts}, "info": info, "complete": not posts}
        _CACHE[key] = entry

    while (
        not entry["complete"]
        and len(entry["posts"]) < MAX_POSTS
        and time.monotonic() < deadline
        and (since is None or (_oldest_date(entry) or date.max) >= since)
    ):
        oldest_id = min(entry["posts"])
        if oldest_id <= 1:
            entry["complete"] = True
            break
        posts, _ = parse_page(fetch_page(channel, oldest_id, timeout=10), channel, tz)
        new = [m for m in posts if m.id not in entry["posts"]]
        if not new:
            entry["complete"] = True
            break
        for m in new:
            entry["posts"][m.id] = m
        time.sleep(0.1)
    return entry


def _months(today: date, count: int = 18) -> list[tuple[str, str]]:
    out, y, m = [], today.year, today.month
    for _ in range(count):
        out.append((f"{y}-{m:02d}", f"{y} {MONTHS_FULL[m]}"))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


def _clock(ts: float, tz) -> str:
    return datetime.fromtimestamp(ts, tz).strftime("%H:%M")


def run(query: dict[str, list[str]]) -> tuple[int, str, str]:
    def q(name: str, default: str = "") -> str:
        return (query.get(name) or [default])[0].strip()

    tz_raw = q("tz", "+5") or "+5"
    try:
        channel = normalize_channel(q("channel") or DEFAULT_CHANNEL)
        tz = parse_tz(tz_raw)
    except ExportError as exc:
        return _error_page(str(exc), 400)

    today = datetime.now(tz).date()
    has_range = any(q(k) for k in ("preset", "month", "from", "to"))
    filters = parse_filters(
        period=q("preset") if has_range else DEFAULT_PRESET,
        date_from=q("from"),
        date_to=q("to"),
        types=query.get("type") or [],
        month=q("month"),
    )
    start, end = filters.bounds(today)
    comp = filters.comparison(today)
    since = min(d for d in (start, comp[0] if comp else None) if d) if start else None

    started = time.monotonic()
    try:
        entry = collect(channel, tz_raw, tz, since, bool(q("refresh")), started + TIME_BUDGET)
    except ExportError as exc:
        return _error_page(str(exc), 404 if "topilmadi" in str(exc) else 502)

    chat = _build_chat(channel, list(entry["posts"].values()), entry["info"])
    filtered = filter_range(chat, start, end, filters.types)
    result = analyze(filtered, top_n=10)

    oldest = _oldest_date(entry)
    compare = None
    if comp:
        covered = entry["complete"] or (oldest is not None and oldest <= comp[0])
        compare = analyze(filter_range(chat, comp[0], comp[1], filters.types), top_n=3) if covered else {}
        compare["available"] = covered

    shown = len([m for m in filtered.messages if m.kind == "message"])
    result["filters"] = {
        "preset": filters.preset,
        "month": "-".join(map(str, filters.month)) if filters.month else None,
        "from": str(start or ""),
        "to": str(end or ""),
        "types": filters.types,
        "posts_shown": shown,
        "posts_collected": len(entry["posts"]),
        "compare": {"from": str(comp[0]), "to": str(comp[1]), "available": compare.get("available")} if comp else None,
    }
    if q("format") == "json":
        if compare:
            result["compare"] = {k: compare.get(k) for k in ("totals", "channel")}
        return 200, "application/json; charset=utf-8", to_json(result)

    fetched = entry["fetched"]
    meta = [
        f"<b>{html.escape(format_range(start, end, today))}</b>",
        f"ma'lumot <b>{_clock(fetched, tz)} · <span data-ago='{int(fetched)}'>hozirgina</span></b>",
    ]
    if comp:
        meta.append(f"solishtirish <b>{html.escape(format_range(*comp, today))}</b>"
                    + ("" if compare.get("available") else " <span class='tb-warn'>(ma'lumot yetarli emas)</span>"))
    if chat.subscribers:
        meta.append(f"<i class='dot'></i>obunachilar <b>{chat.subscribers:,}</b>".replace(",", " "))
    meta.append(f"postlar <b>{shown}</b>")
    meta.append(f"keyingi ma'lumot <b>~{_clock(fetched + CDN_TTL, tz)}</b>")

    warnings = []
    cov = coverage_warning(chat, filters, today, complete=entry["complete"])
    if cov:
        warnings.append(cov)
    if end and end >= today - timedelta(days=1) and shown:
        warnings.append("Oxirgi 1–2 kundagi postlar ko'rishlarni hali yig'moqda — ularning ko'rsatkichlari keyin oshadi.")

    base = {"tz": tz_raw}
    if channel != DEFAULT_CHANNEL:
        base["channel"] = channel
    current = dict(base)
    if filters.types:
        current["type"] = filters.types[0]
    if filters.preset:
        current["preset"] = filters.preset
    elif filters.month:
        current["month"] = f"{filters.month[0]}-{filters.month[1]:02d}"
    elif start or end:
        current.update({"from": str(start or ""), "to": str(end or "")})
    toolbar = render_toolbar(
        title=TITLE,
        action=ACTION,
        base=base,
        filters=filters,
        today=today,
        type_options=type_options(chat),
        months=_months(today),
        meta=meta,
        refresh_href=f"{ACTION}?{urlencode(current | {'refresh': str(int(time.time()))})}",
        warnings=warnings,
    )
    page = to_html(result, top_html=toolbar, show_header=False, compare=compare)
    return 200, "text/html; charset=utf-8", page


class handler(BaseHTTPRequestHandler):  # Vercel shu nomni qidiradi
    def do_GET(self):
        status, content_type, body = run(parse_qs(urlparse(self.path).query))
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if status == 200:
            # Bir xil so'rov 15 daqiqa davomida CDN keshidan beriladi.
            self.send_header("Cache-Control", f"public, s-maxage={CDN_TTL}, stale-while-revalidate=3600")
        self.end_headers()
        self.wfile.write(data)
