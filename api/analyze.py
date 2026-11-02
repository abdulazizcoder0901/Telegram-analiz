"""Vercel serverless funksiyasi: /api/analyze?channel=@kanal&limit=300

Ochiq kanalni t.me/s dan yig'ib, HTML hisobot (yoki ?format=json bilan JSON) qaytaradi.
"""

from __future__ import annotations

import html
import os
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_analiz.analyzer import analyze  # noqa: E402
from telegram_analiz.filters import apply_filters, coverage_warning, parse_filters, type_options  # noqa: E402
from telegram_analiz.loader import ExportError  # noqa: E402
from telegram_analiz.report import CSS, render_filter_bar, to_html, to_json  # noqa: E402
from telegram_analiz.scraper import normalize_channel, parse_tz, scrape_channel  # noqa: E402

DEFAULT_CHANNEL = "junior_academy"  # sayt ochilganda shu kanal ko'rsatiladi
MAX_POSTS = 600
DEFAULT_POSTS = 300
TIME_BUDGET = 45  # soniya; Vercel funksiyasi 60 soniyada to'xtatiladi
LIMIT_CHOICES = (100, 300, 600)
CACHE_TTL = 600  # yig'ilgan postlar iliq funksiya xotirasida 10 daqiqa saqlanadi
_CACHE: dict[tuple, tuple[float, object]] = {}

NAV = "<nav class='topnav'><span class='muted'>{note}</span></nav>"
EXTRA_CSS = (
    ".topnav{display:flex;flex-wrap:wrap;gap:8px 16px;justify-content:flex-end;"
    "align-items:baseline;margin-bottom:20px;font-size:14px}"
)


def _error_page(message: str, status: int) -> tuple[int, str, str]:
    body = (
        "<!doctype html><html lang='uz'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Xato</title><style>{CSS}{EXTRA_CSS}</style></head><body><main>"
        "<nav class='topnav'><a href='/'>← Qaytadan urinish</a></nav>"
        f"<div class='card'><h2>Tahlil qilib bo'lmadi</h2><p>{html.escape(message)}</p></div>"
        "</main></body></html>"
    )
    return status, "text/html; charset=utf-8", body


def run(query: dict[str, list[str]]) -> tuple[int, str, str]:
    raw = (query.get("channel") or [""])[0].strip() or DEFAULT_CHANNEL
    tz_raw = (query.get("tz") or ["+5"])[0]
    try:
        channel = normalize_channel(raw)
        tz = parse_tz(tz_raw)
    except ExportError as exc:
        return _error_page(str(exc), 400)
    try:
        limit = max(20, min(MAX_POSTS, int((query.get("limit") or [DEFAULT_POSTS])[0])))
    except ValueError:
        limit = DEFAULT_POSTS

    started = time.monotonic()
    pages = 0

    def fetch_with_budget(name, before):
        nonlocal pages
        from telegram_analiz.scraper import fetch_page

        if pages and time.monotonic() - started > TIME_BUDGET:
            return ""  # vaqt tugadi — shu paytgacha yig'ilganini tahlil qilamiz
        pages += 1
        return fetch_page(name, before, timeout=10)

    key = (channel, limit, tz_raw)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL:
        chat = cached[1]
    else:
        try:
            chat = scrape_channel(channel, max_posts=limit, delay=0.15, fetch=fetch_with_budget, tz=tz)
        except ExportError as exc:
            return _error_page(str(exc), 404 if "topilmadi" in str(exc) else 502)
        _CACHE[key] = (time.monotonic(), chat)
        for k in [k for k, (t, _) in _CACHE.items() if time.monotonic() - t > CACHE_TTL]:
            _CACHE.pop(k, None)

    filters = parse_filters(
        period=(query.get("period") or ["all"])[0],
        date_from=(query.get("from") or [""])[0],
        date_to=(query.get("to") or [""])[0],
        types=query.get("type") or [],
    )
    today = datetime.now(tz).date()
    filtered = apply_filters(chat, filters, today)
    result = analyze(filtered, top_n=10)
    result["filters"] = {
        "period": filters.period,
        "from": str(filters.bounds(today)[0] or ""),
        "to": str(filters.bounds(today)[1] or ""),
        "types": filters.types,
        "posts_total": len(chat.messages),
        "posts_shown": len(filtered.messages),
    }
    if (query.get("format") or [""])[0] == "json":
        return 200, "application/json; charset=utf-8", to_json(result)

    bar = render_filter_bar(
        action="/api/analyze",
        hidden={"channel": channel, "tz": tz_raw},
        filters=filters,
        today=today,
        type_options=type_options(chat),
        limit=limit if limit in LIMIT_CHOICES else DEFAULT_POSTS,
        limit_choices=LIMIT_CHOICES,
        shown=len([m for m in filtered.messages if m.kind == "message"]),
        total=len([m for m in chat.messages if m.kind == "message"]),
        warning=coverage_warning(chat, filters, today),
    )
    note = f"Vaqtlar UTC{tz_raw}"
    page = to_html(result, top_html=bar)
    page = page.replace("</style>", EXTRA_CSS + "</style>", 1)
    page = page.replace("<main>", "<main>" + NAV.format(note=html.escape(note)), 1)
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
            self.send_header("Cache-Control", "public, s-maxage=900, stale-while-revalidate=3600")
        self.end_headers()
        self.wfile.write(data)
