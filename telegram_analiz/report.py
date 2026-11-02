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
:root{--bg:#f4f6f9;--card:#ffffff;--fg:#17202b;--muted:#5e6b7a;--line:#dfe5ec;--accent:#2b7bd6;--on-accent:#ffffff;--chip:#e9f1fb;--good:#1f8a5b;--bad:#c8463b;--warn:#b7791f;
--font-body:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--font-num:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#11161d;--card:#18202a;--fg:#e6ebf1;--muted:#93a1b1;--line:#28323e;--accent:#5ea4f0;--on-accent:#0b1420;--chip:#1d2b3b;--good:#4cc38a;--bad:#ef7a6f;--warn:#e0a84a;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#11161d;--card:#18202a;--fg:#e6ebf1;--muted:#93a1b1;--line:#28323e;--accent:#5ea4f0;--on-accent:#0b1420;--chip:#1d2b3b;--good:#4cc38a;--bad:#ef7a6f;--warn:#e0a84a;color-scheme:dark}
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
.tb{display:grid;gap:14px;margin:0 0 22px}
.tb-top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.tb-top h1{font-size:26px;margin:0}
.btn-ghost{display:inline-flex;align-items:center;gap:6px;font:600 14px var(--font-body);padding:8px 14px;border:1px solid var(--line);border-radius:999px;color:var(--fg);background:var(--card)}
.btn-ghost:hover{border-color:var(--accent);text-decoration:none}
.tb-meta{display:flex;flex-wrap:wrap;gap:6px 22px;font-size:14px;color:var(--muted);margin:0}
.tb-meta b{color:var(--fg);font-weight:600;font-variant-numeric:tabular-nums}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--good);margin-right:6px;vertical-align:1px}
.pills{display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));gap:10px}
.pill{display:flex;align-items:center;justify-content:center;min-height:44px;padding:8px 12px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--fg);font-weight:500;text-align:center}
.pill:hover{border-color:var(--accent);text-decoration:none}
.pill.on{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.pill.shift{border-style:dashed;color:var(--muted);grid-column:span 2}
.pill.off{opacity:.45;pointer-events:none}
.tb-row{display:grid;grid-template-columns:minmax(150px,1.3fr) minmax(130px,1fr) auto minmax(130px,1fr) minmax(150px,1fr) auto;gap:10px;align-items:center}
.tb-row select,.tb-row input{font:500 15px var(--font-body);padding:10px 14px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg);width:100%;min-width:0}
.tb-row .dash{color:var(--muted)}
.tb-row button{font:600 15px var(--font-body);padding:10px 22px;border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--fg);cursor:pointer}
.tb-row button:hover{border-color:var(--accent)}.tb-row button[disabled]{opacity:.6;cursor:progress}
.tb select:focus-visible,.tb input:focus-visible,.tb button:focus-visible,.pill:focus-visible,.btn-ghost:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.tb-warn{margin:0;font-size:13px;color:var(--warn)}
@media (max-width:760px){.tb-row{grid-template-columns:1fr 1fr}.tb-row .dash{display:none}.tb-row .wide{grid-column:1/-1}.pill.shift{grid-column:1/-1}}
.kpi .d{font:500 12px var(--font-num);margin-top:4px;color:var(--muted)}.kpi .d.up{color:var(--good)}.kpi .d.down{color:var(--bad)}
"""


def render_toolbar(
    *,
    title: str,
    action: str,
    base: dict[str, str],
    filters: Any,
    today: Any,
    type_options: list[tuple[str, str, int]],
    months: list[tuple[str, str]],
    meta: list[str],
    refresh_href: str,
    warnings: list[str] | None = None,
    fetched_ts: int | None = None,
    next_ts: int | None = None,
) -> str:
    """Yandex Direct dashboardidagi kabi panel: sarlavha, holat qatori, tayyor davrlar, sana/oy/tur."""
    from urllib.parse import urlencode

    from .filters import PRESETS, shift_month

    esc = html.escape

    def href(**params) -> str:
        q = dict(base)
        if filters.types:
            q["type"] = filters.types[0]
        q.update({k: v for k, v in params.items() if v})
        return f"{action}?{urlencode(q)}"

    start, end = filters.bounds(today)
    pills = [
        f"<a class='pill{' on' if filters.preset == key else ''}' href='{esc(href(preset=key))}'>{esc(label)}</a>"
        for key, label in PRESETS
    ]
    if start and end:
        prev_from, prev_to = shift_month(start), shift_month(end)
        pills.append(f"<a class='pill shift' href='{esc(href(**{'from': str(prev_from), 'to': str(prev_to)}))}'>"
                     "← O'tgan oyda shu sana</a>")
    else:
        pills.append("<span class='pill shift off'>← O'tgan oyda shu sana</span>")

    current_month = f"{filters.month[0]}-{filters.month[1]:02d}" if filters.month else ""
    month_opts = "<option value=''>Oyni tanlang</option>" + "".join(
        f"<option value='{v}'{' selected' if v == current_month else ''}>{esc(label)}</option>" for v, label in months
    )
    selected_type = filters.types[0] if filters.types else "all"
    type_opts = f"<option value='all'{' selected' if selected_type == 'all' else ''}>Barcha turlar</option>" + "".join(
        f"<option value='{esc(k)}'{' selected' if k == selected_type else ''}>{esc(label)} ({n})</option>"
        for k, label, n in type_options
    )
    hidden = "".join(f"<input type='hidden' name='{esc(k)}' value='{esc(v)}'>" for k, v in base.items())
    if filters.preset:
        hidden += f"<input type='hidden' name='preset' value='{esc(filters.preset)}' id='t-preset'>"
    form = (
        f"<form id='tb-form' class='tb-row' method='get' action='{esc(action)}'>{hidden}"
        f"<select id='t-month' name='month' aria-label='Oy' class='wide'>{month_opts}</select>"
        f"<input id='t-from' type='date' name='from' value='{start or ''}' aria-label='Boshlanish sanasi'>"
        "<span class='dash'>—</span>"
        f"<input id='t-to' type='date' name='to' value='{end or ''}' aria-label='Tugash sanasi'>"
        f"<select id='t-type' name='type' aria-label='Post turi'>{type_opts}</select>"
        "<button type='submit'>Ko'rsatish</button></form>"
    )
    warn = "".join(f"<p class='tb-warn'>{esc(w)}</p>" for w in warnings or [])
    script = """<script>(function(){
var f=document.getElementById('tb-form');if(!f)return;
var a=f.querySelector('#t-from'),b=f.querySelector('#t-to'),m=f.querySelector('#t-month'),
    p=f.querySelector('#t-preset'),dirty=false,monthPicked=false;
[a,b].forEach(function(x){x.addEventListener('change',function(){dirty=true;});});
m.addEventListener('change',function(){if(!m.value)return;monthPicked=true;f.requestSubmit();});
f.querySelector('#t-type').addEventListener('change',function(){f.requestSubmit();});
f.addEventListener('submit',function(){
  if(monthPicked){a.disabled=b.disabled=true;if(p)p.disabled=true;}
  else if(dirty){m.disabled=true;if(p)p.disabled=true;}
  else{a.disabled=b.disabled=true;}
  var btn=f.querySelector('button');btn.disabled=true;btn.textContent='Yuklanmoqda…';});
window.addEventListener('pageshow',function(){a.disabled=b.disabled=m.disabled=false;if(p)p.disabled=false;
  var btn=f.querySelector('button');btn.disabled=false;btn.textContent="Ko'rsatish";});
function ago(){document.querySelectorAll('[data-ago]').forEach(function(el){
  var min=Math.floor((Date.now()/1000-+el.dataset.ago)/60);
  el.textContent=min<1?'hozirgina':min<60?min+' daqiqa oldin':Math.floor(min/60)+' soat oldin';});}
ago();setInterval(ago,30000);
var tb=document.querySelector('.tb'),dataTs=+(tb&&tb.dataset.ts||0),nextTs=+(tb&&tb.dataset.next||0);
function getV(){try{return +(localStorage.getItem('tg-v')||0);}catch(e){return 0;}}
function setV(v){try{localStorage.setItem('tg-v',String(v));}catch(e){}}
var url=new URL(location.href),v=+(url.searchParams.get('v')||0);
if(v)setV(v);
// "Yangilash" boshqa sahifada bosilgan bo'lsa, eski (keshdagi) sahifani yangisiga almashtiramiz.
var lastV=getV();
if(!v&&lastV>dataTs&&nextTs&&lastV>=nextTs-1200){url.searchParams.set('v',lastV);location.replace(url.toString());}
var r=document.getElementById('tb-refresh');
if(r)r.addEventListener('click',function(){var u=new URL(r.href,location.href);
  u.searchParams.set('refresh',Date.now());r.href=u.pathname+u.search;r.textContent='↻ Yangilanmoqda…';});
// Har 20 daqiqada (keyingi yangilanish vaqtida) sahifani o'zi qayta yuklaydi.
function reload(){var u=new URL(location.href);u.searchParams.delete('v');u.searchParams.delete('refresh');
  location.replace(u.toString());}
if(nextTs){var wait=Math.max(5000,(nextTs+15)*1000-Date.now());
  setTimeout(function(){if(document.hidden){document.addEventListener('visibilitychange',function h(){
    if(!document.hidden){document.removeEventListener('visibilitychange',h);reload();}});}else reload();},wait);}
})();</script>"""
    data_attrs = (f" data-ts='{fetched_ts}'" if fetched_ts else "") + (f" data-next='{next_ts}'" if next_ts else "")
    return (
        f"<header class='tb'{data_attrs}>"
        f"<div class='tb-top'><h1>{esc(title)}</h1>"
        f"<a id='tb-refresh' class='btn-ghost' href='{esc(refresh_href)}'>↻ Yangilash</a></div>"
        f"<p class='tb-meta'>{''.join(f'<span>{x}</span>' for x in meta)}</p>"
        f"<nav class='pills' aria-label='Davr'>{''.join(pills)}</nav>"
        f"{form}{warn}</header>{script}"
    )


def _delta(cur: float | None, prev: float | None, points: bool = False) -> str:
    """KPI ostidagi o'zgarish: ↑ 12% / ↓ 3 p.p."""
    if cur is None or prev is None:
        return "<div class='d'>solishtirish yo'q</div>"
    if points:
        diff = round(cur - prev, 2)
        cls = "up" if diff > 0 else "down" if diff < 0 else ""
        arrow = "↑" if diff > 0 else "↓" if diff < 0 else "≈"
        return f"<div class='d {cls}'>{arrow} {abs(diff):g} p.p.</div>"
    if not prev:
        return "<div class='d'>oldin 0</div>" if cur else "<div class='d'>≈ 0%</div>"
    pct = (cur - prev) / prev * 100
    cls = "up" if pct >= 0.5 else "down" if pct <= -0.5 else ""
    arrow = "↑" if pct >= 0.5 else "↓" if pct <= -0.5 else "≈"
    return f"<div class='d {cls}'>{arrow} {abs(pct):.0f}%</div>"


def _legacy_kpis(c: dict[str, Any], t: dict[str, Any], ch: dict[str, Any] | None) -> str:
    """Solishtirishsiz KPI'lar (buyruq qatori hisoboti)."""
    esc = html.escape
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
    return "<div class='grid'>" + "".join(
        f"<div class='kpi'><div class='k'>{esc(k)}</div><div class='v'>{esc(_n(v))}</div></div>" for k, v in kpis
    ) + "</div>"


def to_html(r: dict[str, Any], top_html: str = "", show_header: bool = True,
            compare: dict[str, Any] | None = None) -> str:
    """compare berilsa (sayt), KPI'lar solishtirish davriga nisbatan o'zgarish bilan chiqadi."""
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
    if compare is not None and ch:
        pc, pt = compare.get("channel") or {}, compare.get("totals") or {}
        have = bool(compare.get("available"))

        def prev(v):
            return v if have else None

        tiles = [
            ("Postlar", _n(t["messages"]), _delta(t["messages"], prev(pt.get("messages", 0)))),
            ("Ko'rishlar jami", _n(ch["total_views"]), _delta(ch["total_views"], prev(pc.get("total_views", 0)))),
            ("O'rtacha ko'rish", _n(ch["avg_views"]), _delta(ch["avg_views"], prev(pc.get("avg_views")))),
            ("Mediana ko'rish", _n(ch["median_views"]), _delta(ch["median_views"], prev(pc.get("median_views")))),
            ("Reaksiyalar", _n(t["reactions"]), _delta(t["reactions"], prev(pt.get("reactions", 0)))),
            ("Reaksiya darajasi", f"{ch['avg_reaction_rate_pct']}%",
             _delta(ch["avg_reaction_rate_pct"], prev(pc.get("avg_reaction_rate_pct")), points=True)),
        ]
        if ch["err_pct"] is not None:
            tiles.append(("ERR", f"{ch['err_pct']}%", _delta(ch["err_pct"], prev(pc.get("err_pct")), points=True)))
        if c.get("subscribers"):
            tiles.append(("Obunachilar", _n(c["subscribers"]), "<div class='d'>hozir</div>"))
        body.append("<div class='grid'>" + "".join(
            f"<div class='kpi'><div class='k'>{esc(k)}</div><div class='v'>{esc(v)}</div>{d}</div>"
            for k, v, d in tiles
        ) + "</div>")
    else:
        body.append(_legacy_kpis(c, t, ch))
    body.append(f"<p class='muted'>{t['first_message'][:10]} — {t['last_message'][:10]} · "
                f"eng faol kun {t['busiest_day']['date']} ({t['busiest_day']['messages']} ta)</p>")

    if ch:
        if ch["recommendations"]:
            body.append("<div class='card tips'><h2>Tavsiyalar</h2><ul class='tips-list'>" +
                        "".join(f"<li>{esc(x)}</li>" for x in ch["recommendations"]) + "</ul></div>")
        if t["span_days"] <= 62 and ch.get("views_by_day"):
            # Qisqa davr: har kuni chiqqan postlarning jami ko'rishlari (postsiz kunlar 0).
            from datetime import date as _date, timedelta as _td
            first = _date.fromisoformat(t["first_message"][:10])
            days = [first + _td(days=i) for i in range(t["span_days"])]
            vals = [ch["views_by_day"].get(d.isoformat(), 0) for d in days]
            body.append("<div class='card'><h2>Kunlar bo'yicha ko'rishlar</h2>" +
                        _svg_bars([d.strftime("%d.%m") for d in days], vals) +
                        "<p class='muted note'>Shu kuni chiqqan postlarning jami ko'rishlari.</p></div>")
        elif ch["views_by_month"]:
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
