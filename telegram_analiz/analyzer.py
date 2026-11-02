"""Chat / kanal statistikasini hisoblash."""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlparse

from .loader import Chat, Message

WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]

MEDIA_LABELS = {
    None: "Matn",
    "photo": "Rasm",
    "video_file": "Video",
    "video_message": "Video xabar (dumaloq)",
    "voice_message": "Ovozli xabar",
    "audio_file": "Audio",
    "sticker": "Stiker",
    "animation": "GIF",
    "file": "Fayl",
    "poll": "So'rovnoma",
    "location": "Joylashuv",
    "contact": "Kontakt",
    "album": "Albom",
}

STOPWORDS = set(
    """
    va bilan uchun bu u ham esa emas edi deb bor yoq yo'q lekin ammo endi shu
    bir har biz siz men sen ular nima qanday qachon qayerda kerak mumkin bo'ladi
    bo'lib bo'lsa bo'lgan qilib qilish edi ekan juda eng yana faqat agar chunki
    hamda yoki keyin oldin ko'p kam hech mana hali gacha dan ga ni ning da ta
    и в во не что он на я с со как а то все она так его но да ты к у же вы за
    бы по только ее мне было вот от меня еще нет о из ему теперь когда даже ну
    ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом
    себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам
    это этот эта эти тот при
    the and for are but not you all any can her was one our out has have this
    that with from they will would there their what about which when your just
    https http www com
    """.split()
)

_WORD_RE = re.compile(r"[^\W\d_](?:[\w'ʻʼ‘’`-]*[^\W\d_])?", re.UNICODE)
_URL_RE = re.compile(r"https?://[^\s<>\"']+|(?:t\.me|telegram\.me)/[^\s<>\"']+", re.I)
_HASHTAG_RE = re.compile(r"(?<!\w)#[\w]+", re.UNICODE)
_MENTION_RE = re.compile(r"(?<!\w)@[A-Za-z][A-Za-z0-9_]{3,}")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF\U0001FA70-\U0001FAFF☀-⛿✀-➿"
    "⭐⭕❤✅❌"
    "]"
)


def _words(text: str) -> list[str]:
    """Havola, heshteg va eslatmalarsiz so'zlar ro'yxati."""
    for pattern in (_URL_RE, _HASHTAG_RE, _MENTION_RE):
        text = pattern.sub(" ", text)
    return [w.lower() for w in _WORD_RE.findall(text)]


def _links(msg: Message) -> list[str]:
    found = list(_URL_RE.findall(msg.text))
    for entity in msg.entities:
        if entity.get("type") in {"link", "text_link"}:
            value = entity.get("href") or entity.get("text")
            if value:
                found.append(str(value))
    return list(dict.fromkeys(found))


def _domain(url: str) -> str:
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _top(counter: Counter, n: int) -> list[list[Any]]:
    return [[k, v] for k, v in counter.most_common(n)]


def _streak(days: set[date]) -> dict[str, Any]:
    best = (0, None, None)
    run_start = None
    prev = None
    for day in sorted(days):
        if prev is not None and day - prev == timedelta(days=1):
            pass
        else:
            run_start = day
        length = (day - run_start).days + 1
        if length > best[0]:
            best = (length, run_start, day)
        prev = day
    return {
        "days": best[0],
        "start": best[1].isoformat() if best[1] else None,
        "end": best[2].isoformat() if best[2] else None,
    }


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 1) if values else 0.0


def analyze(chat: Chat, top_n: int = 15, reply_gap_hours: float = 6.0) -> dict[str, Any]:
    msgs = [m for m in chat.messages if m.kind == "message"]
    service = [m for m in chat.messages if m.kind != "message"]

    result: dict[str, Any] = {
        "chat": {
            "name": chat.name,
            "type": chat.type,
            "username": chat.username,
            "description": chat.description,
            "subscribers": chat.subscribers,
        },
        "totals": {"messages": len(msgs), "service_messages": len(service)},
    }
    if not msgs:
        return result

    first, last = msgs[0].date, msgs[-1].date
    span_days = (last.date() - first.date()).days + 1
    active_days = {m.date.date() for m in msgs}
    words_all: Counter = Counter()
    emoji: Counter = Counter()
    hashtags: Counter = Counter()
    mentions: Counter = Counter()
    domains: Counter = Counter()
    media: Counter = Counter()
    reactions: Counter = Counter()
    by_hour = [0] * 24
    by_weekday = [0] * 7
    by_day: Counter = Counter()
    by_month: Counter = Counter()
    heatmap = [[0] * 24 for _ in range(7)]
    lengths: list[int] = []
    per_sender: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"messages": 0, "words": 0, "chars": 0, "media": 0, "replies": 0,
                 "forwards": 0, "reactions_received": 0, "first": None, "last": None}
    )
    forwarded = edited = with_links = 0

    for m in msgs:
        h, wd = m.date.hour, m.date.weekday()
        by_hour[h] += 1
        by_weekday[wd] += 1
        heatmap[wd][h] += 1
        by_day[m.date.date().isoformat()] += 1
        by_month[m.date.strftime("%Y-%m")] += 1

        words = _words(m.text)
        words_all.update(w for w in words if len(w) >= 3 and w not in STOPWORDS)
        emoji.update(_EMOJI_RE.findall(m.text))
        hashtags.update(t.lower() for t in _HASHTAG_RE.findall(m.text))
        mentions.update(x.lower() for x in _MENTION_RE.findall(m.text))
        links = _links(m)
        if links:
            with_links += 1
        domains.update(_domain(u) for u in links)
        media[MEDIA_LABELS.get(m.media_type, m.media_type)] += 1
        reactions.update(m.reactions)
        if m.text:
            lengths.append(len(m.text))
        if m.forwarded_from:
            forwarded += 1
        if m.edited:
            edited += 1

        s = per_sender[m.sender]
        s["messages"] += 1
        s["words"] += len(words)
        s["chars"] += len(m.text)
        s["media"] += 1 if m.media_type else 0
        s["replies"] += 1 if m.reply_to else 0
        s["forwards"] += 1 if m.forwarded_from else 0
        s["reactions_received"] += sum(m.reactions.values())
        s["first"] = s["first"] or m.date.isoformat()
        s["last"] = m.date.isoformat()

    busiest_day = by_day.most_common(1)[0]
    result["totals"].update(
        {
            "first_message": first.isoformat(),
            "last_message": last.isoformat(),
            "span_days": span_days,
            "active_days": len(active_days),
            "avg_per_day": round(len(msgs) / span_days, 2),
            "avg_per_active_day": round(len(msgs) / len(active_days), 2),
            "participants": len(per_sender),
            "words": sum(s["words"] for s in per_sender.values()),
            "avg_length_chars": _avg(lengths),
            "median_length_chars": statistics.median(lengths) if lengths else 0,
            "forwarded": forwarded,
            "edited": edited,
            "with_links": with_links,
            "reactions": sum(reactions.values()),
            "busiest_day": {"date": busiest_day[0], "messages": busiest_day[1]},
            "longest_streak": _streak(active_days),
        }
    )

    senders = []
    for name, s in sorted(per_sender.items(), key=lambda kv: -kv[1]["messages"]):
        senders.append(
            {
                "name": name,
                **s,
                "share": round(100 * s["messages"] / len(msgs), 1),
                "avg_words": round(s["words"] / s["messages"], 1),
            }
        )
    result["senders"] = senders[: max(top_n, 30)]

    result["activity"] = {
        "by_hour": by_hour,
        "by_weekday": dict(zip(WEEKDAYS, by_weekday)),
        "by_month": dict(sorted(by_month.items())),
        "by_day": dict(sorted(by_day.items())),
        "heatmap": heatmap,
        "peak_hour": max(range(24), key=lambda i: by_hour[i]),
        "peak_weekday": WEEKDAYS[max(range(7), key=lambda i: by_weekday[i])],
    }
    result["content"] = {
        "media": _top(media, 20),
        "top_words": _top(words_all, top_n * 2),
        "top_emoji": _top(emoji, top_n),
        "top_hashtags": _top(hashtags, top_n),
        "top_mentions": _top(mentions, top_n),
        "top_domains": _top(domains, top_n),
        "top_reactions": _top(reactions, top_n),
    }

    result["response_times"] = _response_times(msgs, reply_gap_hours)

    if any(m.views is not None for m in msgs):
        result["channel"] = _channel_stats(chat, msgs, top_n)

    return result


def _response_times(msgs: list[Message], gap_hours: float) -> dict[str, Any]:
    """Suhbatdosh almashganda javob qancha vaqtda kelgani (daqiqada)."""
    limit = gap_hours * 3600
    per: dict[str, list[float]] = defaultdict(list)
    for prev, cur in zip(msgs, msgs[1:]):
        if cur.sender == prev.sender:
            continue
        delta = (cur.date - prev.date).total_seconds()
        if 0 <= delta <= limit:
            per[cur.sender].append(delta / 60)
    out = {
        name: {"median_min": round(statistics.median(v), 1), "samples": len(v)}
        for name, v in per.items()
        if len(v) >= 3
    }
    return dict(sorted(out.items(), key=lambda kv: kv[1]["median_min"]))


def _post_summary(m: Message) -> dict[str, Any]:
    text = m.text.replace("\n", " ").strip()
    return {
        "id": m.id,
        "date": m.date.isoformat(),
        "views": m.views,
        "reactions": sum(m.reactions.values()),
        "type": MEDIA_LABELS.get(m.media_type, m.media_type),
        "text": (text[:140] + "…") if len(text) > 140 else text,
        "link": m.link,
    }


def _channel_stats(chat: Chat, msgs: list[Message], top_n: int) -> dict[str, Any]:
    viewed = [m for m in msgs if m.views is not None]
    views = [m.views for m in viewed]
    hour_views: dict[int, list[int]] = defaultdict(list)
    weekday_views: dict[int, list[int]] = defaultdict(list)
    type_views: dict[str, list[int]] = defaultdict(list)
    length_views: dict[str, list[int]] = defaultdict(list)
    er_values = []
    for m in viewed:
        hour_views[m.date.hour].append(m.views)
        weekday_views[m.date.weekday()].append(m.views)
        type_views[MEDIA_LABELS.get(m.media_type, m.media_type)].append(m.views)
        n = len(m.text)
        bucket = "0 (matnsiz)" if n == 0 else "1–200" if n <= 200 else "201–600" if n <= 600 else "600+"
        length_views[bucket].append(m.views)
        if m.views:
            er_values.append(100 * sum(m.reactions.values()) / m.views)

    def table(groups: dict, labels=None) -> list[dict[str, Any]]:
        rows = []
        for key, vals in groups.items():
            rows.append(
                {
                    "key": labels[key] if labels else key,
                    "posts": len(vals),
                    "avg_views": round(sum(vals) / len(vals)),
                    "median_views": round(statistics.median(vals)),
                }
            )
        return rows

    by_hour = sorted(table(hour_views), key=lambda r: r["key"])
    by_weekday = table(dict(sorted(weekday_views.items())), WEEKDAYS)
    reliable_hours = [r for r in by_hour if r["posts"] >= 3] or by_hour
    avg_views = round(sum(views) / len(views)) if views else 0

    # Oxirgi postlar hali ko'rishlarni yig'ayotgan bo'ladi — ularni trenddan chiqaramiz.
    now_cutoff = msgs[-1].date - timedelta(days=2)
    mature = [m for m in viewed if m.date <= now_cutoff] or viewed
    month_views: dict[str, list[int]] = defaultdict(list)
    for m in mature:
        month_views[m.date.strftime("%Y-%m")].append(m.views)

    stats = {
        "posts_with_views": len(viewed),
        "total_views": sum(views),
        "avg_views": avg_views,
        "median_views": round(statistics.median(views)) if views else 0,
        "max_views": max(views) if views else 0,
        "min_views": min(views) if views else 0,
        "avg_reaction_rate_pct": round(_avg(er_values), 2),
        "err_pct": round(100 * avg_views / chat.subscribers, 1) if chat.subscribers else None,
        "views_by_hour": by_hour,
        "views_by_weekday": by_weekday,
        "views_by_type": sorted(table(type_views), key=lambda r: -r["avg_views"]),
        "views_by_length": sorted(table(length_views), key=lambda r: r["key"]),
        "views_by_month": {k: round(sum(v) / len(v)) for k, v in sorted(month_views.items())},
        "best_hour": max(reliable_hours, key=lambda r: r["avg_views"])["key"] if by_hour else None,
        "top_posts": [_post_summary(m) for m in sorted(viewed, key=lambda m: -m.views)[:top_n]],
        "worst_posts": [_post_summary(m) for m in sorted(mature, key=lambda m: m.views)[:5]],
        "top_reacted": [
            _post_summary(m)
            for m in sorted(viewed, key=lambda m: -sum(m.reactions.values()))[:top_n]
            if m.reactions
        ],
    }
    gaps = [
        (b.date - a.date).total_seconds() / 3600 for a, b in zip(msgs, msgs[1:])
    ]
    stats["avg_hours_between_posts"] = round(_avg(gaps), 1)
    stats["recommendations"] = _recommendations(stats, chat)
    return stats


def _recommendations(s: dict[str, Any], chat: Chat) -> list[str]:
    tips = []
    if s["best_hour"] is not None:
        tips.append(f"Eng ko'p ko'rilgan postlar soat {s['best_hour']:02d}:00 atrofida chiqqan — "
                    "muhim postlarni shu vaqtga rejalashtiring.")
    types = [r for r in s["views_by_type"] if r["posts"] >= 3]
    if len(types) >= 2:
        best, worst = types[0], types[-1]
        if best["avg_views"] > worst["avg_views"] * 1.15:
            tips.append(f"'{best['key']}' turidagi postlar o'rtacha {best['avg_views']} ko'rish oladi, "
                        f"'{worst['key']}' esa {worst['avg_views']} — {best['key'].lower()} ulushini oshiring.")
    if s["err_pct"] is not None:
        if s["err_pct"] < 10:
            tips.append(f"ERR {s['err_pct']}% — obunachilarning juda oz qismi postlarni ko'radi; "
                        "obunachilar sifatini (bot/nofaol) tekshiring.")
        elif s["err_pct"] >= 30:
            tips.append(f"ERR {s['err_pct']}% — auditoriya faol, bu yaxshi ko'rsatkich.")
    if s["avg_reaction_rate_pct"] < 1:
        tips.append("Reaksiyalar kam (<1% ko'rishlardan) — savol, so'rovnoma va CTA qo'shib ko'ring.")
    months = list(s["views_by_month"].values())
    if len(months) >= 3:
        change = (months[-1] - months[0]) / max(months[0], 1) * 100
        trend = "o'smoqda" if change > 10 else "pasaymoqda" if change < -10 else "barqaror"
        tips.append(f"O'rtacha ko'rishlar trendi {trend} ({change:+.0f}% birinchi oydan oxirgisigacha).")
    if s["avg_hours_between_posts"] > 72:
        tips.append("Postlar orasidagi o'rtacha vaqt 3 kundan ko'p — muntazamlik auditoriyani ushlab turadi.")
    return tips
