"""Natijani konsol, HTML va JSON ko'rinishida chiqarish."""

from __future__ import annotations

import html
import json
from typing import Any

from .analyzer import WEEKDAYS


def _n(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.1f}".replace(",", " ")
    if isinstance(value, int):
        return f"{value:,}".replace(",", " ")
    return str(value)


# ---------------------------------------------------------------- konsol

def _bar(value: float, maximum: float, width: int = 30) -> str:
    if maximum <= 0:
        return ""
    return "█" * max(1 if value else 0, round(width * value / maximum))


def to_text(r: dict[str, Any], top_n: int = 10) -> str:
    out: list[str] = []
    add = out.append
    c, t = r["chat"], r["totals"]
    title = c["name"] + (f" (@{c['username']})" if c.get("username") else "")
    add("=" * 64)
    add(f" TELEGRAM TAHLIL: {title}")
    add("=" * 64)
    if c.get("description"):
        add(f"Tavsif: {c['description'][:300]}")
    if c.get("subscribers"):
        add(f"Obunachilar: {_n(c['subscribers'])}")
    if not t.get("messages"):
        add("Xabarlar topilmadi.")
        return "\n".join(out)

    add("")
    add("UMUMIY")
    add(f"  Xabarlar/postlar:      {_n(t['messages'])}")
    add(f"  Davr:                  {t['first_message'][:10]} — {t['last_message'][:10]} ({t['span_days']} kun)")
    add(f"  Faol kunlar:           {t['active_days']}  (kuniga o'rtacha {t['avg_per_day']})")
    add(f"  Eng faol kun:          {t['busiest_day']['date']} ({t['busiest_day']['messages']} ta)")
    add(f"  Eng uzun ketma-ketlik: {t['longest_streak']['days']} kun")
    add(f"  O'rtacha uzunlik:      {t['avg_length_chars']} belgi")
    add(f"  Havolali / forward:    {t['with_links']} / {t['forwarded']}")
    add(f"  Reaksiyalar jami:      {_n(t['reactions'])}")

    ch = r.get("channel")
    if ch:
        add("")
        add("KANAL KO'RSATKICHLARI")
        add(f"  Ko'rishlar jami:       {_n(ch['total_views'])}")
        add(f"  O'rtacha / mediana:    {_n(ch['avg_views'])} / {_n(ch['median_views'])}")
        add(f"  Maks / min:            {_n(ch['max_views'])} / {_n(ch['min_views'])}")
        if ch["err_pct"] is not None:
            add(f"  ERR (ko'rish/obunachi): {ch['err_pct']}%")
        add(f"  Reaksiya darajasi:     {ch['avg_reaction_rate_pct']}% ko'rishlardan")
        rec = ch.get("recent_30d") or {}
        if rec.get("posts"):
            add(f"  Oxirgi 30 kun:         {rec['posts']} post, o'rtacha {_n(rec['avg_views'])} ko'rish"
                + (f", ERR {rec['err_pct']}%" if rec.get("err_pct") is not None else ""))
        add(f"  Postlar oralig'i:      ~{ch['avg_hours_between_posts']} soat")
        if ch["best_hour"] is not None:
            add(f"  Eng yaxshi soat:       {ch['best_hour']:02d}:00")
        add("")
        add("  Post turi bo'yicha o'rtacha ko'rish:")
        mx = max((x["avg_views"] for x in ch["views_by_type"]), default=0)
        for row in ch["views_by_type"]:
            add(f"    {row['key'][:18]:<18} {row['posts']:>4} ta  {_n(row['avg_views']):>8}  {_bar(row['avg_views'], mx, 20)}")
        add("")
        add(f"  TOP-{min(top_n, len(ch['top_posts']))} post (ko'rish bo'yicha):")
        for p in ch["top_posts"][:top_n]:
            add(f"    {_n(p['views']):>8} 👁  {p['date'][:10]}  {p['text'][:60] or '[' + p['type'] + ']'}")
        if ch["recommendations"]:
            add("")
            add("TAVSIYALAR")
            for tip in ch["recommendations"]:
                add(f"  • {tip}")

    senders = r.get("senders", [])
    if len(senders) > 1:
        add("")
        add("MUALLIFLAR (imzo bo'yicha)" if ch else "ISHTIROKCHILAR")
        mx = senders[0]["messages"]
        for s in senders[:top_n]:
            add(f"  {s['name'][:20]:<20} {s['messages']:>6} ({s['share']:>4}%) {_bar(s['messages'], mx, 24)}")

    a = r["activity"]
    add("")
    add("SOATLAR BO'YICHA FAOLLIK")
    mx = max(a["by_hour"])
    for h, v in enumerate(a["by_hour"]):
        add(f"  {h:02d}:00 {v:>6} {_bar(v, mx)}")
    add("")
    add("HAFTA KUNLARI")
    mx = max(a["by_weekday"].values())
    for day, v in a["by_weekday"].items():
        add(f"  {day:<10} {v:>6} {_bar(v, mx)}")

    cn = r["content"]
    for key, label in [
        ("media", "KONTENT TURLARI"),
        ("top_words", "KO'P ISHLATILGAN SO'ZLAR"),
        ("top_hashtags", "HESHTEGLAR"),
        ("top_mentions", "ESLATMALAR (@)"),
        ("top_domains", "HAVOLA DOMENLARI"),
        ("top_emoji", "EMOJI"),
        ("top_reactions", "REAKSIYALAR"),
    ]:
        items = cn.get(key) or []
        if not items:
            continue
        add("")
        add(label)
        add("  " + ", ".join(f"{k} ({v})" for k, v in items[: top_n * (2 if key == 'top_words' else 1)]))

    rt = r.get("response_times") or {}
    if len(senders) > 1 and rt and not ch:
        add("")
        add("JAVOB TEZLIGI (mediana, daqiqa)")
        for name, v in list(rt.items())[:top_n]:
            add(f"  {name[:20]:<20} {v['median_min']:>7} daq  ({v['samples']} marta)")
    return "\n".join(out)


# ---------------------------------------------------------------- HTML

def _svg_bars(labels: list[str], values: list[float], height: int = 180, fmt=_n, weak: set[int] | None = None) -> str:
    if not values:
        return ""
    n = len(values)
    width = max(640, n * 28)
    mx = max(values) or 1
    bw = width / n
    bar_w = min(bw * 0.7, 44)
    pad_top, pad_bottom = 18, 22
    inner = height - pad_top - pad_bottom
    parts = [f'<svg viewBox="-16 0 {width + 32} {height}" class="chart" role="img">']
    step = 1 if n <= 24 else -(-n // 10)  # ko'p ustunda har k-chi yozuv
    for i, (lab, v) in enumerate(zip(labels, values)):
        h = inner * v / mx
        x = i * bw + (bw - bar_w) / 2
        y = pad_top + inner - h
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="2"'
            f'{" class=\"weak\"" if weak and i in weak else ""}>'
            f"<title>{html.escape(str(lab))}: {fmt(v)}</title></rect>"
        )
        if i % step == 0:
            parts.append(
                f'<text x="{i * bw + bw / 2:.1f}" y="{height - 6}" class="lbl">{html.escape(str(lab))}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _svg_heatmap(grid: list[list[int]]) -> str:
    mx = max(max(row) for row in grid) or 1
    cell, left, top = 22, 84, 18
    w, h = left + 24 * cell, top + 7 * cell + 4
    parts = [f'<svg viewBox="0 0 {w} {h}" class="chart heat" role="img">']
    for hr in range(0, 24, 3):
        parts.append(f'<text x="{left + hr * cell + cell / 2}" y="12" class="lbl">{hr:02d}</text>')
    for d, row in enumerate(grid):
        parts.append(f'<text x="{left - 6}" y="{top + d * cell + 15}" class="lbl end">{WEEKDAYS[d]}</text>')
        for hr, v in enumerate(row):
            op = 0.06 + 0.94 * (v / mx)
            parts.append(
                f'<rect x="{left + hr * cell}" y="{top + d * cell}" width="{cell - 2}" height="{cell - 2}" '
                f'rx="3" style="fill-opacity:{op:.2f}"><title>{WEEKDAYS[d]} {hr:02d}:00 — {v}</title></rect>'
            )
    parts.append("</svg>")
    return "".join(parts)


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{c if str(c).startswith('<a ') else html.escape(_n(c))}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return f'<div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _chips(items: list[list[Any]]) -> str:
    return "".join(
        f'<span class="chip">{html.escape(str(k))} <b>{_n(v)}</b></span>' for k, v in items
    ) or '<span class="muted">—</span>'


def _post_rows(posts: list[dict[str, Any]]) -> list[list[Any]]:
    rows = []
    for p in posts:
        text = html.escape(p["text"] or f"[{p['type']}]")
        cell = f'<a href="{html.escape(p["link"])}" target="_blank" rel="noopener">{text}</a>' if p.get("link") else text
        rows.append([p["date"][:16].replace("T", " "), p["views"], p["reactions"], p["type"], cell])
    return rows


CSS = """
/* Layout: bir ustunli hisobot — avval KPI va tavsiyalar, keyin grafiklar, oxirida tafsilotlar. */
:root{--bg:#f4f6f9;--card:#ffffff;--fg:#17202b;--muted:#5e6b7a;--line:#dfe5ec;--accent:#2b7bd6;--chip:#e9f1fb;--good:#1f8a5b;--warn:#b7791f;
--font-body:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--font-num:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#11161d;--card:#18202a;--fg:#e6ebf1;--muted:#93a1b1;--line:#28323e;--accent:#5ea4f0;--chip:#1d2b3b;--good:#4cc38a;--warn:#e0a84a;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#11161d;--card:#18202a;--fg:#e6ebf1;--muted:#93a1b1;--line:#28323e;--accent:#5ea4f0;--chip:#1d2b3b;--good:#4cc38a;--warn:#e0a84a;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 var(--font-body)}
main{max-width:1080px;margin:0 auto;padding-block:28px 64px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
h1{font-size:28px;line-height:1.2;margin:0 0 4px;text-wrap:balance}h2{font-size:16px;margin:0 0 12px;text-wrap:balance}
.muted{color:var(--muted)}.desc{white-space:pre-line;max-width:65ch}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}
.kpi,.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;min-width:0}.card{margin:16px 0}
.kpi .v{font:600 22px/1.2 var(--font-num);font-variant-numeric:tabular-nums;margin-top:4px}.kpi .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.chart{width:100%;height:auto;display:block}.chart rect{fill:var(--accent)}.chart .lbl{font-size:10px;fill:var(--muted);text-anchor:middle}
.chart rect.weak{fill-opacity:.3}.note{font-size:13px;margin:8px 0 0}.chart .lbl.end{text-anchor:end}.heat{max-width:640px}.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:11px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.05em}
td:nth-child(2),td:nth-child(3){white-space:nowrap}
a{color:var(--accent);text-decoration:none}a:hover,a:focus-visible{text-decoration:underline}a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:3px 10px;margin:3px;font-size:13px}.chip b{font-family:var(--font-num);font-weight:600}
.tips{border-color:var(--accent)}ul.tips-list{margin:0;padding-left:20px;max-width:75ch}ul.tips-list li{margin:7px 0}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}.two .card{margin:0}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--bg)}
.filters{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:12px 14px;margin:0 0 20px;box-shadow:0 6px 18px -14px rgba(0,0,0,.35)}
.f-row{display:flex;flex-wrap:wrap;gap:10px 12px;align-items:flex-end}
.f{display:flex;flex-direction:column;gap:4px;min-width:0;flex:1 1 140px}
.f label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.f select,.f input{font:500 14px var(--font-body);padding:8px 10px;border:1px solid var(--line);border-radius:7px;background:var(--bg);color:var(--fg);width:100%;min-width:0}
.f-actions{flex:0 0 auto;flex-direction:row;align-items:center;gap:12px}
.f-actions button{font:600 14px var(--font-body);padding:9px 16px;border:0;border-radius:7px;background:var(--accent);color:var(--card);cursor:pointer}
.f-actions button[disabled]{opacity:.7;cursor:progress}
.f select:focus-visible,.f input:focus-visible,.f-actions button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.f-actions a{font-size:14px}
.f-summary{margin:10px 0 0;font-size:13px;color:var(--muted)}.f-summary b{color:var(--fg);font-family:var(--font-num)}
.f-warn{margin:8px 0 0;font-size:13px;color:var(--warn)}
@media (max-width:560px){.filters{position:static}.f{flex-basis:calc(50% - 6px)}.f-actions{flex-basis:100%}}
"""


def render_filter_bar(
    *,
    action: str,
    hidden: dict[str, str],
    filters: Any,
    today: Any,
    type_options: list[tuple[str, str, int]],
    limit: int | None = None,
    limit_choices: tuple[int, ...] = (100, 300, 600),
    shown: int | None = None,
    total: int | None = None,
    warning: str | None = None,
) -> str:
    """Hisobot tepasidagi filtrlar formasi (GET bilan serverga yuboriladi)."""
    from .filters import PERIODS

    esc = html.escape
    period_opts = "".join(
        f"<option value='{k}'{' selected' if filters.period == k else ''}>{esc(label)}</option>"
        for k, (label, _) in PERIODS.items()
    )
    selected_type = filters.types[0] if filters.types else "all"
    type_opts = f"<option value='all'{' selected' if selected_type == 'all' else ''}>Barcha turlar</option>" + "".join(
        f"<option value='{esc(k)}'{' selected' if k == selected_type else ''}>{esc(label)} ({n})</option>"
        for k, label, n in type_options
    )
    start, end = filters.bounds(today)
    fields = [
        f"<div class='f'><label for='f-period'>Davr</label><select id='f-period' name='period'>{period_opts}</select></div>",
        f"<div class='f'><label for='f-from'>Dan</label><input id='f-from' type='date' name='from' value='{start or ''}'></div>",
        f"<div class='f'><label for='f-to'>Gacha</label><input id='f-to' type='date' name='to' value='{end or ''}'></div>",
        f"<div class='f'><label for='f-type'>Post turi</label><select id='f-type' name='type'>{type_opts}</select></div>",
    ]
    if limit is not None:
        limit_opts = "".join(
            f"<option value='{n}'{' selected' if n == limit else ''}>oxirgi {n}</option>" for n in limit_choices
        )
        fields.append(
            f"<div class='f'><label for='f-limit'>Yig'iladigan postlar</label><select id='f-limit' name='limit'>{limit_opts}</select></div>"
        )
    hidden_html = "".join(f"<input type='hidden' name='{esc(k)}' value='{esc(v)}'>" for k, v in hidden.items())
    reset_q = "&".join(f"{esc(k)}={esc(v)}" for k, v in hidden.items())
    summary = ""
    if shown is not None and total is not None:
        desc = " · ".join(filters.describe(today)) or "filtrsiz"
        summary = f"<p class='f-summary'><b>{shown}</b> / {total} post · {esc(desc)}</p>"
    warn = f"<p class='f-warn'>{esc(warning)}</p>" if warning else ""
    script = (
        "<script>(function(){var f=document.getElementById('filters');if(!f)return;"
        "var p=f.querySelector('#f-period'),a=f.querySelector('#f-from'),b=f.querySelector('#f-to');"
        "p.addEventListener('change',function(){if(p.value!=='custom'){a.value='';b.value='';}f.requestSubmit();});"
        "[a,b].forEach(function(x){x.addEventListener('change',function(){p.value='custom';});});"
        "f.querySelectorAll('#f-type,#f-limit').forEach(function(x){x.addEventListener('change',function(){f.requestSubmit();});});"
        "f.addEventListener('submit',function(){if(p.value!=='custom'){a.disabled=true;b.disabled=true;}"
        "var btn=f.querySelector('button');btn.disabled=true;btn.textContent='Yuklanmoqda…';});"
        "window.addEventListener('pageshow',function(){a.disabled=false;b.disabled=false;"
        "var btn=f.querySelector('button');btn.disabled=false;btn.textContent='Qo‘llash';});})();</script>"
    )
    return (
        f"<form id='filters' class='filters' method='get' action='{esc(action)}'>{hidden_html}"
        f"<div class='f-row'>{''.join(fields)}"
        f"<div class='f f-actions'><button type='submit'>Qo‘llash</button>"
        f"<a href='{esc(action)}?{reset_q}'>Tozalash</a></div></div>{summary}{warn}</form>{script}"
    )


def to_html(r: dict[str, Any], top_html: str = "", show_header: bool = True) -> str:
    c, t = r["chat"], r["totals"]
    esc = html.escape
    title = c["name"]
    sub = f"@{c['username']}" if c.get("username") else c.get("type", "")
    body: list[str] = [top_html]
    if show_header:
        body.append(f"<h1>{esc(title)}</h1><div class='muted'>{esc(sub)}</div>")
        if c.get("description"):
            body.append(f"<p class='muted desc'>{esc(c['description'])}</p>")
    if not t.get("messages"):
        body.append("<div class='card'><h2>Postlar topilmadi</h2><p class='muted'>Tanlangan filtrlarga mos post yo'q. "
                    "Davrni kengaytiring yoki boshqa post turini tanlang.</p></div>")
        return _page(title, body)

    ch = r.get("channel")
    kpis = [("Postlar" if ch else "Xabarlar", t["messages"]),
            ("Davr (kun)", t["span_days"]), ("Kuniga o'rtacha", t["avg_per_day"])]
    if c.get("subscribers"):
        kpis.insert(0, ("Obunachilar", c["subscribers"]))
    if ch:
        kpis += [("O'rtacha ko'rish", ch["avg_views"]), ("Mediana ko'rish", ch["median_views"])]
        if ch["err_pct"] is not None:
            kpis.append(("ERR (butun davr)", f"{ch['err_pct']}%"))
        rec = ch.get("recent_30d") or {}
        if rec.get("posts"):
            kpis.append(("Ko'rish (30 kun)", rec["avg_views"]))
            if rec.get("err_pct") is not None:
                kpis.append(("ERR (30 kun)", f"{rec['err_pct']}%"))
        kpis.append(("Reaksiya darajasi", f"{ch['avg_reaction_rate_pct']}%"))
    else:
        kpis += [("Ishtirokchilar", t["participants"]), ("Reaksiyalar", t["reactions"])]
    body.append("<div class='grid'>" + "".join(
        f"<div class='kpi'><div class='k'>{esc(k)}</div><div class='v'>{esc(_n(v))}</div></div>" for k, v in kpis
    ) + "</div>")
    body.append(f"<p class='muted'>{t['first_message'][:10]} — {t['last_message'][:10]} · "
                f"eng faol kun {t['busiest_day']['date']} ({t['busiest_day']['messages']} ta)</p>")

    if ch:
        if ch["recommendations"]:
            body.append("<div class='card tips'><h2>Tavsiyalar</h2><ul class='tips-list'>" +
                        "".join(f"<li>{esc(x)}</li>" for x in ch["recommendations"]) + "</ul></div>")
        if ch["views_by_month"]:
            body.append("<div class='card'><h2>Oylar bo'yicha o'rtacha ko'rish</h2>" +
                        _svg_bars(list(ch["views_by_month"]), list(ch["views_by_month"].values())) + "</div>")
        hv = {row["key"]: row for row in ch["views_by_hour"]}
        min_posts = max(3, round(ch["posts_with_views"] * 0.02))
        weak = {h for h in range(24) if hv.get(h, {}).get("posts", 0) < min_posts}
        body.append("<div class='card'><h2>Chiqarilgan soat bo'yicha o'rtacha ko'rish</h2>" +
                    _svg_bars([f"{h:02d}" for h in range(24)], [hv.get(h, {}).get("avg_views", 0) for h in range(24)],
                              weak=weak) +
                    f"<p class='muted note'>Och rangli ustunlar: {min_posts} tadan kam post chiqqan soatlar, "
                    "ularga ishonib bo'lmaydi.</p></div>")
        body.append("<div class='two'>")
        body.append("<div class='card'><h2>Post turi bo'yicha</h2>" + _table(
            ["Tur", "Postlar", "O'rt. ko'rish", "Mediana"],
            [[x["key"], x["posts"], x["avg_views"], x["median_views"]] for x in ch["views_by_type"]]) + "</div>")
        body.append("<div class='card'><h2>Matn uzunligi bo'yicha</h2>" + _table(
            ["Belgilar", "Postlar", "O'rt. ko'rish", "Mediana"],
            [[x["key"], x["posts"], x["avg_views"], x["median_views"]] for x in ch["views_by_length"]]) + "</div>")
        body.append("</div>")
        body.append("<div class='card'><h2>Eng ko'p ko'rilgan postlar</h2>" + _table(
            ["Sana", "Ko'rish", "Reaksiya", "Tur", "Post"], _post_rows(ch["top_posts"])) + "</div>")
        if ch["top_reacted"]:
            body.append("<div class='card'><h2>Eng ko'p reaksiya olgan postlar</h2>" + _table(
                ["Sana", "Ko'rish", "Reaksiya", "Tur", "Post"], _post_rows(ch["top_reacted"][:10])) + "</div>")
        body.append("<div class='card'><h2>Eng kam ko'rilgan postlar</h2>" + _table(
            ["Sana", "Ko'rish", "Reaksiya", "Tur", "Post"], _post_rows(ch["worst_posts"])) + "</div>")

    a = r["activity"]
    body.append("<div class='card'><h2>Faollik: hafta kuni × soat</h2>" + _svg_heatmap(a["heatmap"]) + "</div>")
    body.append("<div class='two'>")
    body.append("<div class='card'><h2>Soatlar bo'yicha</h2>" +
                _svg_bars([f"{h:02d}" for h in range(24)], a["by_hour"]) + "</div>")
    body.append("<div class='card'><h2>Oylar bo'yicha</h2>" +
                _svg_bars(list(a["by_month"]), list(a["by_month"].values())) + "</div>")
    body.append("</div>")

    senders = r.get("senders", [])
    if len(senders) > 1:
        rt = {} if ch else r.get("response_times", {})
        label = "Mualliflar (imzo bo'yicha)" if ch else "Ishtirokchilar"
        body.append(f"<div class='card'><h2>{label}</h2>" + _table(
            ["Ism", "Xabarlar", "Ulush %", "So'zlar", "O'rt. so'z", "Media", "Javob (daq)"],
            [[s["name"], s["messages"], s["share"], s["words"], s["avg_words"], s["media"],
              rt.get(s["name"], {}).get("median_min", "—")] for s in senders[:30]]) + "</div>")

    cn = r["content"]
    for key, label in [("media", "Kontent turlari"), ("top_words", "Ko'p ishlatilgan so'zlar"),
                       ("top_hashtags", "Heshteglar"), ("top_mentions", "Eslatmalar"),
                       ("top_domains", "Havola domenlari"), ("top_emoji", "Emoji"),
                       ("top_reactions", "Reaksiyalar")]:
        if cn.get(key):
            body.append(f"<div class='card'><h2>{label}</h2>{_chips(cn[key])}</div>")
    body.append("<p class='muted'>telegram-analiz yordamida yaratildi.</p>")
    return _page(title, body)


def _page(title: str, body: list[str]) -> str:
    return (
        "<!doctype html><html lang='uz'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'>"
        "<meta name='claude:viewport-fit-sides' content='cover'>"
        f"<title>{html.escape(title)} tahlili</title>"
        "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500;600"
        "&family=IBM+Plex+Sans:wght@400;600&display=swap'>"
        f"<style>{CSS}</style></head>"
        f"<body><main>{''.join(body)}</main></body></html>"
    )


def to_json(r: dict[str, Any]) -> str:
    return json.dumps(r, ensure_ascii=False, indent=2, default=str)
