"""Obunachilar tarixini saqlash (Upstash Redis REST API orqali, kutubxonasiz).

Vercel → Storage → "Upstash for Redis" ulanganda loyiha muhitiga KV_REST_API_URL va
KV_REST_API_TOKEN (yoki UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN) qo'shiladi.
Har kunning yozuvi: jami obunachilar, qo'shilgan, chiqib ketgan. Telegram statistikasi
eski kunlarni qaytarmay qo'ysa ham, saqlangan tarix qoladi.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import date
from typing import Any, Callable


class HistoryStore:
    def __init__(self, url: str, token: str, opener: Callable | None = None):
        self.url = url.rstrip("/")
        self.token = token
        self.opener = opener or urllib.request.urlopen

    def _command(self, *args: str) -> Any:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(list(args)).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="POST",
        )
        with self.opener(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, dict) and payload.get("error"):
            raise RuntimeError(payload["error"])
        return payload.get("result") if isinstance(payload, dict) else payload

    @staticmethod
    def _key(channel: str) -> str:
        return f"tg:{channel.lstrip('@').lower()}:daily"

    def load(self, channel: str) -> dict[date, dict[str, Any]]:
        flat = self._command("HGETALL", self._key(channel)) or []
        out: dict[date, dict[str, Any]] = {}
        for field, value in zip(flat[::2], flat[1::2]):
            try:
                row = json.loads(value)
                out[date.fromisoformat(field)] = {
                    "total": row.get("total"), "joined": row.get("joined"), "left": row.get("left")
                }
            except (ValueError, TypeError, AttributeError):
                continue
        return dict(sorted(out.items()))

    def save(self, channel: str, series: dict[date, dict[str, Any]]) -> int:
        args: list[str] = []
        for day, row in series.items():
            clean = {k: row.get(k) for k in ("total", "joined", "left")}
            if any(v is not None for v in clean.values()):
                args += [day.isoformat(), json.dumps(clean)]
        if args:
            self._command("HSET", self._key(channel), *args)
        return len(args) // 2


def store_from_env(env: dict[str, str] | None = None) -> HistoryStore | None:
    env = os.environ if env is None else env
    url = env.get("KV_REST_API_URL") or env.get("UPSTASH_REDIS_REST_URL")
    token = env.get("KV_REST_API_TOKEN") or env.get("UPSTASH_REDIS_REST_TOKEN")
    return HistoryStore(url, token) if url and token else None


def merge(stored: dict[date, dict[str, Any]], fresh: dict[date, dict[str, Any]]) -> dict[date, dict[str, Any]]:
    """Telegram'dan kelgan yangi qiymatlar ustun; yo'q kunlar saqlangan tarixdan olinadi."""
    out = {d: dict(v) for d, v in stored.items()}
    for d, row in fresh.items():
        base = out.setdefault(d, {"total": None, "joined": None, "left": None})
        for k in ("total", "joined", "left"):
            if row.get(k) is not None:
                base[k] = row[k]
    return dict(sorted(out.items()))
