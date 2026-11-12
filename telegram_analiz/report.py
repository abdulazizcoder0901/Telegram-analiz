"""Natijani konsol, HTML va JSON ko'rinishida chiqarish."""

from __future__ import annotations

import html
import json
from datetime import datetime
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
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 var(--font-body)}
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
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin:0 0 4px}
.tabs [role=tab]{font:600 15px var(--font-body);padding:10px 16px;border:0;border-bottom:2px solid transparent;margin-bottom:-1px;background:none;color:var(--muted);cursor:pointer;display:inline-flex;align-items:center;gap:8px}
.tabs [role=tab]:hover{color:var(--fg)}
.tabs [role=tab][aria-selected=true]{color:var(--fg);border-bottom-color:var(--accent)}
.tabs [role=tab]:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.badge{font:600 12px var(--font-num);background:var(--chip);color:var(--fg);border-radius:999px;padding:1px 8px}
.kpi .d{font:500 12px var(--font-num);margin-top:4px;color:var(--muted)}.kpi .d.up{color:var(--good)}.kpi .d.down{color:var(--bad)}
.kpi .v.up{color:var(--good)}.kpi .v.down{color:var(--bad)}
.sec{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;margin:22px 0 0;font-weight:600}
.followers .grid{margin-top:10px}
.chart.div rect.up{fill:var(--good)}.chart.div rect.down{fill:var(--bad)}
.chart .axis{stroke:var(--line);stroke-width:1}.chart .grid{stroke:var(--line);stroke-dasharray:3 4}
.chart.line .stroke{fill:none;stroke:var(--accent);stroke-width:2.5;stroke-linejoin:round}
.chart.line .area{fill:var(--accent);fill-opacity:.12}.chart.line .dot{fill:var(--accent)}
.legend{display:flex;gap:16px;font-size:13px;color:var(--muted);margin:0 0 8px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
details.card summary{cursor:pointer;font-weight:600}details.card[open] summary{margin-bottom:10px}
.setup{border-style:dashed}
.kpi-btn{font:inherit;color:inherit;text-align:left;cursor:pointer;width:100%;display:block}
.kpi-btn:hover{border-color:var(--accent)}
.kpi-btn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.kpi-more{font-size:12px;color:var(--accent);margin-top:6px}
.aud-modal{width:min(640px,calc(100vw - 32px));max-height:calc(100vh - 48px);overflow:auto;padding:20px 22px;
border:1px solid var(--line);border-radius:14px;background:var(--card);color:var(--fg);box-shadow:0 24px 60px -20px rgba(0,0,0,.55)}
.aud-modal::backdrop{background:rgba(8,12,18,.55)}
.aud-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:6px}
.aud-head h2{margin:0}.aud-head h2 .muted{font-weight:500;font-size:13px;margin-left:6px}
.aud-close{flex:0 0 auto;width:34px;height:34px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);font-size:20px;line-height:1;cursor:pointer}
.aud-close:hover{border-color:var(--accent)}.aud-close:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.aud-row{display:grid;grid-template-columns:minmax(0,1fr) auto 64px minmax(80px,180px);gap:12px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)}
.aud-l{min-width:0}.aud-n{font:600 15px var(--font-num);font-variant-numeric:tabular-nums;text-align:right}
.aud-p{font:500 14px var(--font-num);color:var(--muted);text-align:right}
.aud-bar{height:8px;border-radius:999px;background:var(--chip);position:relative;overflow:hidden}
.aud-bar i{position:absolute;inset:0 auto 0 0;border-radius:999px}.aud-bar.up i{background:var(--good)}.aud-bar.down i{background:var(--bad)}
.aud-extra{margin:10px 0 0;font-size:14px}.aud-extra b{font-family:var(--font-num)}
@media (max-width:560px){.aud-row{grid-template-columns:minmax(0,1fr) auto 56px}.aud-bar{grid-column:1/-1}}
.plan-head{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;margin:18px 0 6px}
.plan-title{font-size:20px;margin:0}.plan-sub{margin:4px 0 0;font-size:14px}
.plan-nav{display:flex;gap:16px;font-size:14px}
.plan-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:10px 0}
.plan-grid .card{margin:0}.plan-empty h2{margin-bottom:6px}
.pcard{display:grid;gap:10px}.pk{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.pv{font:600 24px/1.2 var(--font-num);font-variant-numeric:tabular-nums;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.pv .muted{font-size:16px;font-weight:500}.ppct{margin-left:auto;font-size:15px;color:var(--fg)}
.pbar{position:relative;height:10px;border-radius:999px;background:var(--chip);overflow:visible}
.pbar i{position:absolute;inset:0 auto 0 0;border-radius:999px;background:var(--accent)}
.pbar.good i{background:var(--good)}.pbar.bad i{background:var(--bad)}
.pbar s{position:absolute;top:-4px;bottom:-4px;width:2px;margin-left:-1px;background:var(--fg);opacity:.55;text-decoration:none}
.pmeta{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center;font-size:14px;color:var(--muted)}
.pmeta b{color:var(--fg);font-family:var(--font-num)}
.pstat{font-size:12px;font-weight:600;padding:2px 10px;border-radius:999px;background:var(--chip);color:var(--fg)}
.pstat.ahead,.pstat.ok,.pstat.done{background:color-mix(in srgb,var(--good) 18%,transparent);color:var(--good)}
.pstat.behind,.pstat.missed{background:color-mix(in srgb,var(--bad) 18%,transparent);color:var(--bad)}
.plines{display:grid;grid-template-columns:1fr auto;gap:4px 12px;margin:0;font-size:13px}
.plines dt{color:var(--muted)}.plines dd{margin:0;font-family:var(--font-num);font-variant-numeric:tabular-nums;text-align:right}
.plan-edit{margin-top:16px}
.plan-rows-head,.plan-row{display:grid;grid-template-columns:minmax(200px,2fr) minmax(90px,1fr) minmax(90px,1fr) 36px;gap:8px;align-items:center}
.plan-rows-head{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.plan-row{margin-bottom:8px}.pr-metric{display:grid;gap:6px;min-width:0}
.plan-row select,.plan-row input{font:500 14px var(--font-body);padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);width:100%;min-width:0}
.pr-auto{font-size:13px;font-family:var(--font-num)}
.pr-del{border:1px solid var(--line);background:var(--card);color:var(--muted);border-radius:8px;height:36px;font-size:18px;cursor:pointer}
.pr-del:hover{color:var(--bad);border-color:var(--bad)}
.plan-actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-top:10px}
.plan-actions input{font:500 14px var(--font-body);padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}
#plan-save{font:600 14px var(--font-body);padding:9px 18px;border:0;border-radius:8px;background:var(--accent);color:var(--on-accent);cursor:pointer}
#plan-save[disabled]{opacity:.6;cursor:progress}
.plan-row :focus-visible,#plan-save:focus-visible,.pr-del:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (max-width:640px){.plan-rows-head{display:none}.plan-row{grid-template-columns:1fr 1fr 36px}.pr-metric{grid-column:1/-1}}
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


def render_followers_block(
    *,
    summary: dict[str, Any] | None,
    raw: dict[str, Any] | None,
    sources: list[tuple[str, float]] | None = None,
    error: str | None = None,
    configured: bool = True,
    fetched_label: str = "",
    month_start: dict[str, Any] | None = None,
) -> str:
    """Saytdagi "Obunachilar" bo'limi (Telegram admin statistikasi)."""
    from .admin_stats import _signed, _svg_diverging, _svg_line
    from .filters import format_range

    esc = html.escape
    head = "<section class='followers'><h2 class='sec'>Obunachilar</h2>"
    if not configured:
        return (head + "<div class='card setup'><p>Qo'shilgan va chiqib ketgan obunachilar, oy boshidagi son — "
                "Telegram admin statistikasidan olinadi va hali ulanmagan. Vercel'ga <b>TG_API_ID</b>, "
                "<b>TG_API_HASH</b> va <b>TG_SESSION</b> qo'shilgach shu yerda chiqadi (README: "
                "“Obunachilar statistikasi”).</p></div></section>")
    if summary is None:
        msg = error or "Bu davr uchun Telegram statistikasi yo'q."
        return head + f"<div class='card'><p class='muted'>{esc(msg)}</p></div></section>"

    def num(v):
        return _n(int(v)) if v is not None else "—"

    def tg_delta(v: dict[str, Any] | None) -> str:
        if not v or v.get("previous") in (None, 0):
            return ""
        diff = v["current"] - v["previous"]
        pct = abs(diff) / v["previous"] * 100
        cls = "up" if diff > 0 else "down" if diff < 0 else ""
        sign = "+" if diff > 0 else "−" if diff < 0 else ""
        return f"<div class='d {cls}'>{sign}{_n(round(abs(diff)))} ({pct:.2f}%)</div>"

    raw = raw or {}
    start = summary["from"]
    starts_on_first = start.endswith("-01")
    change = summary["total_change"] if summary["total_change"] is not None else summary["net"]
    ms = month_start or {}
    ms_total = ms.get("total") if ms else summary["start_total"] if starts_on_first else None
    ms_sub = ""
    if ms or starts_on_first:
        d = date_of(ms.get("date") or start)
        ms_sub = f"<div class='d'>{d.day}-{_MONTHS_SHORT[d.month]} holati</div>"
    tiles = [
        ("Obunachilar", num((raw.get("followers") or {}).get("current") or summary["end_total"]),
         "", tg_delta(raw.get("followers"))),
        ("Oy boshida", num(ms_total), "", ms_sub),
    ]
    if not starts_on_first:
        tiles.append(("Davr boshida", num(summary["start_total"]), "", f"<div class='d'>{esc(start)}</div>"))
    tiles += [
        ("Davr oxirida", num(summary["end_total"]), "", f"<div class='d'>{esc(summary['to'])}</div>"),
        ("Qo'shildi", "+" + num(summary["joined"]), "up", ""),
        ("Chiqib ketdi", "−" + num(summary["left"]), "down", ""),
        ("Sof o'zgarish", _signed(change), "up" if change and change > 0 else "down" if change and change < 0 else "",
         f"<div class='d'>{summary['growth_pct']:+.2f}%</div>" if summary.get("growth_pct") is not None else ""),
    ]
    en = raw.get("enabled_notifications") or {}
    if en.get("total"):
        tiles.append(("Bildirishnoma yoqilgan", f"{100 * en['part'] / en['total']:.2f}%", "", ""))
    overview = [("Post boshiga ko'rish", raw.get("views_per_post")),
                ("Post boshiga ulashish", raw.get("shares_per_post")),
                ("Post boshiga reaksiya", raw.get("reactions_per_post"))]
    for label, v in overview:
        if v and v.get("current") is not None:
            tiles.append((label, num(v["current"]), "", tg_delta(v)))

    aud = summary.get("audience")
    toggles = {"Qo'shildi": "aud-joined", "Chiqib ketdi": "aud-left"} if aud else {}

    def tile_html(k, v, c, d):
        inner = f"<div class='k'>{esc(k)}</div><div class='v {c}'>{esc(v)}</div>{d}"
        if k in toggles:
            return (f"<button type='button' class='kpi kpi-btn' aria-haspopup='dialog' aria-controls='{toggles[k]}'>"
                    f"{inner}<div class='kpi-more'>Tafsilot →</div></button>")
        return f"<div class='kpi'>{inner}</div>"

    parts = [head, "<div class='grid'>" + "".join(tile_html(*t) for t in tiles) + "</div>"]
    if aud:
        parts.append(_audience_panels(aud, summary))

    days = summary["days"]
    labels = [d["date"][8:10] + "." + d["date"][5:7] for d in days]
    line = _svg_line(labels, [d["total"] for d in days])
    div = _svg_diverging(labels, [d["joined"] or 0 for d in days], [d["left"] or 0 for d in days])
    parts.append("<div class='two'>")
    if line:
        parts.append(f"<div class='card'><h2>Jami obunachilar</h2>{line}</div>")
    parts.append("<div class='card'><h2>Har kuni qo'shilgan va chiqib ketgan</h2>"
                 "<div class='legend'><span><i style='background:var(--good)'></i>Qo'shildi</span>"
                 f"<span><i style='background:var(--bad)'></i>Chiqib ketdi</span></div>{div}</div>")
    parts.append("</div>")
    rows = [[d["date"], num(d["total"]), "+" + num(d["joined"]) if d["joined"] is not None else "—",
             "−" + num(d["left"]) if d["left"] is not None else "—", _signed(d["net"])] for d in reversed(days)]
    parts.append("<details class='card'><summary>Kunlar bo'yicha jadval</summary>" +
                 _table(["Sana", "Jami", "Qo'shildi", "Chiqdi", "Sof"], rows) + "</details>")
    if sources:
        total = sum(v for _, v in sources) or 1
        parts.append("<div class='card'><h2>Yangi obunachilar qayerdan keldi</h2>" + _table(
            ["Manba", "Obunachilar", "Ulush"],
            [[name, int(v), f"{100 * v / total:.1f}%"] for name, v in sources]) + "</div>")
    notes = []
    if summary.get("start_frozen_on"):
        notes.append(f"Oy boshidagi son ({summary['from']} holati) {summary['start_frozen_on']} da qayd etilgan va "
                     "boshqa o'zgarmaydi; sof o'zgarish shu songa nisbatan hisoblanadi.")
    if not summary["complete"]:
        notes.append(f"Statistika davrning faqat {format_range(date_of(summary['from']), date_of(summary['to']))} "
                     "qismini qamraydi.")
    if raw.get("period"):
        notes.append("Post boshiga ko'rsatkichlar va o'zgarishlar — Telegram'ning o'z davri: "
                     f"{raw['period']['min'][:10]} — {raw['period']['max'][:10]}, oldingi shuncha kunga nisbatan.")
    if fetched_label:
        notes.append(f"Telegram admin statistikasi · {fetched_label}")
    if error:
        notes.append(error)
    parts.append("".join(f"<p class='muted note'>{esc(n)}</p>" for n in notes))
    parts.append("</section><h2 class='sec'>Postlar</h2>")
    return "".join(parts)


def _audience_panels(aud: dict[str, Any], summary: dict[str, Any]) -> str:
    """"Qo'shildi" / "Chiqib ketdi" bosilganda ochiladigan panellar: guruhlar soni va foizi."""
    esc = html.escape

    def rows(groups: list[dict[str, Any]], cls: str) -> str:
        return "".join(
            f"<div class='aud-row'><span class='aud-l'>{esc(g['label'])}</span>"
            f"<span class='aud-n'>{_n(g['n'])}</span><span class='aud-p'>{g['pct']:g}%</span>"
            f"<span class='aud-bar {cls}'><i style='width:{min(100, g['pct'])}%'></i></span></div>"
            for g in groups if g["n"] or g["key"] != "unknown"
        )

    since = aud.get("tracking_since")
    since_txt = ""
    if since:
        dt = datetime.fromisoformat(since)
        since_txt = f"{dt.day}-{_MONTHS_SHORT[dt.month]} {dt:%H:%M}"
    j, lf = aud["joined"], aud["left"]
    note = (f"<p class='muted note'>Telegram'ning \"So'nggi harakatlar\" jurnali bo'yicha (kuzatuv {esc(since_txt)} dan; "
            "Telegram jurnalni 48 soat saqlaydi, shuning uchun undan oldingi qo'shilish vaqtlari noma'lum). "
            f"Jurnalda: +{_n(j['total'])} / −{_n(lf['total'])}; grafikda: +{_n(int(summary['joined']))} / "
            f"−{_n(int(summary['left']))}.</p>")
    if not aud.get("complete"):
        note += ("<p class='muted note'>Kuzatuv davr o'rtasida boshlangani uchun bu davr to'liq emas; "
                 "keyingi oydan boshlab ajratish to'liq bo'ladi.</p>")
    then_left = j.get("then_left") or {}
    joined_extra = (f"<p class='aud-extra'>Shulardan keyin chiqib ketgan: <b>{_n(then_left.get('n', 0))}</b> "
                    f"({then_left.get('pct', 0):g}%)</p>") if j["total"] else ""
    def dialog(dlg_id: str, title: str, total: int, body: str) -> str:
        return (
            f"<dialog id='{dlg_id}' class='aud-modal' aria-labelledby='{dlg_id}-t'>"
            f"<div class='aud-head'><h2 id='{dlg_id}-t'>{title} <span class='muted'>jurnal bo'yicha {_n(total)} ta</span></h2>"
            "<button type='button' class='aud-close' aria-label='Yopish'>×</button></div>"
            f"{body}{note}</dialog>"
        )

    return (
        dialog("aud-joined", "Qo'shilganlar: kimlar?", j["total"], rows(j["groups"], "up") + joined_extra)
        + dialog("aud-left", "Chiqib ketganlar: eski yoki yangi?", lf["total"], rows(lf["groups"], "down"))
        + AUDIENCE_SCRIPT
    )


AUDIENCE_SCRIPT = r"""<script>(function(){
// Kartochka bosilganda tafsilot alohida oynada (modal) ochiladi — sahifadagi bloklar siljimaydi.
document.querySelectorAll('.kpi-btn').forEach(function(b){
  var d=document.getElementById(b.getAttribute('aria-controls'));if(!d)return;
  b.addEventListener('click',function(){
    if(typeof d.showModal==='function'){d.showModal();}else{d.setAttribute('open','');}});
  d.addEventListener('close',function(){b.focus();});
});
document.querySelectorAll('.aud-modal').forEach(function(d){
  function close(){if(typeof d.close==='function'){d.close();}else{d.removeAttribute('open');}}
  d.querySelector('.aud-close').addEventListener('click',close);
  // Oynadan tashqariga (fonga) bosilsa yopiladi.
  d.addEventListener('click',function(e){if(e.target===d)close();});
});
})();</script>"""


_MONTHS_SHORT = ["", "yan", "fev", "mar", "apr", "may", "iyun", "iyul", "avg", "sen", "okt", "noy", "dek"]


def date_of(value: str):
    from datetime import date as _date
    return _date.fromisoformat(value[:10])


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
            compare: dict[str, Any] | None = None, web: bool = False, main_top_html: str = "",
            plan_html: str = "") -> str:
    """web=True (sayt): "Asosiy"/"Tavsiyalar" bo'limlari va KPI'lar ostida solishtirish davriga
    nisbatan o'zgarish (compare berilgan bo'lsa)."""
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
        empty = ("<div class='card'><h2>Postlar topilmadi</h2><p class='muted'>Tanlangan filtrlarga mos post yo'q. "
                 "Davrni kengaytiring yoki boshqa post turini tanlang.</p></div>")
        if web:
            body.append(_tabs_open(0, bool(plan_html)) + main_top_html + empty + "</section>")
            body.append(plan_html)
            body.append("<section id='p-tips' role='tabpanel' aria-labelledby='tab-tips' hidden>"
                        "<div class='card'><p class='muted'>Bu davr uchun tavsiya yo'q.</p></div></section>")
            body.append(TABS_SCRIPT)
        else:
            body.append(main_top_html + empty)
        return _page(title, body)

    ch = r.get("channel")
    tabs = web and bool(ch)  # sayt: "Asosiy", "Plan" va "Tavsiyalar" bo'limlari
    if tabs:
        body.append(_tabs_open(len(ch["recommendations"]), bool(plan_html)) + main_top_html)
    if web and ch:
        pc, pt = (compare or {}).get("channel") or {}, (compare or {}).get("totals") or {}
        have = bool((compare or {}).get("available"))

        def prev(v):
            return v if have else None

        # "Butun davr"da solishtiradigan davr yo'q — o'zgarish qatori ko'rsatilmaydi.
        delta = _delta if compare is not None else (lambda *_a, **_k: "")

        tiles = [
            ("Postlar", _n(t["messages"]), delta(t["messages"], prev(pt.get("messages", 0)))),
            ("Ko'rishlar jami", _n(ch["total_views"]), delta(ch["total_views"], prev(pc.get("total_views", 0)))),
            ("O'rtacha ko'rish", _n(ch["avg_views"]), delta(ch["avg_views"], prev(pc.get("avg_views")))),
            ("Mediana ko'rish", _n(ch["median_views"]), delta(ch["median_views"], prev(pc.get("median_views")))),
            ("Reaksiyalar", _n(t["reactions"]), delta(t["reactions"], prev(pt.get("reactions", 0)))),
            ("Reaksiya darajasi", f"{ch['avg_reaction_rate_pct']}%",
             delta(ch["avg_reaction_rate_pct"], prev(pc.get("avg_reaction_rate_pct")), points=True)),
        ]
        if ch["err_pct"] is not None:
            tiles.append(("ERR", f"{ch['err_pct']}%", delta(ch["err_pct"], prev(pc.get("err_pct")), points=True)))
        if c.get("subscribers") and "class='followers'" not in main_top_html:
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
        if ch["recommendations"] and not tabs:
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
    if tabs:
        body.append("</section>")
        body.append(plan_html)
        body.append(_tips_panel(ch))
        body.append(TABS_SCRIPT)
    body.append("<p class='muted'>telegram-analiz yordamida yaratildi.</p>")
    return _page(title, body)


def _tabs_open(n_tips: int, with_plan: bool) -> str:
    def tab(key: str, label: str, selected: bool = False) -> str:
        return (f"<button type='button' role='tab' id='tab-{key}' aria-controls='p-{key}' "
                f"aria-selected='{'true' if selected else 'false'}'>{label}</button>")

    return (
        "<div class='tabs' role='tablist' aria-label='Bo‘limlar'>"
        + tab("main", "Asosiy", True)
        + (tab("plan", "Plan") if with_plan else "")
        + tab("tips", f"Tavsiyalar<span class='badge'>{n_tips}</span>")
        + "</div><section id='p-main' role='tabpanel' aria-labelledby='tab-main'>"
    )


def render_plan_panel(ctx: dict[str, Any]) -> str:
    """"Plan" bo'limi. Planlar /api/plan dan brauzerda olinadi (CDN keshidan qat'i nazar doim yangi),
    faktlar sahifaga ``ctx["actuals"]`` sifatida joylanadi."""
    esc = html.escape
    data = json.dumps(ctx, ensure_ascii=False).replace("</", "<\\/")
    elapsed, total = ctx["days_elapsed"], ctx["days_total"]
    pct = round(100 * elapsed / total) if total else 0
    nav = ""
    if ctx.get("prev_href") or ctx.get("next_href"):
        nav = ("<nav class='plan-nav'>"
               + (f"<a href='{esc(ctx['prev_href'])}'>← {esc(ctx.get('prev_label', ''))}</a>" if ctx.get("prev_href") else "")
               + (f"<a href='{esc(ctx['next_href'])}'>{esc(ctx.get('next_label', ''))} →</a>" if ctx.get("next_href") else "")
               + "</nav>")
    return (
        "<section id='p-plan' role='tabpanel' aria-labelledby='tab-plan' hidden>"
        f"<div class='plan-head'><div><h2 class='plan-title'>Plan · {esc(ctx['month_label'])}</h2>"
        f"<p class='muted plan-sub'>{elapsed} / {total} kun o'tdi ({pct}%)</p></div>{nav}</div>"
        "<div id='plan-cards' class='plan-grid'><div class='card'><p class='muted'>Yuklanmoqda…</p></div></div>"
        "<details class='card plan-edit' id='plan-edit'><summary>Planni tahrirlash</summary>"
        "<form id='plan-form' novalidate>"
        "<div class='plan-rows-head'><span>Ko'rsatkich</span><span>Plan</span><span>Fakt</span><span></span></div>"
        "<div id='plan-rows'></div>"
        "<div class='plan-actions'>"
        "<button type='button' id='plan-add' class='btn-ghost'>+ Ko'rsatkich qo'shish</button>"
        "<input type='password' id='plan-pass' placeholder='Parol' autocomplete='current-password' hidden>"
        "<button type='submit' id='plan-save'>Saqlash</button>"
        "<span id='plan-msg' class='muted' role='status'></span></div>"
        "<p class='muted note'>Obunachilar, postlar va ko'rishlar fakti avtomatik hisoblanadi. "
        "\"Boshqa\" ko'rsatkichlar (masalan, sifatli lidlar) faktini o'zingiz kiritasiz.</p>"
        "</form></details>"
        f"<script type='application/json' id='plan-ctx'>{data}</script>"
        + PLAN_SCRIPT + "</section>"
    )


PLAN_SCRIPT = r"""<script>(function(){
var ctx=JSON.parse(document.getElementById('plan-ctx').textContent),M=ctx.metrics,A=ctx.actuals;
var cards=document.getElementById('plan-cards'),rows=document.getElementById('plan-rows'),
    form=document.getElementById('plan-form'),msg=document.getElementById('plan-msg'),
    pass=document.getElementById('plan-pass'),edit=document.getElementById('plan-edit');
var state={items:[],protected:false,storage:true};
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function fmt(n){if(n==null||isNaN(n))return '—';var r=Math.round(n);return (r<0?'−':'')+String(Math.abs(r)).replace(/\B(?=(\d{3})+(?!\d))/g,' ');}
function signed(n){return n==null?'—':(n>0?'+':'')+fmt(n);}
function name(it){return it.metric==='custom'?it.name:(M[it.metric]||{}).label||it.metric;}
function actual(it){return it.metric==='custom'?it.actual:A[it.metric];}
function evaluate(it){
  var m=M[it.metric]||{kind:'sum',dir:'up'},plan=+it.plan,act=actual(it),T=ctx.days_total,E=ctx.days_elapsed;
  var done=E>=T,frac=T?E/T:0,r={act:act,plan:plan,lines:[]};
  if(act==null){r.status='nodata';r.label=m.source==='admin'?"Obunachilar statistikasi yo'q":"Fakt kiritilmagan";return r;}
  r.pct=plan>0?act/plan*100:null;r.diff=act-plan;
  if(m.kind==='sum'){
    r.marker=done?null:frac*100;var expected=plan*frac,left=T-E;
    if(E===0){r.status='wait';r.label='Boshlanmagan';}
    else if(m.dir==='down'){var lim=done?plan:expected;r.status=act<=lim?'ok':'behind';r.label=act<=lim?"Me'yorda":'Oshib ketdi';}
    else if(done){r.status=act>=plan?'done':'missed';r.label=act>=plan?'Bajarildi':'Bajarilmadi';}
    else{var q=expected?act/expected:1;r.status=q>=1.05?'ahead':q>=0.95?'ok':'behind';
      r.label=q>=1.05?'Oldinda':q>=0.95?'Rejada':'Orqada';}
    if(!done&&E>0){r.lines.push(['Bugungacha kerak',fmt(expected)]);
      r.lines.push(['Oy oxiri prognozi',fmt(act/E*T)]);
      if(m.dir!=='down'&&left>0&&act<plan)r.lines.push(['Kuniga kerak (qolgan '+left+' kun)',fmt((plan-act)/left)]);}
  }else{
    var ok=m.dir==='down'?act<=plan:act>=plan;r.status=ok?'done':'behind';
    r.label=ok?'Plan darajasida':'Plandan past';
  }
  return r;
}
function renderCards(){
  if(!state.items.length){cards.innerHTML="<div class='card plan-empty'><h2>Bu oy uchun plan kiritilmagan</h2>"+
    "<p class='muted'>Pastdagi \"Planni tahrirlash\" bo'limida maqsadlarni yozing va saqlang — fakt bilan farq shu yerda chiqadi.</p></div>";return;}
  cards.innerHTML=state.items.map(function(it){var r=evaluate(it),w=r.pct==null?0:Math.min(100,Math.max(0,r.pct));
    var bad=r.status==='behind'||r.status==='missed',good=r.status==='ahead'||r.status==='ok'||r.status==='done';
    return "<div class='card pcard'><div class='pk'>"+esc(name(it))+"</div>"+
      "<div class='pv'><b>"+fmt(r.act)+"</b> <span class='muted'>/ "+fmt(r.plan)+"</span>"+
      (r.pct!=null?"<span class='ppct'>"+Math.round(r.pct)+"%</span>":"")+"</div>"+
      "<div class='pbar"+(bad?' bad':good?' good':'')+"'><i style='width:"+w+"%'></i>"+
      (r.marker!=null?"<s style='left:"+r.marker+"%' title='Bugungacha kerak'></s>":"")+"</div>"+
      "<div class='pmeta'><span class='pstat "+r.status+"'>"+esc(r.label)+"</span>"+
      (r.diff!=null?"<span>Farq: <b>"+signed(r.diff)+"</b></span>":"")+"</div>"+
      (r.lines.length?"<dl class='plines'>"+r.lines.map(function(l){return "<dt>"+esc(l[0])+"</dt><dd>"+l[1]+"</dd>";}).join('')+"</dl>":"")+
      "</div>";}).join('');
}
function rowHtml(it){
  var opts=Object.keys(M).map(function(k){return "<option value='"+k+"'"+(it.metric===k?' selected':'')+">"+esc(M[k].label)+"</option>";}).join('');
  var custom=it.metric==='custom';
  return "<div class='plan-row'><div class='pr-metric'><select class='pr-sel' aria-label=\"Ko'rsatkich\">"+opts+"</select>"+
    "<input class='pr-name' type='text' maxlength='60' placeholder='Nomi (masalan, Sifatli lidlar)' value='"+esc(it.name||'')+"'"+(custom?'':' hidden')+"></div>"+
    "<input class='pr-plan' type='number' min='0' step='any' inputmode='decimal' placeholder='Plan' aria-label='Plan' value='"+(it.plan==null?'':it.plan)+"'>"+
    "<input class='pr-act' type='number' min='0' step='any' inputmode='decimal' placeholder='Fakt' aria-label='Fakt' value='"+(it.actual==null?'':it.actual)+"'"+(custom?'':' hidden')+">"+
    (custom?"":"<span class='pr-auto muted'>avto: "+fmt(A[it.metric])+"</span>")+
    "<button type='button' class='pr-del' aria-label=\"O'chirish\">×</button></div>";
}
function renderRows(items){rows.innerHTML=items.map(rowHtml).join('');}
function readRows(){return Array.prototype.map.call(rows.querySelectorAll('.plan-row'),function(r){
  var metric=r.querySelector('.pr-sel').value,it={metric:metric,plan:r.querySelector('.pr-plan').value};
  if(metric==='custom'){it.name=r.querySelector('.pr-name').value.trim();it.actual=r.querySelector('.pr-act').value;}
  return it;});}
rows.addEventListener('change',function(e){if(e.target.classList.contains('pr-sel')){var items=readRows();renderRows(items);}});
rows.addEventListener('click',function(e){if(e.target.classList.contains('pr-del')){e.target.closest('.plan-row').remove();}});
document.getElementById('plan-add').addEventListener('click',function(){var items=readRows();items.push({metric:'joined',plan:null});renderRows(items);});
function getPass(){try{return localStorage.getItem('tg-plan-pass')||'';}catch(e){return '';}}
form.addEventListener('submit',function(e){e.preventDefault();
  var items=readRows().filter(function(it){return it.plan!==''||(it.name||'');});
  var btn=document.getElementById('plan-save');btn.disabled=true;msg.textContent='Saqlanmoqda…';
  fetch('/api/plan',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({channel:ctx.channel,month:ctx.month,items:items,password:pass.value||getPass()})})
  .then(function(r){return r.json().then(function(d){return [r.status,d];});})
  .then(function(x){var st=x[0],d=x[1];btn.disabled=false;
    if(st===200){state.items=d.items;renderCards();renderRows(state.items.length?state.items:ctx.suggested);
      if(pass.value){try{localStorage.setItem('tg-plan-pass',pass.value);}catch(e){}}
      msg.textContent='Saqlandi ✓ '+new Date().toLocaleTimeString('uz',{hour:'2-digit',minute:'2-digit'});}
    else{if(d.protected){pass.hidden=false;}msg.textContent=d.error||'Xato';}})
  .catch(function(){btn.disabled=false;msg.textContent="Saqlab bo'lmadi: internet aloqasini tekshiring.";});});
fetch('/api/plan?month='+encodeURIComponent(ctx.month)+'&channel='+encodeURIComponent(ctx.channel),{cache:'no-store'})
  .then(function(r){return r.json();})
  .then(function(d){state.items=d.items||[];state.protected=!!d.protected;state.storage=d.storage!==false;
    pass.hidden=!(state.protected&&!getPass());
    renderCards();renderRows(state.items.length?state.items:ctx.suggested);
    if(!state.items.length)edit.open=true;
    if(d.error){msg.textContent=d.error;}
    if(!state.storage){document.getElementById('plan-save').disabled=true;}})
  .catch(function(){cards.innerHTML="<div class='card'><p class='muted'>Planni yuklab bo'lmadi. Sahifani yangilang.</p></div>";
    renderRows(ctx.suggested);edit.open=true;});
})();</script>"""


def _tips_panel(ch: dict[str, Any]) -> str:
    """"Tavsiyalar" bo'limi: tavsiyalar ro'yxati va eng yaxshi vaqt jadvallari."""
    esc = html.escape
    tips = ch["recommendations"] or ["Bu davr uchun tavsiya topilmadi. Davrni kengaytirib ko'ring (masalan, 30 kun)."]
    min_posts = max(3, round(ch["posts_with_views"] * 0.02))
    hours = sorted((r for r in ch["views_by_hour"] if r["posts"] >= min_posts),
                   key=lambda r: -r["avg_views"])[:5]
    weekdays = sorted((r for r in ch["views_by_weekday"] if r["posts"] >= min(min_posts, 2)),
                      key=lambda r: -r["avg_views"])
    types = [r for r in ch["views_by_type"] if r["posts"] >= min(min_posts, 3)]
    parts = [
        "<section id='p-tips' role='tabpanel' aria-labelledby='tab-tips' hidden>",
        "<div class='card tips'><h2>Tavsiyalar</h2><ul class='tips-list'>"
        + "".join(f"<li>{esc(x)}</li>" for x in tips) + "</ul></div>",
        "<div class='two'>",
    ]
    if hours:
        parts.append("<div class='card'><h2>Post chiqarish uchun eng yaxshi soatlar</h2>" + _table(
            ["Soat", "Postlar", "O'rt. ko'rish"],
            [[f"{r['key']:02d}:00", r["posts"], r["avg_views"]] for r in hours]) +
            f"<p class='muted note'>Kamida {min_posts} ta post chiqqan soatlar hisobga olingan.</p></div>")
    if weekdays:
        parts.append("<div class='card'><h2>Hafta kunlari</h2>" + _table(
            ["Kun", "Postlar", "O'rt. ko'rish"],
            [[r["key"], r["posts"], r["avg_views"]] for r in weekdays]) + "</div>")
    parts.append("</div>")
    if types:
        parts.append("<div class='card'><h2>Qaysi post turi ko'proq ko'riladi</h2>" + _table(
            ["Tur", "Postlar", "O'rt. ko'rish", "Mediana"],
            [[r["key"], r["posts"], r["avg_views"], r["median_views"]] for r in types]) + "</div>")
    parts.append("</section>")
    return "".join(parts)


TABS_SCRIPT = """<script>(function(){
var names=['main','plan','tips'],hashes={main:'',plan:'#plan',tips:'#tavsiyalar'},tabs={},panels={};
names.forEach(function(k){var t=document.getElementById('tab-'+k),p=document.getElementById('p-'+k);
  if(t&&p){tabs[k]=t;panels[k]=p;}});
var keys=Object.keys(tabs);if(keys.length<2)return;
function withHash(href,hash){var u=new URL(href,location.href);u.hash=hash;return u.pathname+u.search+u.hash;}
function show(name,save){
  if(!tabs[name])name='main';
  keys.forEach(function(k){var on=k===name;tabs[k].setAttribute('aria-selected',on);
    tabs[k].tabIndex=on?0:-1;panels[k].hidden=!on;});
  var hash=hashes[name];
  if(save)history.replaceState(null,'',location.pathname+location.search+hash);
  // Filtr, oy, "Yangilash" va plan oyi havolalari tanlangan bo'limni saqlab qoladi.
  document.querySelectorAll('.pills a.pill,#tb-refresh,.plan-nav a').forEach(function(a){a.href=withHash(a.href,hash);});
  var f=document.getElementById('tb-form');if(f)f.action=withHash(f.getAttribute('action').split('#')[0],hash);
}
keys.forEach(function(k){tabs[k].addEventListener('click',function(){show(k,true);});});
document.querySelector('.tabs').addEventListener('keydown',function(e){
  if(e.key!=='ArrowRight'&&e.key!=='ArrowLeft')return;
  var cur=keys.findIndex(function(k){return tabs[k].getAttribute('aria-selected')==='true';});
  var n=keys[(cur+(e.key==='ArrowRight'?1:keys.length-1))%keys.length];show(n,true);tabs[n].focus();});
var start=Object.keys(hashes).find(function(k){return hashes[k]&&hashes[k]===location.hash;});
show(start||'main',false);
})();</script>"""


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
