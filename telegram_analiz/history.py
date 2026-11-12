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


class JSONStore:
    """HistoryStore ustida oddiy JSON kalit/qiymat (planlar uchun)."""

    def __init__(self, store: HistoryStore):
        self.store = store

    def get(self, key: str) -> Any:
        value = self.store._command("GET", key)
        return json.loads(value) if value else None

    def set(self, key: str, value: Any) -> None:
        self.store._command("SET", key, json.dumps(value, ensure_ascii=False))

    def delete(self, key: str) -> None:
        self.store._command("DEL", key)

    def set_once(self, key: str, value: Any) -> bool:
        """Kalit bo'sh bo'lsagina yozadi (SET NX). Yozilgan bo'lsa True."""
        return self.store._command("SET", key, json.dumps(value, ensure_ascii=False), "NX") == "OK"


def store_from_env(env: dict[str, str] | None = None) -> HistoryStore | None:
    """KV_REST_API_URL/TOKEN, UPSTASH_REDIS_REST_URL/TOKEN yoki istalgan prefiksli
    <PREFIKS>_REST_API_URL/<PREFIKS>_REST_API_TOKEN juftligini topadi."""
    env = os.environ if env is None else env
    pairs = [("KV_REST_API_URL", "KV_REST_API_TOKEN"), ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN")]
    pairs += [(k, k[: -len("URL")] + "TOKEN") for k in sorted(env)
              if k.endswith("_REST_API_URL") and not k.startswith("KV_")]
    for url_key, token_key in pairs:
        if env.get(url_key) and env.get(token_key):
            return HistoryStore(env[url_key], env[token_key])
    return None


def merge(stored: dict[date, dict[str, Any]], fresh: dict[date, dict[str, Any]]) -> dict[date, dict[str, Any]]:
    """Telegram'dan kelgan yangi qiymatlar ustun; yo'q kunlar saqlangan tarixdan olinadi."""
    out = {d: dict(v) for d, v in stored.items()}
    for d, row in fresh.items():
        base = out.setdefault(d, {"total": None, "joined": None, "left": None})
        for k in ("total", "joined", "left"):
            if row.get(k) is not None:
                base[k] = row[k]
    return dict(sorted(out.items()))


class MemberLog:
    """Obunachilarning qo'shilish/chiqish vaqtlari (ID'lar xeshlangan).

    tg:<kanal>:members        hash: <xesh> → {"j": [ISO...], "l": [ISO...]}
    tg:<kanal>:members_since  kuzatuv qachondan boshlangani (eng birinchi yozilgan hodisa vaqti)
    """

    def __init__(self, store: HistoryStore):
        self.store = store

    @staticmethod
    def _keys(channel: str) -> tuple[str, str]:
        ch = channel.lstrip("@").lower()
        return f"tg:{ch}:members", f"tg:{ch}:members_since"

    def record(self, channel: str, events: list[dict[str, str]], now_iso: str) -> int:
        """Yangi hodisalarni qo'shadi (takrorlarsiz). Nechta foydalanuvchi yozuvi o'zgarganini qaytaradi."""
        key, since_key = self._keys(channel)
        first = min([e["at"] for e in events] + [now_iso])
        self.store._command("SET", since_key, first, "NX")
        if not events:
            return 0
        users = sorted({e["u"] for e in events})
        current = self.store._command("HMGET", key, *users) or [None] * len(users)
        rows = {}
        for u, raw in zip(users, current):
            try:
                rows[u] = json.loads(raw) if raw else {"j": [], "l": []}
            except ValueError:
                rows[u] = {"j": [], "l": []}
        changed = set()
        for e in events:
            lst = rows[e["u"]]["j" if e["t"] == "join" else "l"]
            if e["at"] not in lst:
                lst.append(e["at"])
                lst.sort()
                changed.add(e["u"])
        if changed:
            args: list[str] = []
            for u in sorted(changed):
                args += [u, json.dumps(rows[u], separators=(",", ":"))]
            self.store._command("HSET", key, *args)
        return len(changed)

    def load(self, channel: str) -> tuple[dict[str, dict[str, list[str]]], str | None]:
        key, since_key = self._keys(channel)
        flat = self.store._command("HGETALL", key) or []
        members = {}
        for u, raw in zip(flat[::2], flat[1::2]):
            try:
                members[u] = json.loads(raw)
            except ValueError:
                continue
        return members, self.store._command("GET", since_key)
