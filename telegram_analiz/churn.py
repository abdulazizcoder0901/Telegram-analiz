"""Nega obunachilar chiqib ketmoqda: kunlik chiqishlar, postlar va jurnal bo'yicha taxminiy sabablar.

Telegram chiqib ketish sababini aytmaydi. Bu yerda faqat bog'liqliklar ko'riladi (masalan, sotuv posti
chiqqan kunlari chiqish ko'pmi, post chiqqandan keyingi soatlarda chiqish ko'payadimi) — bu isbot emas,
lekin nimani sinab ko'rishni ko'rsatadi.
"""

from __future__ import annotations

import re
import statistics
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

# Sotuv / reklama postini taxminan aniqlash uchun so'zlar (o'zbek lotin va kirill, rus).
PROMO_RE = re.compile(
    r"narx|chegirma|skidka|aksiya|sotuv|to['ʻ’`]?lov|so['ʻ’`]?m\b|ro['ʻ’`]?yxatdan|"
    r"adminga|murojaat|joylar soni|joy qoldi|bepul dars|kursga yoziling|"
    r"нарх|чегирма|скидк|акци|цена|оплат|запис",
    re.IGNORECASE,
)

MIN_DAYS = 3  # guruhni solishtirish uchun kamida shuncha kun


def _is_promo(text: str) -> bool:
    return bool(PROMO_RE.search(text or ""))


def _parse_utc(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def analyze_churn(days: list[dict[str, Any]], posts: list[Any], members: dict[str, dict[str, list[str]]] | None,
                  tz: tzinfo, today: date) -> dict[str, Any]:
    """days — Telegram grafigidan kunlik qatorlar (date, joined, left); posts — davrdagi kanal postlari
    (loader.Message, sanalar ``tz`` bo'yicha); members — jurnal (MemberLog.load)."""
    out: dict[str, Any] = {"findings": [], "spikes": []}
    rows = [r for r in days if r.get("left") is not None]
    # Bugungi kun hali tugamagan — taqqoslashlarga kiritilmaydi.
    full = [r for r in rows if date.fromisoformat(r["date"]) < today]
    if len(full) < MIN_DAYS:
        return out
    lefts = [r["left"] for r in full]
    mean_left = sum(lefts) / len(lefts)
    out["avg_left"] = round(mean_left, 1)
    out["total_left"] = int(sum(lefts))

    posts_by_day: dict[str, list[Any]] = {}
    for m in posts:
        if getattr(m, "kind", "message") == "message":
            posts_by_day.setdefault(m.date.date().isoformat(), []).append(m)

    # 1) Chiqish ko'p bo'lgan kunlar va o'sha kuni (yoki kechasi) chiqqan postlar.
    sd = statistics.pstdev(lefts) if len(lefts) > 1 else 0
    threshold = max(mean_left * 1.4, mean_left + sd)
    for r in sorted(full, key=lambda r: -r["left"]):
        if r["left"] < threshold or len(out["spikes"]) >= 3:
            break
        d = date.fromisoformat(r["date"])
        same = posts_by_day.get(d.isoformat(), [])
        prev = posts_by_day.get((d - timedelta(days=1)).isoformat(), [])
        out["spikes"].append({
            "date": r["date"], "left": int(r["left"]), "joined": int(r.get("joined") or 0),
            "times_avg": round(r["left"] / mean_left, 1) if mean_left else None,
            "posts": [{"time": m.date.strftime("%d.%m %H:%M"), "text": (m.text or "").replace("\n", " ")[:90],
                       "promo": _is_promo(m.text), "link": getattr(m, "link", None)} for m in prev[-2:] + same],
        })

    # 2) Kuniga post soni va chiqish (o'sha kun + ertasi kuni chiqishlar).
    left_by_day = {r["date"]: r["left"] for r in full}

    def next_left(iso: str) -> float | None:
        nxt = (date.fromisoformat(iso) + timedelta(days=1)).isoformat()
        return left_by_day.get(nxt)

    groups: dict[str, list[float]] = {"0-1": [], "2": [], "3+": []}
    promo_days, plain_days = [], []
    for iso, left in left_by_day.items():
        n = len(posts_by_day.get(iso, []))
        groups["0-1" if n <= 1 else "2" if n == 2 else "3+"].append(left)
        day_posts = posts_by_day.get(iso, [])
        if day_posts:
            nl = next_left(iso)
            window = left + (nl if nl is not None else left)
            (promo_days if any(_is_promo(m.text) for m in day_posts) else plain_days).append(window / 2)
    out["by_post_count"] = {k: {"days": len(v), "avg_left": _avg(v)} for k, v in groups.items()}
    low, high = groups["0-1"], groups["3+"]
    if len(low) >= MIN_DAYS and len(high) >= MIN_DAYS and _avg(low):
        ratio = _avg(high) / _avg(low)
        out["post_count_ratio"] = round(ratio, 2)
        if ratio >= 1.2:
            out["findings"].append(
                f"Kuniga 3 va undan ko'p post chiqqan kunlari o'rtacha {_avg(high):g} kishi chiqqan, 0–1 post "
                f"chiqqan kunlari esa {_avg(low):g} — {round((ratio - 1) * 100)}% ko'p.")
    if len(promo_days) >= MIN_DAYS and len(plain_days) >= MIN_DAYS and _avg(plain_days):
        ratio = _avg(promo_days) / _avg(plain_days)
        out["promo_ratio"] = round(ratio, 2)
        out["promo_days"], out["plain_days"] = len(promo_days), len(plain_days)
        if ratio >= 1.15:
            out["findings"].append(
                f"Sotuvga oid post (narx, chegirma, \"adminga yozing\") chiqqan kunlari va ertasiga o'rtacha "
                f"{_avg(promo_days):g} kishi chiqqan, boshqa postli kunlari {_avg(plain_days):g} — "
                f"{round((ratio - 1) * 100)}% ko'p.")

    # 3) Jurnal: yangi kelganlar qancha tez ketadi, chiqishlar postdan keyin bo'ladimi, qaysi soatda.
    if members:
        to_leave_days, leaves, joins = [], [], 0
        for row in members.values():
            js = sorted(_parse_utc(t) for t in row.get("j", []))
            ls = sorted(_parse_utc(t) for t in row.get("l", []))
            joins += len(js)
            leaves += ls
            for lt in ls:
                prior = [j for j in js if j <= lt]
                if prior:
                    to_leave_days.append((lt - prior[-1]).total_seconds() / 86400)
        if joins >= 20:
            fast = sum(1 for x in to_leave_days if x <= 2)
            out["fast_churn"] = {"joined": joins, "left_within_2d": fast, "pct": round(100 * fast / joins, 1)}
            if fast / joins >= 0.1:
                out["findings"].append(
                    f"Jurnal bo'yicha yangi qo'shilganlarning {round(100 * fast / joins)}% ({fast} / {joins}) "
                    "2 kun ichida chiqib ketgan — ular kanaldan kutganini topmayapti.")
        if to_leave_days:
            out["median_days_to_leave"] = round(statistics.median(to_leave_days), 1)
        if len(leaves) >= 20 and posts:
            post_times = sorted(m.date.replace(tzinfo=tz) for m in posts if getattr(m, "kind", "message") == "message")
            start, end = min(leaves), max(leaves)
            window = timedelta(hours=3)
            covered = timedelta()
            last_end = None
            for pt in post_times:  # postdan keyingi 3 soatlik oynalar log davrini qanchalik qoplaydi
                a, b = max(pt, start), min(pt + window, end)
                if last_end and a < last_end:
                    a = last_end
                if b > a:
                    covered += b - a
                    last_end = b
            span = (end - start).total_seconds()
            after = sum(1 for lt in leaves if any(timedelta() <= lt - pt <= window for pt in post_times))
            if span > 0 and covered.total_seconds() > 0:
                expected = covered.total_seconds() / span
                actual = after / len(leaves)
                out["after_post"] = {"pct": round(100 * actual, 1), "expected_pct": round(100 * expected, 1)}
                if actual >= expected * 1.3 and actual >= 0.25:
                    out["findings"].append(
                        f"Chiqishlarning {round(100 * actual)}% post chiqqandan keyingi 3 soat ichida bo'lgan "
                        f"(tasodifiy bo'lsa ~{round(100 * expected)}% bo'lardi) — ayrim postlar va bildirishnomalar "
                        "odamlarni chiqib ketishga undayapti.")
            hours: dict[int, int] = {}
            for lt in leaves:
                h = lt.astimezone(tz).hour
                hours[h] = hours.get(h, 0) + 1
            peak = max(hours, key=hours.get)
            out["leave_peak_hour"] = {"hour": peak, "n": hours[peak], "of": len(leaves)}

    if out["spikes"]:
        s = out["spikes"][0]
        promo = any(p["promo"] for p in s["posts"])
        out["findings"].insert(0, (
            f"Eng ko'p chiqish {date.fromisoformat(s['date']).strftime('%d.%m')} kuni: {s['left']} kishi "
            f"(odatdagidan {s['times_avg']:g} baravar ko'p)"
            + ("; o'sha kuni yoki oldingi kun sotuvga oid post chiqqan." if promo else
               "; o'sha kungi postlarni pastdagi jadvalda ko'ring.")))

    out["recommendations"] = recommendations(out)
    return out


def recommendations(ins: dict[str, Any]) -> list[str]:
    """Topilmalarga mos ushlab qolish tavsiyalari (avval — ma'lumotga asoslanganlari)."""
    tips: list[str] = []
    fast = ins.get("fast_churn") or {}
    if fast.get("pct", 0) >= 10:
        tips.append("Yangi obunachilar uchun \"xush kelibsiz\" postini qadab qo'ying: kanal nima beradi, qaysi kunlari "
                    "nima chiqadi, eng foydali 3–5 post havolasi. Birinchi 48 soatda qiymat ko'rmagan odam chiqib ketadi.")
        tips.append("Reklama va'dasini tekshiring: reklamada nima va'da qilingan bo'lsa (masalan, bepul dars), kanalda "
                    "shu darhol ko'rinib tursin. Reklama auditoriyasini toraytiring (masalan, faqat 8–17 yoshli farzandi "
                    "bor ota-onalar) — tasodifiy obunachilar tez ketadi.")
    if (ins.get("promo_ratio") or 0) >= 1.15:
        tips.append("Sotuv postlarini kamaytiring: 4–5 foydali post (maslahat, o'quvchi natijasi, dars parchasi) ga "
                    "1 ta sotuv posti. Narx va \"adminga yozing\"ni foydali kontent ichiga qo'shing, alohida reklama qilib emas.")
    if (ins.get("post_count_ratio") or 0) >= 1.2:
        tips.append("Kuniga 1–2 ta postdan oshirmang. Bir nechta xabarni bitta postga (albom yoki ro'yxat) birlashtiring.")
    after = ins.get("after_post") or {}
    if after and after["pct"] >= max(25, after["expected_pct"] * 1.3):
        tips.append("Muhim bo'lmagan postlarni ovozsiz yuboring (yuborish tugmasini bosib turing → \"Ovozsiz yuborish\"), "
                    "kechki va tungi soatlarda post qo'ymang — har bildirishnoma \"obunani bekor qilish\" uchun turtki.")
    if ins.get("spikes"):
        tips.append("Pastdagi \"ko'p chiqish kunlari\" jadvalidagi postlarni ko'rib chiqing: shunday mavzu va ohangni takrorlamang.")
    # Umumiy (doim foydali) amaliyotlar.
    tips.append("Har hafta bitta interaktiv post qiling: so'rovnoma, savol-javob yoki o'quvchi ishini baholash — "
                "faol ishtirok etgan obunachi kamdan-kam chiqib ketadi.")
    tips.append("Muntazam jadval: bir xil kunlar va soatlarda post qiling (\"Tavsiyalar\"dagi eng yaxshi soatlar), "
                "uzoq tanaffus va keyin ketma-ket ko'p post — ikkalasi ham chiqishni ko'paytiradi.")
    return tips
