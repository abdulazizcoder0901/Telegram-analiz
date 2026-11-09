"""Kanal admin statistikasi: obunachilar soni, qo'shilganlar va chiqib ketganlar.

Bu ma'lumot faqat kanal adminlariga ochiq, shuning uchun Telegram akkauntingiz bilan
kirish kerak (Telethon, MTProto API). Ishlatish:

    pip install telethon
    python -m telegram_analiz.admin_stats @kanal --month 2026-10 --html obunachilar.html

API kalitlarini https://my.telegram.org → "API development tools" dan oling va
TG_API_ID / TG_API_HASH muhit o'zgaruvchilariga yozing (yoki --api-id / --api-hash).
Birinchi ishga tushirishda telefon raqam va Telegram yuborgan kod so'raladi; sessiya
``telegram_analiz.session`` fayliga saqlanadi — bu faylni hech kimga bermang.
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
import html
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .loader import ExportError
from .report import _n, _page, _table

GRAPHS = ("growth_graph", "followers_graph", "mute_graph", "new_followers_by_source_graph",
          "views_by_source_graph")


# ---------------------------------------------------------------- yig'ish (Telethon)

async def _fetch_async(client, channel: str) -> dict[str, Any]:
    from telethon import errors, functions, types

    entity = await client.get_input_entity(channel)
    request = functions.stats.GetBroadcastStatsRequest(channel=entity)
    sender = None
    try:
        try:
            stats = await client(request)
        except errors.StatsMigrateError as exc:
            # Statistika boshqa Telegram serverida (DC) saqlanadi.
            sender = await client._borrow_exported_sender(exc.dc)
            stats = await sender.send(request)

        async def call(req):
            return await (sender.send(req) if sender else client(req))

        graphs: dict[str, Any] = {}
        graph_errors: dict[str, str] = {}
        for name in GRAPHS:
            graph = getattr(stats, name, None)
            if isinstance(graph, types.StatsGraphAsync):
                graph = await call(functions.stats.LoadAsyncGraphRequest(token=graph.token))
            if isinstance(graph, types.StatsGraph):
                graphs[name] = json.loads(graph.json.data)
            elif isinstance(graph, types.StatsGraphError):
                graph_errors[name] = graph.error
    finally:
        if sender is not None:
            await client._return_exported_sender(sender)

    def abs_value(v):
        return {"current": v.current, "previous": v.previous} if v is not None else None

    def percent(v):
        return {"part": v.part, "total": v.total} if v is not None else None

    return {
        "channel": channel,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "period": {"min": stats.period.min_date.isoformat(), "max": stats.period.max_date.isoformat()},
        "followers": abs_value(stats.followers),
        "views_per_post": abs_value(stats.views_per_post),
        "shares_per_post": abs_value(getattr(stats, "shares_per_post", None)),
        "reactions_per_post": abs_value(getattr(stats, "reactions_per_post", None)),
        "enabled_notifications": percent(stats.enabled_notifications),
        "graphs": graphs,
        "graph_errors": graph_errors,
    }


def fetch_stats(channel: str, api_id: int, api_hash: str, session: str = "telegram_analiz",
                timeout: float | None = None) -> dict[str, Any]:
    """``session`` — sessiya fayli nomi yoki ``make_session`` bergan matnli kalit (StringSession)."""
    try:
        from telethon import TelegramClient, errors
        from telethon.sessions import StringSession
    except ImportError as exc:
        raise ExportError("Telethon o'rnatilmagan. Avval: pip install telethon") from exc

    is_string = len(session) > 80 and "/" not in session and not session.endswith(".session")
    session_obj = StringSession(session) if is_string else session

    async def main():
        client = TelegramClient(session_obj, api_id, api_hash)
        if is_string:
            # Serverda (Vercel) login so'rab bo'lmaydi: sessiya yaroqsiz bo'lsa — aniq xato.
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                raise ExportError("Telegram sessiyasi yaroqsiz yoki bekor qilingan. "
                                  "make_session bilan yangi TG_SESSION yarating.")
        else:
            await client.start()  # birinchi marta telefon raqam va kod so'raydi
        async with client:
            try:
                return await _fetch_async(client, channel)
            except errors.ChatAdminRequiredError as exc:
                raise ExportError(
                    "Statistika yopiq: akkauntingiz bu kanalda admin emas yoki kanalda statistika "
                    "hali ochilmagan (obunachilar kam)."
                ) from exc
            except errors.BroadcastRequiredError as exc:
                raise ExportError("Bu kanal emas (guruh). Hozircha faqat kanallar qo'llab-quvvatlanadi.") from exc

    async def bounded():
        return await (asyncio.wait_for(main(), timeout) if timeout else main())

    try:
        return asyncio.run(bounded())
    except asyncio.TimeoutError as exc:
        raise ExportError("Telegram statistikasi vaqtida javob bermadi.") from exc


# ---------------------------------------------------------------- hisoblash

def _columns(graph: dict[str, Any]) -> tuple[list[date], dict[str, list[float]], dict[str, str]]:
    cols = {c[0]: c[1:] for c in graph.get("columns", []) if c}
    xs = cols.pop("x", [])
    days = [datetime.fromtimestamp(int(x) / 1000, tz=timezone.utc).date() for x in xs]
    names = {k: str(v) for k, v in (graph.get("names") or {}).items()}
    return days, cols, names


def _pick(cols: dict[str, list], names: dict[str, str], words: tuple[str, ...], fallback_index: int) -> list | None:
    for key, name in names.items():
        if any(w in name.lower() for w in words) and key in cols:
            return cols[key]
    keys = sorted(cols)
    return cols[keys[fallback_index]] if len(keys) > fallback_index else None


def daily_series(raw: dict[str, Any]) -> dict[date, dict[str, float | None]]:
    """{kun: {"total": jami obunachi, "joined": qo'shildi, "left": chiqib ketdi}}"""
    series: dict[date, dict[str, float | None]] = {}
    graphs = raw.get("graphs", {})

    growth = graphs.get("growth_graph")
    if growth:
        days, cols, names = _columns(growth)
        totals = _pick(cols, names, ("total", "follower", "subscriber", "member"), 0) or []
        for d, v in zip(days, totals):
            series.setdefault(d, {"total": None, "joined": None, "left": None})["total"] = v

    followers = graphs.get("followers_graph")
    if followers:
        days, cols, names = _columns(followers)
        joined = _pick(cols, names, ("join", "new", "qo'shil"), 0) or []
        left = _pick(cols, names, ("left", "leave", "unsub", "chiq"), 1) or []
        for d, v in zip(days, joined):
            series.setdefault(d, {"total": None, "joined": None, "left": None})["joined"] = v
        for d, v in zip(days, left):
            series.setdefault(d, {"total": None, "joined": None, "left": None})["left"] = v

    return dict(sorted(series.items()))


def source_totals(raw: dict[str, Any], graph_name: str, start: date | None, end: date | None) -> list[tuple[str, float]]:
    """Manba grafigidagi (masalan new_followers_by_source_graph) har bir manba yig'indisi."""
    graph = (raw.get("graphs") or {}).get(graph_name)
    if not graph:
        return []
    days, cols, names = _columns(graph)
    totals = []
    for key, values in cols.items():
        total = sum(v or 0 for d, v in zip(days, values) if (not start or d >= start) and (not end or d <= end))
        if total:
            totals.append((names.get(key, key), total))
    return sorted(totals, key=lambda kv: -kv[1])


def series_to_json(series: dict[date, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {d.isoformat(): v for d, v in series.items()}


def series_from_json(data: dict[str, dict[str, Any]]) -> dict[date, dict[str, Any]]:
    out = {}
    for k, v in (data or {}).items():
        try:
            out[date.fromisoformat(k)] = {"total": v.get("total"), "joined": v.get("joined"), "left": v.get("left")}
        except (ValueError, AttributeError):
            continue
    return dict(sorted(out.items()))


def parse_month(value: str | None, today: date | None = None) -> tuple[date, date]:
    """'2026-10' → (2026-10-01, 2026-10-31). Bo'sh bo'lsa — o'tgan oy."""
    today = today or date.today()
    if not value:
        last = today.replace(day=1) - timedelta(days=1)
        year, month = last.year, last.month
    else:
        try:
            year, month = (int(x) for x in value.split("-")[:2])
            date(year, month, 1)
        except (ValueError, TypeError) as exc:
            raise ExportError(f"Oy formati noto'g'ri: {value!r} (masalan 2026-10)") from exc
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def month_summary(series: dict[date, dict[str, Any]], start: date, end: date) -> dict[str, Any]:
    if not series:
        raise ExportError("Statistikada kunlik ma'lumot yo'q.")
    days = [d for d in series if start <= d <= end]
    first_avail, last_avail = min(series), max(series)
    if not days:
        raise ExportError(
            f"{start:%Y-%m} uchun ma'lumot yo'q. Telegram statistikasi {first_avail} — {last_avail} "
            "oralig'ini qaytardi."
        )

    rows = []
    for d in days:
        v = series[d]
        j, lft = v.get("joined"), v.get("left")
        rows.append({
            "date": d.isoformat(),
            "total": v.get("total"),
            "joined": j,
            "left": lft,
            "net": (j - lft) if j is not None and lft is not None else None,
        })

    joined = sum(r["joined"] or 0 for r in rows)
    left = sum(r["left"] or 0 for r in rows)

    # Oy boshidagi son = oldingi oyning oxirgi kunidagi jami. Bo'lmasa, birinchi kundan hisoblaymiz.
    before = [d for d in series if d < start and series[d].get("total") is not None]
    start_estimated = False
    if before and (start - max(before)).days <= 1:
        start_total = series[max(before)]["total"]
    else:
        first = rows[0]
        start_total = None
        if first["total"] is not None:
            start_total = first["total"] - (first["net"] or 0)
            start_estimated = True
    end_rows = [r for r in rows if r["total"] is not None]
    end_total = end_rows[-1]["total"] if end_rows else None

    complete = days[0] == start and days[-1] == end
    expected_end = (start_total + joined - left) if start_total is not None else None
    peak_join = max(rows, key=lambda r: r["joined"] or 0)
    peak_left = max(rows, key=lambda r: r["left"] or 0)

    return {
        "month": f"{start:%Y-%m}",
        "from": days[0].isoformat(),
        "to": days[-1].isoformat(),
        "complete": complete,
        "start_total": start_total,
        "start_estimated": start_estimated,
        "end_total": end_total,
        "joined": joined,
        "left": left,
        "net": joined - left,
        "total_change": (end_total - start_total) if end_total is not None and start_total is not None else None,
        "mismatch": (end_total - expected_end) if end_total is not None and expected_end is not None else None,
        "churn_pct": round(100 * left / start_total, 2) if start_total else None,
        "growth_pct": round(100 * (end_total - start_total) / start_total, 2)
        if start_total and end_total is not None else None,
        "peak_join_day": {"date": peak_join["date"], "joined": peak_join["joined"]},
        "peak_left_day": {"date": peak_left["date"], "left": peak_left["left"]},
        "available": {"from": first_avail.isoformat(), "to": last_avail.isoformat()},
        "days": rows,
    }


def apply_start(summary: dict[str, Any], start_total: float | None, recorded_on: str | None = None) -> dict[str, Any]:
    """Oy boshidagi sonni qotirilgan qiymat bilan almashtirib, unga bog'liq ko'rsatkichlarni qayta hisoblaydi."""
    if start_total is None:
        return summary
    s = dict(summary)
    end_total, joined, left = s.get("end_total"), s.get("joined") or 0, s.get("left") or 0
    s["start_total"] = start_total
    s["start_estimated"] = False
    s["start_frozen_on"] = recorded_on
    s["total_change"] = (end_total - start_total) if end_total is not None else None
    s["mismatch"] = (end_total - (start_total + joined - left)) if end_total is not None else None
    s["churn_pct"] = round(100 * left / start_total, 2) if start_total else None
    s["growth_pct"] = round(100 * (end_total - start_total) / start_total, 2) if start_total and end_total is not None else None
    return s


# ---------------------------------------------------------------- hisobot

def _svg_diverging(labels: list[str], up: list[float], down: list[float], height: int = 220) -> str:
    n = len(labels)
    if not n:
        return ""
    width = max(640, n * 22)
    mx = max(max(up, default=0), max(down, default=0)) or 1
    top, bottom = 14, 24
    half = (height - top - bottom) / 2
    mid = top + half
    bw = width / n
    bar = min(bw * 0.7, 30)
    out = [f'<svg viewBox="-52 0 {width + 68} {height}" class="chart div" role="img">',
           f'<line x1="0" x2="{width}" y1="{mid}" y2="{mid}" class="axis"/>']
    step = 1 if n <= 16 else -(-n // 10)
    for i, (lab, u, d) in enumerate(zip(labels, up, down)):
        x = i * bw + (bw - bar) / 2
        hu, hd = half * u / mx, half * d / mx
        out.append(f'<rect class="up" x="{x:.1f}" y="{mid - hu:.1f}" width="{bar:.1f}" height="{hu:.1f}" rx="2">'
                   f'<title>{html.escape(lab)}: +{_n(u)}</title></rect>')
        out.append(f'<rect class="down" x="{x:.1f}" y="{mid:.1f}" width="{bar:.1f}" height="{hd:.1f}" rx="2">'
                   f'<title>{html.escape(lab)}: −{_n(d)}</title></rect>')
        if i % step == 0:
            out.append(f'<text x="{i * bw + bw / 2:.1f}" y="{height - 6}" class="lbl">{html.escape(lab)}</text>')
    out.append(f'<text x="-8" y="{top + 8}" class="lbl end">+{_n(mx)}</text>')
    out.append(f'<text x="-8" y="{mid + 3}" class="lbl end">0</text>')
    out.append(f'<text x="-8" y="{height - bottom}" class="lbl end">−{_n(mx)}</text>')
    out.append("</svg>")
    return "".join(out)


def _svg_line(labels: list[str], values: list[float], height: int = 200) -> str:
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return ""
    n = len(labels)
    width = max(640, n * 22)
    lo, hi = min(v for _, v in pts), max(v for _, v in pts)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    pad = (hi - lo) * 0.1
    lo, hi = lo - pad, hi + pad
    top, bottom = 14, 24
    inner = height - top - bottom
    bw = width / n

    def xy(i, v):
        return i * bw + bw / 2, top + inner * (1 - (v - lo) / (hi - lo))

    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(i, v) for i, v in pts))
    x0, _ = xy(pts[0][0], pts[0][1])
    x1, y1 = xy(pts[-1][0], pts[-1][1])
    area = f"{x0:.1f},{top + inner} {line} {x1:.1f},{top + inner}"
    out = [f'<svg viewBox="-52 0 {width + 68} {height}" class="chart line" role="img">']
    for frac in (0, 0.5, 1):
        y = top + inner * frac
        val = hi - (hi - lo) * frac
        out.append(f'<line x1="0" x2="{width}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                   f'<text x="-8" y="{y + 3:.1f}" class="lbl end">{_n(round(val))}</text>')
    out.append(f'<polygon points="{area}" class="area"/><polyline points="{line}" class="stroke"/>')
    out.append(f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="4" class="dot"><title>{_n(pts[-1][1])}</title></circle>')
    step = 1 if n <= 16 else -(-n // 10)
    for i, lab in enumerate(labels):
        if i % step == 0:
            out.append(f'<text x="{i * bw + bw / 2:.1f}" y="{height - 6}" class="lbl">{html.escape(lab)}</text>')
    out.append("</svg>")
    return "".join(out)


EXTRA_CSS = """
:root{--up:#1f8a5b;--down:#c8463b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--up:#4cc38a;--down:#ef7a6f}}
:root[data-theme="dark"]{--up:#4cc38a;--down:#ef7a6f}
.chart.div rect.up{fill:var(--up)}.chart.div rect.down{fill:var(--down)}
.chart .axis{stroke:var(--line);stroke-width:1}.chart .grid{stroke:var(--line);stroke-dasharray:3 4}
.chart.line .stroke{fill:none;stroke:var(--accent);stroke-width:2.5;stroke-linejoin:round}
.chart.line .area{fill:var(--accent);fill-opacity:.12}.chart.line .dot{fill:var(--accent)}
.kpi .v.up{color:var(--up)}.kpi .v.down{color:var(--down)}
.legend{display:flex;gap:16px;font-size:13px;color:var(--muted);margin:0 0 8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
"""

MONTHS_UZ = ["", "yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust",
             "sentabr", "oktabr", "noyabr", "dekabr"]


def _signed(v: float | None) -> str:
    if v is None:
        return "—"
    return ("+" if v > 0 else "−" if v < 0 else "") + _n(abs(int(v)))


def to_html(raw: dict[str, Any], s: dict[str, Any]) -> str:
    esc = html.escape
    y, m = (int(x) for x in s["month"].split("-"))
    month_name = f"{y}-yil {MONTHS_UZ[m]}"
    title = f"{raw.get('channel', 'Kanal')} obunachilari"
    body = [f"<h1>{esc(raw.get('channel', ''))}: {month_name}</h1>",
            f"<div class='muted'>Obunachilar dinamikasi · Telegram admin statistikasi · "
            f"{s['from']} — {s['to']}</div>"]
    kpis = [
        ("Oy boshida", _n(int(s["start_total"])) if s["start_total"] is not None else "—", ""),
        ("Oy oxirida", _n(int(s["end_total"])) if s["end_total"] is not None else "—", ""),
        ("Qo'shildi", "+" + _n(int(s["joined"])), "up"),
        ("Chiqib ketdi", "−" + _n(int(s["left"])), "down"),
        ("Sof o'zgarish", _signed(s["total_change"] if s["total_change"] is not None else s["net"]),
         "up" if (s["total_change"] or s["net"]) > 0 else "down"),
        ("Chiqib ketish", f"{s['churn_pct']}%" if s["churn_pct"] is not None else "—", ""),
    ]
    body.append("<div class='grid'>" + "".join(
        f"<div class='kpi'><div class='k'>{esc(k)}</div><div class='v {c}'>{esc(v)}</div></div>" for k, v, c in kpis
    ) + "</div>")

    notes = []
    if not s["complete"]:
        notes.append(f"Statistika oyning faqat {s['from']} — {s['to']} kunlarini qamraydi.")
    if s["start_estimated"]:
        notes.append("Oy boshidagi son birinchi kun ma'lumotidan hisoblangan.")
    if s["mismatch"]:
        notes.append(f"Telegram'ning jami soni bilan qo'shilgan−chiqqan yig'indisi orasida {_signed(s['mismatch'])} "
                     "farq bor (o'chirilgan akkauntlar va Telegram yaxlitlashi sabab bo'lishi mumkin).")
    body.append(
        "<div class='card'><h2>Xulosa</h2><ul class='tips-list'>"
        f"<li>Oy boshida <b>{_n(int(s['start_total'])) if s['start_total'] is not None else '—'}</b> obunachi bo'lgan, "
        f"oy oxirida <b>{_n(int(s['end_total'])) if s['end_total'] is not None else '—'}</b>.</li>"
        f"<li>{_n(int(s['joined']))} kishi qo'shildi, {_n(int(s['left']))} kishi chiqib ketdi.</li>"
        f"<li>Eng ko'p qo'shilgan kun: {s['peak_join_day']['date']} (+{_n(int(s['peak_join_day']['joined'] or 0))}). "
        f"Eng ko'p chiqib ketgan kun: {s['peak_left_day']['date']} (−{_n(int(s['peak_left_day']['left'] or 0))}).</li>"
        + "".join(f"<li class='muted'>{esc(n)}</li>" for n in notes) + "</ul></div>"
    )
    labels = [r["date"][8:10] for r in s["days"]]
    body.append(
        "<div class='card'><h2>Kunlik qo'shilgan va chiqib ketganlar</h2>"
        "<div class='legend'><span><i style='background:var(--up)'></i>Qo'shildi</span>"
        "<span><i style='background:var(--down)'></i>Chiqib ketdi</span></div>"
        + _svg_diverging(labels, [r["joined"] or 0 for r in s["days"]], [r["left"] or 0 for r in s["days"]])
        + "</div>"
    )
    line = _svg_line(labels, [r["total"] for r in s["days"]])
    if line:
        body.append("<div class='card'><h2>Jami obunachilar</h2>" + line + "</div>")
    body.append("<div class='card'><h2>Kunlar bo'yicha</h2>" + _table(
        ["Sana", "Jami", "Qo'shildi", "Chiqdi", "Sof"],
        [[r["date"], int(r["total"]) if r["total"] is not None else "—",
          int(r["joined"]) if r["joined"] is not None else "—",
          int(r["left"]) if r["left"] is not None else "—",
          _signed(r["net"])] for r in s["days"]]) + "</div>")
    if raw.get("enabled_notifications"):
        en = raw["enabled_notifications"]
        if en.get("total"):
            body.append(f"<p class='muted'>Bildirishnomasi yoqilgan obunachilar: "
                        f"{100 * en['part'] / en['total']:.1f}%.</p>")
    page = _page(title, body)
    return page.replace("</style>", EXTRA_CSS + "</style>", 1)


def to_text(raw: dict[str, Any], s: dict[str, Any]) -> str:
    def num(v):
        return _n(int(v)) if v is not None else "—"

    lines = [
        f"{raw.get('channel', '')} — {s['month']} ({s['from']} — {s['to']})",
        f"  Oy boshida:     {num(s['start_total'])}{' (hisoblangan)' if s['start_estimated'] else ''}",
        f"  Oy oxirida:     {num(s['end_total'])}",
        f"  Qo'shildi:      +{num(s['joined'])}",
        f"  Chiqib ketdi:   −{num(s['left'])}",
        f"  Sof o'zgarish:  {_signed(s['total_change'] if s['total_change'] is not None else s['net'])}",
        f"  Chiqib ketish:  {s['churn_pct']}% (oy boshidagi obunachilardan)",
        f"  Eng ko'p qo'shilgan kun: {s['peak_join_day']['date']} (+{num(s['peak_join_day']['joined'])})",
        f"  Eng ko'p chiqqan kun:    {s['peak_left_day']['date']} (−{num(s['peak_left_day']['left'])})",
    ]
    if not s["complete"]:
        lines.append(f"  Diqqat: statistika oyning faqat {s['from']} — {s['to']} kunlarini qamraydi.")
    return "\n".join(lines)


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m telegram_analiz.admin_stats",
        description="Kanal obunachilari: oy boshida/oxirida nechta, qancha qo'shildi va chiqib ketdi (admin uchun).",
    )
    p.add_argument("channel", nargs="?", help="@kanal (siz admin bo'lgan)")
    p.add_argument("--month", help="oy, masalan 2026-10 (standart: o'tgan oy)")
    p.add_argument("--api-id", type=int, default=int(os.environ.get("TG_API_ID", "0") or 0))
    p.add_argument("--api-hash", default=os.environ.get("TG_API_HASH", ""))
    p.add_argument("--session", default="telegram_analiz", help="sessiya fayli nomi")
    p.add_argument("--save-json", metavar="FAYL", help="Telegram'dan olingan xom statistikani saqlash")
    p.add_argument("--from-json", metavar="FAYL", help="avval saqlangan statistikadan (login qilmasdan)")
    p.add_argument("--html", metavar="FAYL", help="HTML hisobot")
    p.add_argument("--json", metavar="FAYL", help="oy xulosasini JSON qilib saqlash")
    args = p.parse_args(argv)

    try:
        if args.from_json:
            raw = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        else:
            if not args.channel:
                p.error("kanal nomini kiriting yoki --from-json bering")
            if not args.api_id or not args.api_hash:
                p.error("API kalitlari kerak: --api-id va --api-hash (yoki TG_API_ID / TG_API_HASH). "
                        "Ularni https://my.telegram.org dan oling.")
            from .scraper import normalize_channel

            raw = fetch_stats("@" + normalize_channel(args.channel), args.api_id, args.api_hash, args.session)
            if args.save_json:
                Path(args.save_json).write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"Xom statistika: {args.save_json}", file=sys.stderr)
        start, end = parse_month(args.month)
        summary = month_summary(daily_series(raw), start, end)
    except ExportError as exc:
        print(f"Xato: {exc}", file=sys.stderr)
        return 1

    print(to_text(raw, summary))
    if args.html:
        Path(args.html).write_text(to_html(raw, summary), encoding="utf-8")
        print(f"HTML hisobot: {args.html}", file=sys.stderr)
    if args.json:
        Path(args.json).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
