"""Telegram Desktop eksport faylini (result.json) o'qish va normallashtirish."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class Message:
    id: int
    date: datetime
    sender: str
    sender_id: str
    text: str
    kind: str  # "message" yoki "service"
    media_type: str | None = None
    reply_to: int | None = None
    forwarded_from: str | None = None
    edited: bool = False
    reactions: dict[str, int] = field(default_factory=dict)
    entities: list[dict[str, Any]] = field(default_factory=list)
    action: str | None = None
    views: int | None = None
    link: str | None = None


@dataclass
class Chat:
    name: str
    type: str
    id: int | None
    messages: list[Message]
    username: str | None = None
    description: str | None = None
    subscribers: int | None = None


class ExportError(ValueError):
    """Eksport fayli noto'g'ri formatda bo'lsa."""


def flatten_text(raw: Any) -> str:
    """Telegram matni oddiy satr yoki satr/obyektlar ro'yxati bo'lishi mumkin."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts = []
        for item in raw:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text", "")))
        return "".join(parts)
    return str(raw)


def _media_type(raw: dict[str, Any]) -> str | None:
    if raw.get("media_type"):
        return str(raw["media_type"])
    if "photo" in raw:
        return "photo"
    if "poll" in raw:
        return "poll"
    if "location_information" in raw:
        return "location"
    if "contact_information" in raw:
        return "contact"
    if "file" in raw:
        return "file"
    return None


def _parse_date(raw: dict[str, Any]) -> datetime:
    value = raw.get("date")
    if not value:
        unix = raw.get("date_unixtime")
        if unix is None:
            raise ExportError(f"Xabar #{raw.get('id')} sanasi yo'q")
        return datetime.fromtimestamp(int(unix))
    return datetime.fromisoformat(str(value))


def _parse_reactions(raw: dict[str, Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for reaction in raw.get("reactions") or []:
        if not isinstance(reaction, dict):
            continue
        key = reaction.get("emoji") or reaction.get("document_id") or reaction.get("type", "?")
        result[str(key)] = result.get(str(key), 0) + int(reaction.get("count", 1))
    return result


def parse_message(raw: dict[str, Any]) -> Message:
    kind = str(raw.get("type", "message"))
    sender = raw.get("from") if kind == "message" else raw.get("actor")
    sender_id = raw.get("from_id") if kind == "message" else raw.get("actor_id")
    return Message(
        id=int(raw.get("id", 0)),
        date=_parse_date(raw),
        sender=str(sender) if sender else "Noma'lum",
        sender_id=str(sender_id) if sender_id else "",
        text=flatten_text(raw.get("text")),
        kind=kind,
        media_type=_media_type(raw),
        reply_to=raw.get("reply_to_message_id"),
        forwarded_from=raw.get("forwarded_from"),
        edited=bool(raw.get("edited")),
        reactions=_parse_reactions(raw),
        entities=[e for e in raw.get("text_entities") or [] if isinstance(e, dict)],
        action=raw.get("action"),
    )


def parse_chat(raw: dict[str, Any]) -> Chat:
    if "messages" not in raw:
        raise ExportError("Chatda 'messages' maydoni topilmadi")
    messages = [parse_message(m) for m in raw["messages"] if isinstance(m, dict)]
    messages.sort(key=lambda m: (m.date, m.id))
    return Chat(
        name=str(raw.get("name") or "Nomsiz chat"),
        type=str(raw.get("type", "unknown")),
        id=raw.get("id"),
        messages=messages,
    )


def load_chats(path: str | Path) -> list[Chat]:
    """Bitta chat eksporti yoki to'liq akkaunt eksportini yuklaydi."""
    path = Path(path)
    if path.is_dir():
        path = path / "result.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ExportError(f"Fayl topilmadi: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExportError(f"JSON xato: {exc}") from exc

    if not isinstance(data, dict):
        raise ExportError("Kutilgan format: JSON obyekt")
    if "messages" in data:
        return [parse_chat(data)]
    chats = data.get("chats", {})
    if isinstance(chats, dict) and isinstance(chats.get("list"), list):
        return [parse_chat(c) for c in chats["list"] if isinstance(c, dict) and "messages" in c]
    raise ExportError(
        "Bu Telegram eksport fayliga o'xshamaydi. Telegram Desktop → Export chat history → "
        "Format: Machine-readable JSON tanlang."
    )


def select_chat(chats: list[Chat], name: str | None) -> Chat:
    if not chats:
        raise ExportError("Eksportda birorta ham chat yo'q")
    if name is None:
        if len(chats) == 1:
            return chats[0]
        return max(chats, key=lambda c: len(c.messages))
    lowered = name.lower()
    for chat in chats:
        if chat.name.lower() == lowered or str(chat.id) == name:
            return chat
    matches = [c for c in chats if lowered in c.name.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ExportError(f"'{name}' nomli chat topilmadi")
    names = ", ".join(c.name for c in matches[:10])
    raise ExportError(f"'{name}' bir nechta chatga mos keldi: {names}")
