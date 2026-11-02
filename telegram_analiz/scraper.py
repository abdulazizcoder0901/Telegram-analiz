"""Ochiq Telegram kanalini https://t.me/s/<kanal> veb-ko'rinishidan yig'ish.

API kalit yoki akkaunt talab qilinmaydi, lekin faqat ochiq (public) kanallar
uchun ishlaydi. Har bir sahifada ~20 ta post bo'ladi, eskiroq postlar
``?before=<id>`` orqali olinadi.
"""

from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone, tzinfo
from html.parser import HTMLParser
from pathlib import Path

from .loader import Chat, ExportError, Message

BASE_URL = "https://t.me/s/"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "source", "wbr"}

_MEDIA_MARKERS = [
    ("tgme_widget_message_roundvideo", "video_message"),
    ("tgme_widget_message_video_player", "video_file"),
    ("tgme_widget_message_voice", "voice_message"),
    ("tgme_widget_message_audio", "audio_file"),
    ("tgme_widget_message_document", "file"),
    ("tgme_widget_message_poll", "poll"),
    ("tgme_widget_message_sticker", "sticker"),
    ("tgme_widget_message_location", "location"),
    ("tgme_widget_message_photo_wrap", "photo"),
    ("tgme_widget_message_grouped", "album"),
    ("message_media_not_supported", "unsupported"),
]


def normalize_channel(name: str) -> str:
    """'@kanal', 't.me/kanal', 'https://t.me/s/kanal/123' → 'kanal'."""
    name = name.strip()
    name = re.sub(r"^(https?://)?(www\.)?(t|telegram)\.me/", "", name)
    name = re.sub(r"^s/", "", name)
    name = name.lstrip("@").split("/")[0].split("?")[0]
    if not re.fullmatch(r"[A-Za-z0-9_]{4,64}", name):
        raise ExportError(f"Kanal nomi noto'g'ri: {name!r}")
    return name


def parse_count(value: str | None) -> int | None:
    """'1.2K' → 1200, '3,4M' → 3400000, '12 345' → 12345."""
    if not value:
        return None
    value = html.unescape(value).strip().replace(" ", "").replace(" ", "")
    match = re.fullmatch(r"([\d.,]+)([KkMmBb]?)", value)
    if not match:
        return None
    number, suffix = match.groups()
    multiplier = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000}[suffix.lower()]
    if suffix:
        number = number.replace(",", ".")
    else:
        number = number.replace(",", "").replace(".", "")
    try:
        return int(round(float(number) * multiplier))
    except ValueError:
        return None


class _ElementText(HTMLParser):
    """Berilgan class'li birinchi elementning ichki matnini oladi."""

    def __init__(self, class_name: str):
        super().__init__(convert_charrefs=True)
        self.class_name = class_name
        self.depth = 0
        self.done = False
        self.parts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        attrs_d = dict(attrs)
        if self.depth == 0:
            classes = (attrs_d.get("class") or "").split()
            if self.class_name in classes and tag not in _VOID_TAGS:
                self.depth = 1
            return
        if tag == "br":
            self.parts.append("\n")
            return
        if tag == "a" and attrs_d.get("href"):
            self.links.append(attrs_d["href"])
        if tag == "img" and attrs_d.get("alt"):
            self.parts.append(attrs_d["alt"])
        if tag not in _VOID_TAGS:
            self.depth += 1

    def handle_endtag(self, tag):
        if self.done or self.depth == 0 or tag in _VOID_TAGS:
            return
        self.depth -= 1
        if self.depth == 0:
            self.done = True

    def handle_data(self, data):
        if self.depth > 0 and not self.done:
            self.parts.append(data)

    @property
    def text(self) -> str:
        return "".join(self.parts).strip()


def _inner_text(fragment: str, class_name: str) -> tuple[str, list[str]]:
    parser = _ElementText(class_name)
    parser.feed(fragment)
    parser.close()
    return parser.text, parser.links


def _first(pattern: str, text: str, flags: int = re.S) -> str | None:
    match = re.search(pattern, text, flags)
    return html.unescape(match.group(1)).strip() if match else None


def _parse_reactions(block: str) -> dict[str, int]:
    reactions: dict[str, int] = {}
    for classes, chunk in re.findall(r'<span class="(tgme_reaction[^"]*)">(.*?)</span>', block, re.S):
        if "paid" in classes:
            emoji = "⭐"  # Telegram Stars (pullik reaksiya)
        elif "<tg-emoji" in chunk:
            emoji = "✨ maxsus"  # kanalning custom emojisi — vebda belgisi ko'rinmaydi
        else:
            emoji = _first(r"<b>(.*?)</b>", chunk) or _first(r'alt="([^"]+)"', chunk) or "?"
        chunk = re.sub(r"<tg-emoji.*?</tg-emoji>", "", chunk, flags=re.S)
        count = parse_count(re.sub(r"<[^>]+>", "", re.sub(r"<b>.*?</b>", "", chunk, flags=re.S)))
        if count:
            reactions[emoji] = reactions.get(emoji, 0) + count
    return reactions


def parse_tz(value: str | None) -> tzinfo | None:
    """'+5', '+05:00', '-3', 'UTC' yoki 'Asia/Tashkent' → tzinfo. None → kompyuter vaqt zonasi."""
    if not value:
        return None
    if value.upper() in {"UTC", "Z", "GMT"}:
        return timezone.utc
    match = re.fullmatch(r"([+-])(\d{1,2})(?::?(\d{2}))?", value.strip())
    if match:
        sign, hours, minutes = match.groups()
        delta = timedelta(hours=int(hours), minutes=int(minutes or 0))
        return timezone(delta if sign == "+" else -delta)
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(value)
    except Exception as exc:  # noqa: BLE001
        raise ExportError(f"Vaqt zonasi noto'g'ri: {value!r} (masalan: +5 yoki Asia/Tashkent)") from exc


def parse_post(block: str, channel: str, tz: tzinfo | None = None) -> Message | None:
    post_ref = _first(r'data-post="([^"]+)"', block)
    if not post_ref or "/" not in post_ref:
        return None
    try:
        post_id = int(post_ref.rsplit("/", 1)[1])
    except ValueError:
        return None

    date_raw = _first(r'<time[^>]*datetime="([^"]+)"', block)
    if not date_raw:
        return None
    date = datetime.fromisoformat(date_raw)
    if date.tzinfo is not None:
        # Tanlangan (yoki kompyuterning) vaqt zonasiga o'tkazib, tz ma'lumotini olib tashlaymiz.
        date = date.astimezone(tz).replace(tzinfo=None)

    text, links = _inner_text(block, "tgme_widget_message_text")
    is_service = "service_message" in block[:400]

    media_type = None
    for marker, kind in _MEDIA_MARKERS:
        if marker in block:
            media_type = kind
            break

    # Post imzosi (agar kanal "Sign messages" yoqqan bo'lsa); aks holda kanalning o'zi.
    author = _first(r'class="tgme_widget_message_from_author"[^>]*>(.*?)</', block)
    forwarded = None
    if "tgme_widget_message_forwarded_from" in block:
        forwarded = _first(
            r'tgme_widget_message_forwarded_from_name"[^>]*>(?:<span[^>]*>)?(.*?)</', block
        ) or "?"

    entities = [
        {"type": "link", "text": href}
        for href in links
        if href.lower().startswith(("http://", "https://", "//"))  # heshteg (?q=…) va tel: emas
    ]
    entities += [
        {"type": "hashtag", "text": tag} for tag in re.findall(r"#[\w\d_]+", text)
    ]

    return Message(
        id=post_id,
        date=date,
        sender=author or channel,
        sender_id=channel,
        text=text,
        kind="service" if is_service else "message",
        media_type=media_type,
        reply_to=int(reply) if (reply := _first(
            r'class="tgme_widget_message_reply[^"]*"\s+href="[^"]*/(\d+)"', block)) else None,
        forwarded_from=forwarded,
        edited=bool(re.search(r"\bedited\b", _first(r'tgme_widget_message_meta"(.*?)</time>', block) or "")),
        reactions=_parse_reactions(block),
        entities=entities,
        views=parse_count(_first(r'class="tgme_widget_message_views"[^>]*>(.*?)</span>', block)),
        link=f"https://t.me/{post_ref}",
    )


def parse_page(page: str, channel: str, tz: tzinfo | None = None) -> tuple[list[Message], dict]:
    info = {
        "title": _first(r'class="tgme_channel_info_header_title"[^>]*>(?:<span[^>]*>)?(.*?)</', page),
        "description": None,
        "subscribers": None,
    }
    desc, _ = _inner_text(page, "tgme_channel_info_description")
    info["description"] = desc or None
    for value, kind in re.findall(
        r'<span class="counter_value">(.*?)</span>\s*<span class="counter_type">(.*?)</span>', page, re.S
    ):
        if "subscriber" in kind or "obunachi" in kind or "member" in kind:
            info["subscribers"] = parse_count(value)

    blocks = re.split(r'(?=<div class="tgme_widget_message_wrap)', page)
    messages = []
    for block in blocks[1:]:
        msg = parse_post(block, channel, tz)
        if msg is not None:
            messages.append(msg)
    return messages, info


def _build_chat(channel: str, posts: list[Message], info: dict) -> Chat:
    title = info.get("title") or f"@{channel}"
    for m in posts:
        if m.sender == channel:
            m.sender = title
    return Chat(
        name=title,
        type="public_channel",
        id=None,
        messages=sorted(posts, key=lambda m: (m.date, m.id)),
        username=channel,
        description=info.get("description"),
        subscribers=info.get("subscribers"),
    )


def fetch_page(channel: str, before: int | None = None, timeout: float = 20.0) -> str:
    url = BASE_URL + channel + (f"?before={before}" if before else "")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise ExportError(f"t.me {exc.code} xato qaytardi: {url}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ExportError(
            f"t.me ga ulanib bo'lmadi ({exc}). Internet yoki tarmoq cheklovlarini tekshiring."
        ) from exc


def scrape_channel(
    channel: str,
    max_posts: int = 1000,
    delay: float = 1.0,
    progress=None,
    fetch=fetch_page,
    tz: tzinfo | None = None,
) -> Chat:
    """Kanalning oxirgi ``max_posts`` ta postini yig'adi."""
    channel = normalize_channel(channel)
    collected: dict[int, Message] = {}
    info: dict = {}
    before: int | None = None

    while len(collected) < max_posts:
        page = fetch(channel, before)
        messages, page_info = parse_page(page, channel, tz)
        if not info:
            info = page_info
            if before is None and not messages and not page_info.get("title"):
                raise ExportError(
                    f"@{channel} topilmadi yoki ochiq kanal emas (t.me/s/{channel} bo'sh)."
                )
        new = [m for m in messages if m.id not in collected]
        if not new:
            break
        for m in new:
            collected[m.id] = m
        if progress:
            progress(len(collected))
        oldest = min(m.id for m in messages)
        if oldest <= 1:
            break
        before = oldest
        if delay:
            time.sleep(delay)

    posts = sorted(collected.values(), key=lambda m: (m.date, m.id))[-max_posts:]
    return _build_chat(channel, posts, info)


def load_saved_html(paths: list[str | Path], channel: str = "kanal", tz: tzinfo | None = None) -> Chat:
    """Brauzerda saqlangan t.me/s sahifalaridan kanalni yuklash (oflayn rejim)."""
    collected: dict[int, Message] = {}
    info: dict = {}
    for path in paths:
        try:
            page = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise ExportError(f"Faylni o'qib bo'lmadi: {path} ({exc})") from exc
        messages, page_info = parse_page(page, channel, tz)
        info = info or page_info
        for m in messages:
            collected[m.id] = m
    if not collected:
        raise ExportError("Saqlangan HTML ichida postlar topilmadi")
    return _build_chat(channel, list(collected.values()), info)
