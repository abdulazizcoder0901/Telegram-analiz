"""Vercel serverless funksiyasi: @junior_academy dashboardi.

    /api/analyze                      → oxirgi 30 kun
    /api/analyze?preset=this_month    → shu oy (today, yesterday, 7, 14, 30, this_month, last_month, all)
    /api/analyze?month=2026-10        → tanlangan oy
    /api/analyze?from=..&to=..        → aniq sanalar
    &type=photo                       → post turi
    &refresh=1                        → hozir qaytadan yig'ish ("Yangilash"), keyin ?v=<vaqt> ga yo'naltiradi
    &v=<unix vaqt>                    → kamida shu vaqtda olingan ma'lumotni ko'rsatish
    &format=json                      → JSON
    &channel=@boshqa_kanal            → boshqa ochiq kanal
"""

from __future__ import annotations

import html
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlencode, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_analiz import admin_stats, audience, history, plan  # noqa: E402
from telegram_analiz.analyzer import analyze  # noqa: E402
from telegram_analiz.filters import (  # noqa: E402
    MONTHS_FULL,
    month_bounds,
    coverage_warning,
    filter_range,
    format_range,
    parse_filters,
    type_options,
)
from telegram_analiz.loader import ExportError  # noqa: E402
from telegram_analiz.report import (  # noqa: E402
    CSS,
    render_followers_block,
    render_plan_panel,
    render_toolbar,
    to_html,
    to_json,
)
from telegram_analiz.scraper import _build_chat, fetch_page, normalize_channel, parse_page, parse_tz  # noqa: E402

DEFAULT_CHANNEL = "junior_academy"  # sayt ochilganda shu kanal ko'rsatiladi
DEFAULT_PRESET = "this_month"  # sayt "Shu oy" bilan ochiladi
TITLE = "Junior: Telegram"
MAX_POSTS = 2500
TIME_BUDGET = 40  # soniya; Vercel funksiyasi 60 soniyada to'xtatiladi
ADMIN_TIMEOUT = 25  # Telegram admin statistikasi (postlar bilan parallel)
SLOT = 1200  # ma'lumot har 20 daqiqada (:00, :20, :40) yangilanadi
ACTION = "/api/analyze"

# (kanal, tz) → {"fetched": epoch, "posts": {id: Message}, "info": dict, "complete": bool}
_CACHE: dict[tuple[str, str], dict] = {}
# kanal → {"fetched": epoch, "raw": dict|None, "series": {date: row}, "error": str|None}
_ADMIN: dict[str, dict] = {}


def admin_configured(env=None) -> bool:
    env = os.environ if env is None else env
    return all(env.get(k) for k in ("TG_API_ID", "TG_API_HASH", "TG_SESSION"))


def fetch_admin(channel: str) -> dict:
    """Telegram admin statistikasi (Vercel muhitidagi TG_* kalitlari bilan)."""
    return admin_stats.fetch_stats("@" + channel, int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"],
                                   os.environ["TG_SESSION"], timeout=ADMIN_TIMEOUT)


def admin_data(channel: str, min_fetched: float) -> dict | None:
    """Admin statistikasi + saqlangan tarix. Sozlanmagan bo'lsa None."""
    if not admin_configured():
        return None
    entry = _ADMIN.get(channel)
    if entry and entry["fetched"] >= min_fetched:
        return entry
    store = history.store_from_env()
    stored: dict = {}
    store_error = None
    if store:
        try:
            stored = store.load(channel)
        except Exception as exc:  # noqa: BLE001
            store_error = f"Tarixni o'qib bo'lmadi: {exc}"
    try:
        raw = fetch_admin(channel)
        fresh = admin_stats.daily_series(raw)
        if store:
            try:
                store.save(channel, fresh)
            except Exception as exc:  # noqa: BLE001
                store_error = f"Tarixni saqlab bo'lmadi: {exc}"
        entry = {"fetched": time.time(), "raw": raw, "series": history.merge(stored, fresh),
                 "error": store_error, "stored": bool(store)}
        print(f"[admin] ok: telegram {len(fresh)} kun, saqlangan {len(stored)} kun, "
              f"obunachilar {(raw.get('followers') or {}).get('current')}, baza {'bor' if store else 'yoq'}"
              + (f", baza xatosi: {store_error}" if store_error else ""), flush=True)
    except Exception as exc:  # noqa: BLE001 — statistika xatosi dashboardni to'xtatmasin
        previous = entry or {}
        entry = {"fetched": time.time(), "raw": previous.get("raw"),
                 "series": history.merge(stored, previous.get("series") or {}),
                 "error": f"Telegram statistikasini olib bo'lmadi: {exc}", "stored": bool(store)}
        print(f"[admin] xato: {type(exc).__name__}: {exc}", flush=True)
    # Obunachilar jurnali (qo'shilish/chiqish vaqtlari) — yangi/eski auditoriyani ajratish uchun.
    entry.setdefault("members", previous_members(channel))
    if store:
        log = history.MemberLog(store)
        try:
            events = (entry.get("raw") or {}).get("member_events") or []
            if entry.get("raw") is not None and "member_events" in entry["raw"]:
                log.record(channel, events, datetime.now(timezone.utc).isoformat(timespec="seconds"))
            members, since = log.load(channel)
            entry["members"] = {"rows": members, "since": since}
        except Exception as exc:  # noqa: BLE001
            print(f"[members] xato: {type(exc).__name__}: {exc}", flush=True)
    _ADMIN[channel] = entry
    return entry


def previous_members(channel: str) -> dict:
    return (_ADMIN.get(channel) or {}).get("members") or {"rows": {}, "since": None}




def frozen_month_start(channel: str, year: int, month: int, series: dict, today: date) -> dict | None:
    """Oy boshidagi obunachilar soni: birinchi marta hisoblanganda bazaga yoziladi va keyin o'zgarmaydi.

    Telegram eski kunlardagi jami sonni keyinroq tuzatib turadi, shuning uchun har safar qayta
    hisoblansa "oy boshida" har kuni boshqacha chiqadi.
    """
    mk = plan.month_key(year, month)
    if (year, month) > (today.year, today.month) or not series:
        return None
    base = history.store_from_env()
    store = history.JSONStore(base) if base else None
    db_key = f"tg:{channel}:month_start:{mk}"
    if store:
        try:
            saved = store.get(db_key)
            if saved and saved.get("total") is not None:
                return saved  # har safar bazadan: qo'lda tuzatish darhol ko'rinadi
        except Exception as exc:  # noqa: BLE001
            print(f"[frozen] o'qib bo'lmadi: {exc}", flush=True)
    try:
        computed = admin_stats.month_summary(series, *month_bounds(year, month))["start_total"]
    except ExportError:
        return None
    if computed is None:
        return None
    value = {"total": computed, "recorded": today.isoformat()}
    if not store:
        return None  # bazasiz qotirib bo'lmaydi — Telegram'ning joriy hisobi ishlatiladi
    try:
        if not store.set_once(db_key, value):
            value = store.get(db_key) or value  # boshqa so'rov oldinroq yozib ulgurgan
        print(f"[frozen] {channel} {mk}: oy boshida {value['total']}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[frozen] yozib bo'lmadi: {exc}", flush=True)
        return None
    return value


def with_frozen_start(summary: dict | None, channel: str, start: date | None, series: dict, today: date) -> dict | None:
    """Davr oyning 1-kunidan boshlansa, "oy boshida" qotirilgan qiymat bilan almashtiriladi."""
    if summary is None or start is None or start.day != 1:
        return summary
    frozen = frozen_month_start(channel, start.year, start.month, series, today)
    if not frozen:
        return summary
    return admin_stats.apply_start(summary, frozen["total"], frozen.get("recorded"), bool(frozen.get("manual")))


def followers_section(entry: dict | None, start: date | None, end: date | None, tz,
                      channel: str = DEFAULT_CHANNEL, today: date | None = None) -> tuple[str, dict | None]:
    if entry is None:
        return render_followers_block(summary=None, raw=None, configured=False), None
    series = entry["series"]
    summary = None
    error = entry.get("error")
    if series:
        s, e = start or min(series), end or max(series)
        try:
            summary = admin_stats.month_summary(series, s, e)
        except ExportError as exc:
            error = str(exc)
        today = today or date.today()
        summary = with_frozen_start(summary, channel, s, series, today)
        # "Oy boshida" kartochkasi har doim: davr oxiri tushgan oy (masalan 7 kun tanlansa ham 1-noyabr).
        ms, me = month_bounds(e.year, e.month)
        try:
            telegram_now = admin_stats.month_summary(series, ms, me)["start_total"]
        except ExportError:
            telegram_now = None
        frozen = frozen_month_start(channel, e.year, e.month, series, today)
        month_start = {"channel": channel, "month": plan.month_key(e.year, e.month), "date": ms.isoformat(),
                       "total": (frozen or {}).get("total", telegram_now), "telegram": telegram_now,
                       "recorded": (frozen or {}).get("recorded"), "manual": bool((frozen or {}).get("manual")),
                       "frozen": frozen is not None}
    else:
        month_start = None
    sources = admin_stats.source_totals(entry["raw"] or {}, "new_followers_by_source_graph", start, end)
    members = entry.get("members") or {}
    aud = None
    if members.get("rows") or members.get("since"):
        period_start = start or (date.fromisoformat(summary["from"]) if summary else None)
        aud = audience.classify(members.get("rows") or {}, period_start, end, members.get("since"), tz)
        aud["log_by_day"] = audience.events_by_day((entry.get("raw") or {}).get("member_events") or [], tz)
        aud["log_error"] = (entry.get("raw") or {}).get("member_events_error")
        if summary is not None:
            summary = dict(summary, audience=aud)
    fetched = f"olingan {_clock(entry['fetched'], tz)}" + (" · tarix saqlanmoqda" if entry.get("stored") else "")
    block = render_followers_block(summary=summary, raw=entry["raw"], sources=sources, error=error,
                                   fetched_label=fetched, month_start=month_start)
    return block, summary


def _error_page(message: str, status: int) -> tuple[int, str, str]:
    body = (
        "<!doctype html><html lang='uz'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Xato</title><style>{CSS}</style></head><body><main>"
        f"<div class='card'><h2>Tahlil qilib bo'lmadi</h2><p>{html.escape(message)}</p>"
        "<p><a href='/'>Qaytadan urinish</a></p></div></main></body></html>"
    )
    return status, "text/html; charset=utf-8", body, {"Cache-Control": "no-store"}


def _oldest_date(entry: dict) -> date | None:
    posts = entry["posts"]
    return min(m.date for m in posts.values()).date() if posts else None


def slot_start(ts: float) -> float:
    return ts - ts % SLOT


def collect(channel: str, tz_raw: str, tz, since: date | None, min_fetched: float, deadline: float) -> dict:
    """Postlarni ``since`` sanasigacha yig'adi; keshdagi postlardan davom etadi.

    Kesh ``min_fetched`` dan oldin olingan bo'lsa (yangi 20 daqiqalik oraliq boshlangan yoki
    "Yangilash" bosilgan), hammasi Telegram'dan qaytadan yig'iladi.
    """
    key = (channel, tz_raw)
    entry = _CACHE.get(key)
    now = time.time()
    if entry is None or entry["fetched"] < min_fetched:
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


def run(query: dict[str, list[str]]) -> tuple[int, str, str, dict[str, str]]:
    """(status, content-type, body, qo'shimcha sarlavhalar)."""
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
    # Plan oyi: tanlangan oy, aks holda davr tugagan (yoki joriy) oy.
    if filters.month:
        plan_y, plan_m = filters.month
    else:
        ref = end or today
        plan_y, plan_m = ref.year, ref.month
    plan_start, plan_end = month_bounds(plan_y, plan_m)
    since = min(d for d in (start, comp[0] if comp else None, plan_start) if d) if start else None

    now = time.time()
    refresh = bool(q("refresh"))
    try:
        version = min(float(q("v") or 0), now)  # "Yangilash" bosilgan vaqt (server soatiga cheklangan)
    except ValueError:
        version = 0.0
    min_fetched = now if refresh else max(slot_start(now), version)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as pool:
        admin_future = pool.submit(admin_data, channel, min_fetched)  # postlar bilan parallel
        try:
            entry = collect(channel, tz_raw, tz, since, min_fetched, started + TIME_BUDGET)
        except ExportError as exc:
            return _error_page(str(exc), 404 if "topilmadi" in str(exc) else 502)
        admin_entry = admin_future.result()

    if refresh:
        # Yangi ma'lumot olindi: shu vaqtni "v" qilib qayta yo'naltiramiz, keyingi barcha
        # havolalar (tugmalar, oy, filtrlar) aynan shu yoki undan yangi ma'lumotni ishlatadi.
        params = {k: v[0] for k, v in query.items() if k not in ("refresh", "v") and v}
        params["v"] = str(int(entry["fetched"]))
        location = f"{ACTION}?{urlencode(params)}"
        return 302, "text/plain; charset=utf-8", "", {"Location": location, "Cache-Control": "no-store"}

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
    fetched = entry["fetched"]
    next_update = slot_start(now) + SLOT
    # CDN sahifani faqat joriy 20 daqiqalik oraliq oxirigacha saqlaydi.
    cache_headers = {"Cache-Control": f"public, max-age=0, s-maxage={max(1, int(next_update - now))}"}
    result["data"] = {"fetched_at": int(fetched), "next_update": int(next_update)}
    followers_html, followers = followers_section(admin_entry, start, end, tz, channel, today)

    # Plan bo'limi uchun shu oyning avtomatik faktlari.
    plan_posts = analyze(filter_range(chat, plan_start, plan_end), top_n=1)
    plan_followers = None
    if admin_entry and admin_entry.get("series"):
        try:
            plan_followers = with_frozen_start(
                admin_stats.month_summary(admin_entry["series"], plan_start, plan_end),
                channel, plan_start, admin_entry["series"], today)
        except ExportError:
            plan_followers = None
    plan_ctx = {
        "channel": channel,
        "month": plan.month_key(plan_y, plan_m),
        "month_label": f"{plan_y} {MONTHS_FULL[plan_m]}",
        **plan.month_progress(plan_y, plan_m, today),
        "actuals": plan.actuals_for_month(plan_posts, plan_followers),
        "admin": admin_entry is not None,
        "metrics": plan.METRICS,
        "suggested": plan.SUGGESTED,
    }
    result["plan_context"] = {k: plan_ctx[k] for k in ("month", "days_total", "days_elapsed", "actuals")}
    if followers is not None:
        result["followers"] = followers
    if q("format") == "json":
        if compare:
            result["compare"] = {k: compare.get(k) for k in ("totals", "channel")}
        return 200, "application/json; charset=utf-8", to_json(result), cache_headers

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
    meta.append(f"keyingi yangilanish <b>{_clock(next_update, tz)}</b>")

    warnings = []
    cov = coverage_warning(chat, filters, today, complete=entry["complete"])
    if cov:
        warnings.append(cov)

    base = {"tz": tz_raw}
    if channel != DEFAULT_CHANNEL:
        base["channel"] = channel
    if version:
        base["v"] = str(int(version))
    def month_href(y: int, m: int) -> str:
        return f"{ACTION}?{urlencode(base | {'month': plan.month_key(y, m)})}#plan"

    py, pm = (plan_y - 1, 12) if plan_m == 1 else (plan_y, plan_m - 1)
    ny, nm = (plan_y + 1, 1) if plan_m == 12 else (plan_y, plan_m + 1)
    plan_ctx.update(prev_href=month_href(py, pm), prev_label=MONTHS_FULL[pm],
                    next_href=month_href(ny, nm), next_label=MONTHS_FULL[nm])
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
        refresh_href=f"{ACTION}?{urlencode({k: v for k, v in current.items() if k != 'v'} | {'refresh': '1'})}",
        warnings=warnings,
        fetched_ts=int(fetched),
        next_ts=int(next_update),
    )
    page = to_html(result, top_html=toolbar, show_header=False, compare=compare, web=True,
                   main_top_html=followers_html, plan_html=render_plan_panel(plan_ctx))
    return 200, "text/html; charset=utf-8", page, cache_headers


class handler(BaseHTTPRequestHandler):  # Vercel shu nomni qidiradi
    def do_GET(self):
        status, content_type, body, headers = run(parse_qs(urlparse(self.path).query))
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)
