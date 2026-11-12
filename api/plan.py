"""Vercel funksiyasi: oylik planlarni o'qish va saqlash.

    GET  /api/plan?month=2026-11[&channel=junior_academy]   → {"month", "items", "protected", "storage"}
    POST /api/plan   {"month": "2026-11", "items": [...], "password": "..."}
    POST /api/plan   {"action": "month_start", "month": "2026-11", "total": 5939}  (bo'sh total — avtomatik)

Planlar Upstash Redis'da saqlanadi (KV_REST_API_URL / KV_REST_API_TOKEN).
PLAN_PASSWORD muhit o'zgaruvchisi qo'yilsa, saqlash uchun shu parol kerak.
"""

from __future__ import annotations

import hmac
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_analiz import history, plan  # noqa: E402
from telegram_analiz.loader import ExportError  # noqa: E402
from telegram_analiz.scraper import normalize_channel  # noqa: E402

DEFAULT_CHANNEL = "junior_academy"
MAX_BODY = 32_000


def _store():
    base = history.store_from_env()
    return history.JSONStore(base) if base else None


def _channel(value: str | None) -> str:
    return normalize_channel(value or DEFAULT_CHANNEL)


def get_plan(query: dict[str, list[str]]) -> tuple[int, dict]:
    try:
        channel = _channel((query.get("channel") or [""])[0])
        y, m = plan.parse_month_key((query.get("month") or [""])[0])
    except (ExportError, plan.PlanError) as exc:
        return 400, {"error": str(exc)}
    month = plan.month_key(y, m)
    store = _store()
    base = {"month": month, "protected": bool(os.environ.get("PLAN_PASSWORD")), "storage": bool(store)}
    if not store:
        return 200, base | {"items": [], "error": "Planlarni saqlash uchun baza (Upstash) ulanmagan."}
    try:
        items = store.get(plan.storage_key(channel, month)) or []
    except Exception as exc:  # noqa: BLE001
        return 502, base | {"items": [], "error": f"Bazadan o'qib bo'lmadi: {exc}"}
    return 200, base | {"items": items}


def save_plan(body: bytes) -> tuple[int, dict]:
    try:
        data = json.loads(body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return 400, {"error": "JSON noto'g'ri"}
    if not isinstance(data, dict):
        return 400, {"error": "JSON obyekt kerak"}
    password = os.environ.get("PLAN_PASSWORD")
    if password and not hmac.compare_digest(str(data.get("password") or ""), password):
        return 403, {"error": "Parol noto'g'ri", "protected": True}
    if data.get("action") == "month_start":
        return save_month_start(data)
    try:
        channel = _channel(data.get("channel"))
        y, m = plan.parse_month_key(str(data.get("month") or ""))
        items = plan.clean_items(data.get("items"))
    except (ExportError, plan.PlanError) as exc:
        return 400, {"error": str(exc)}
    store = _store()
    if not store:
        return 503, {"error": "Planlarni saqlash uchun baza (Upstash) ulanmagan."}
    month = plan.month_key(y, m)
    try:
        store.set(plan.storage_key(channel, month), items)
    except Exception as exc:  # noqa: BLE001
        return 502, {"error": f"Bazaga yozib bo'lmadi: {exc}"}
    print(f"[plan] saqlandi: {channel} {month}, {len(items)} ta ko'rsatkich", flush=True)
    return 200, {"month": month, "items": items, "saved": True}


def month_start_key(channel: str, month: str) -> str:
    return f"tg:{channel}:month_start:{month}"


def save_month_start(data: dict) -> tuple[int, dict]:
    """Oy boshidagi obunachilar sonini qo'lda yozish; bo'sh qiymat — avtomatik hisobga qaytarish."""
    try:
        channel = _channel(data.get("channel"))
        y, m = plan.parse_month_key(str(data.get("month") or ""))
        total = plan._number(data.get("total"), "Oy boshidagi son")
    except (ExportError, plan.PlanError) as exc:
        return 400, {"error": str(exc)}
    store = _store()
    if not store:
        return 503, {"error": "Baza (Upstash) ulanmagan."}
    month = plan.month_key(y, m)
    key = month_start_key(channel, month)
    today = datetime.now(timezone(timedelta(hours=5))).date().isoformat()
    try:
        if total is None:
            store.delete(key)
        else:
            store.set(key, {"total": total, "recorded": today, "manual": True})
    except Exception as exc:  # noqa: BLE001
        return 502, {"error": f"Bazaga yozib bo'lmadi: {exc}"}
    print(f"[month_start] {channel} {month}: {'avtomatik' if total is None else total}", flush=True)
    return 200, {"month": month, "total": total, "saved": True}


class handler(BaseHTTPRequestHandler):  # Vercel shu nomni qidiradi
    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(*get_plan(parse_qs(urlparse(self.path).query)))

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            self._send(413, {"error": "So'rov juda katta"})
            return
        self._send(*save_plan(self.rfile.read(length)))
