import json
import os
from urllib.parse import parse_qs, urlparse
import tempfile
import unittest
from pathlib import Path

from telegram_analiz import analyze, load_chats, select_chat
from telegram_analiz.cli import main
from telegram_analiz.loader import ExportError, flatten_text
from telegram_analiz.report import to_html, to_text
from telegram_analiz.scraper import normalize_channel, parse_count, parse_page, parse_tz, scrape_channel

FIX = Path(__file__).parent / "fixtures"


class ScraperTests(unittest.TestCase):
    def setUp(self):
        self.page = (FIX / "channel_page.html").read_text(encoding="utf-8")

    def test_normalize_channel(self):
        for raw in ["@junior_academy", "junior_academy", "https://t.me/junior_academy",
                    "t.me/s/junior_academy/123", "https://telegram.me/junior_academy?x=1"]:
            self.assertEqual(normalize_channel(raw), "junior_academy")
        with self.assertRaises(ExportError):
            normalize_channel("a b")

    def test_parse_count(self):
        self.assertEqual(parse_count("1.2K"), 1200)
        self.assertEqual(parse_count("2,1K"), 2100)
        self.assertEqual(parse_count("3.4M"), 3_400_000)
        self.assertEqual(parse_count("860"), 860)
        self.assertEqual(parse_count("12 345"), 12345)
        self.assertIsNone(parse_count("abc"))

    def test_timezone(self):
        posts, _ = parse_page(self.page, "test_academy", parse_tz("+5"))
        self.assertEqual(posts[0].date.isoformat(), "2026-10-01T14:15:00")
        posts, _ = parse_page(self.page, "test_academy", parse_tz("UTC"))
        self.assertEqual(posts[0].date.isoformat(), "2026-10-01T09:15:00")
        with self.assertRaises(ExportError):
            parse_tz("Mars/Olympus")

    def test_parse_page(self):
        posts, info = parse_page(self.page, "test_academy")
        self.assertEqual(info["title"], "Test Academy")
        self.assertEqual(info["subscribers"], 2500)
        self.assertIn("Sinov kanali & dasturlash\nKurslar", info["description"])
        self.assertEqual([p.id for p in posts], [101, 102, 103, 104])
        first, second, third, fourth = posts
        self.assertEqual(first.views, 1200)
        self.assertEqual(first.media_type, "photo")
        self.assertEqual(first.reactions, {"👍": 45, "🔥": 12})
        self.assertIn("Python kursi boshlandi! 🚀\nRo'yxatdan", first.text)
        self.assertEqual(first.link, "https://t.me/test_academy/101")
        self.assertFalse(first.edited)
        self.assertEqual(second.media_type, "video_file")
        self.assertEqual(second.forwarded_from, "Other Channel")
        self.assertTrue(second.edited)
        self.assertEqual(third.media_type, "poll")
        self.assertEqual(third.views, 2100)
        self.assertEqual(third.reply_to, 101)
        self.assertEqual(third.reactions, {"✨ maxsus": 3, "⭐": 2})
        self.assertEqual(fourth.media_type, "unsupported")
        self.assertEqual(fourth.views, 1250)
        self.assertEqual(fourth.text, "")

    def test_scrape_paginates_and_stops(self):
        calls = []

        def fake_fetch(channel, before):
            calls.append(before)
            return self.page if before is None else "<html></html>"

        chat = scrape_channel("@test_academy", delay=0, fetch=fake_fetch)
        self.assertEqual(calls, [None, 101])
        self.assertEqual({m.sender for m in chat.messages}, {"Test Academy"})
        self.assertEqual(chat.subscribers, 2500)
        self.assertEqual(len(chat.messages), 4)

    def test_scrape_missing_channel(self):
        with self.assertRaises(ExportError):
            scrape_channel("nonexistent_ch", delay=0, fetch=lambda c, b: "<html></html>")

    def test_channel_analysis(self):
        posts, info = parse_page(self.page, "test_academy")
        from telegram_analiz.loader import Chat
        chat = Chat("Test Academy", "public_channel", None, posts, "test_academy", None, info["subscribers"])
        r = analyze(chat)
        ch = r["channel"]
        self.assertEqual(ch["total_views"], 1200 + 860 + 2100 + 1250)
        self.assertEqual(ch["max_views"], 2100)
        self.assertEqual(ch["top_posts"][0]["id"], 103)
        self.assertAlmostEqual(ch["err_pct"], round(100 * round(5410 / 4) / 2500, 1))
        self.assertIn(["python", 1], [[k, v] for k, v in r["content"]["top_words"]])
        self.assertIn(["#python", 1], r["content"]["top_hashtags"])
        self.assertIn(["@mentor_uz", 1], r["content"]["top_mentions"])
        domains = dict(r["content"]["top_domains"])
        self.assertEqual(domains.get("example.uz"), 1)
        self.assertEqual(domains.get("youtube.com"), 1)
        self.assertIn("Tavsiyalar".upper()[:3], to_text(r).upper())
        self.assertIn("<svg", to_html(r))


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.chat = select_chat(load_chats(FIX / "export.json"), None)

    def test_flatten_text(self):
        self.assertEqual(flatten_text(["a ", {"type": "bold", "text": "b"}]), "a b")
        self.assertEqual(flatten_text(None), "")

    def test_load(self):
        self.assertEqual(self.chat.name, "Sinov guruhi")
        self.assertEqual(len(self.chat.messages), 10)
        self.assertEqual(self.chat.messages[2].text, "Salom Ali qalaysan?")

    def test_analysis(self):
        r = analyze(self.chat)
        t = r["totals"]
        self.assertEqual(t["messages"], 9)
        self.assertEqual(t["service_messages"], 1)
        self.assertEqual(t["participants"], 2)
        self.assertEqual(t["span_days"], 3)
        self.assertEqual(t["longest_streak"]["days"], 3)
        self.assertEqual(t["forwarded"], 1)
        self.assertEqual(t["edited"], 1)
        self.assertEqual(t["reactions"], 2)
        senders = {s["name"]: s for s in r["senders"]}
        self.assertEqual(senders["Ali"]["messages"], 5)
        self.assertEqual(senders["Vali"]["replies"], 1)
        self.assertEqual(dict(r["content"]["top_words"])["python"], 2)
        media = dict(r["content"]["media"])
        self.assertEqual(media["Ovozli xabar"], 1)
        self.assertEqual(media["Rasm"], 1)
        self.assertNotIn("channel", r)
        self.assertIn("Ali", r["response_times"])

    def test_full_export_and_select(self):
        data = json.loads((FIX / "export.json").read_text(encoding="utf-8"))
        small = dict(data, name="Kichik", id=7, messages=data["messages"][:2])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "result.json"
            p.write_text(json.dumps({"chats": {"list": [small, data]}}), encoding="utf-8")
            chats = load_chats(d)
            self.assertEqual(len(chats), 2)
            self.assertEqual(select_chat(chats, None).name, "Sinov guruhi")
            self.assertEqual(select_chat(chats, "kichik").name, "Kichik")
            with self.assertRaises(ExportError):
                select_chat(chats, "yo'q")

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            html_path, json_path = Path(d) / "r.html", Path(d) / "r.json"
            code = main([str(FIX / "export.json"), "--quiet", "--html", str(html_path), "--json", str(json_path)])
            self.assertEqual(code, 0)
            self.assertIn("Sinov guruhi", html_path.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["totals"]["messages"], 9)
            self.assertEqual(main(["--saved-html", str(FIX / "channel_page.html"), "--quiet"]), 0)
            self.assertEqual(main([str(Path(d) / "missing.json")]), 1)


if __name__ == "__main__":
    unittest.main()


def _load_api():
    import importlib.util
    spec = importlib.util.spec_from_file_location("api_analyze", Path(__file__).parent.parent / "api" / "analyze.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class VercelFunctionTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load_api()
        self.page = (FIX / "channel_page.html").read_text(encoding="utf-8")
        self.calls = []

        def fake_fetch(channel, before, timeout=10):
            self.calls.append(before)
            return self.page if before is None else ""

        self.mod.fetch_page = fake_fetch

    def test_dashboard_html(self):
        status, ctype, body, headers = self.mod.run({"preset": ["all"]})
        self.assertEqual(status, 200)
        self.assertRegex(headers["Cache-Control"], r"s-maxage=\d+$")
        self.assertIn("data-next=", body)
        self.assertEqual(self.mod.DEFAULT_CHANNEL, "junior_academy")
        self.assertIn("Junior: Telegram", body)
        self.assertIn("↻ Yangilash", body)
        import html as _h
        text = _h.unescape(body)
        for label in ("Bugun", "Kecha", "7 kun", "14 kun", "30 kun", "Shu oy", "O'tgan oy",
                      "O'tgan oyda shu sana", "Oyni tanlang", "Ko'rsatish"):
            self.assertIn(label, text)
        self.assertEqual(body.count("class='pill on'"), 0)  # "all" tugmalar orasida yo'q
        self.assertNotIn("<h1>Test Academy", body)
        # "Asosiy" va "Tavsiyalar" bo'limlari; tavsiyalar asosiy qismda takrorlanmaydi
        self.assertIn("id='tab-main'", body)
        self.assertIn("id='tab-tips'", body)
        main_part = body.split("<section id='p-main'")[1].split("</section>")[0]
        tips_part = body.split("<section id='p-tips'")[1].split("</section>")[0]
        self.assertNotIn("<h2>Tavsiyalar</h2>", main_part)
        self.assertIn("<h2>Tavsiyalar</h2>", tips_part)
        self.assertEqual(self.mod.run({"channel": ["a b"]})[0], 400)
        self.assertEqual(self.mod.slot_start(1200 * 5 + 7), 1200 * 5)

    def test_json_and_cache(self):
        status, _, body, _ = self.mod.run({"from": ["2026-10-01"], "to": ["2026-10-03"], "format": ["json"]})
        data = json.loads(body)
        self.assertEqual(data["channel"]["total_views"], 5410)
        self.assertEqual(data["filters"]["compare"], {"from": "2026-09-28", "to": "2026-09-30", "available": True})
        self.assertEqual(data["compare"]["totals"]["messages"], 0)
        n = len(self.calls)
        self.mod.run({"month": ["2026-10"], "type": ["poll"], "format": ["json"]})
        self.assertEqual(len(self.calls), n, "keshdan olinishi kerak")
        # "Yangilash": qaytadan yig'adi va ?v=<olingan vaqt> ga yo'naltiradi
        status, _, _, headers = self.mod.run({"preset": ["7"], "refresh": ["123"], "v": ["1"]})
        self.assertEqual(status, 302)
        self.assertGreater(len(self.calls), n)
        loc = headers["Location"]
        self.assertIn("preset=7", loc)
        self.assertNotIn("refresh", loc)
        v = int(parse_qs(urlparse(loc).query)["v"][0])
        n = len(self.calls)
        _, _, body, _ = self.mod.run({"preset": ["14"], "v": [str(v)]})
        self.assertEqual(len(self.calls), n, "shu v uchun yangi kesh ishlatiladi")
        self.assertIn(f"v={v}", body)  # tugmalar v ni olib yuradi
        # kesh "v" dan eski bo'lsa — qayta yig'iladi
        self.mod._CACHE[("junior_academy", "+5")]["fetched"] = v - 5
        self.mod.run({"preset": ["14"], "v": [str(v)]})
        self.assertGreater(len(self.calls), n)
        # yangi 20 daqiqalik oraliq boshlansa — qayta yig'iladi
        n = len(self.calls)
        self.mod._CACHE[("junior_academy", "+5")]["fetched"] -= 1300
        self.mod.run({"preset": ["14"]})
        self.assertGreater(len(self.calls), n)

    def test_dashboard_with_comparison(self):
        status, _, body, _ = self.mod.run({"from": ["2026-10-01"], "to": ["2026-10-03"]})
        self.assertEqual(status, 200)
        self.assertIn("class='d", body)  # KPI ostida o'zgarish qatori
        self.assertIn("solishtirish <b>", body)
        self.assertIn("id='p-tips'", body)

    def test_filters(self):
        _, _, body, _ = self.mod.run({"month": ["2026-10"], "type": ["poll"], "format": ["json"]})
        data = json.loads(body)
        self.assertEqual(data["filters"]["posts_shown"], 1)
        self.assertEqual(data["channel"]["total_views"], 2100)
        status, _, body, _ = self.mod.run({"preset": ["all"], "type": ["text"]})
        self.assertEqual(status, 200)
        self.assertIn("Postlar topilmadi", body)


class FilterTests(unittest.TestCase):
    def setUp(self):
        from telegram_analiz.loader import Chat
        posts, info = parse_page((FIX / "channel_page.html").read_text(encoding="utf-8"), "test_academy", parse_tz("UTC"))
        self.chat = Chat("Test Academy", "public_channel", None, posts, "test_academy", None, info["subscribers"])

    def test_parse_filters(self):
        from telegram_analiz.filters import parse_filters
        f = parse_filters("30")
        self.assertEqual((f.period, f.types), ("30", []))
        self.assertEqual(parse_filters("bogus").period, "all")
        f = parse_filters("7", "2026-10-03", "2026-10-01", ["all", "photo", "photo"])
        self.assertEqual(f.period, "custom")
        self.assertEqual((str(f.date_from), str(f.date_to)), ("2026-10-01", "2026-10-03"))
        self.assertEqual(f.types, ["photo"])

    def test_apply_period_and_type(self):
        from datetime import date
        from telegram_analiz.filters import apply_filters, coverage_warning, parse_filters, type_options
        today = date(2026, 10, 3)
        ids = lambda f: [m.id for m in apply_filters(self.chat, f, today).messages]
        self.assertEqual(ids(parse_filters("all")), [101, 102, 103, 104])
        self.assertEqual(ids(parse_filters(None, "2026-10-02", "2026-10-02")), [102])
        self.assertEqual(ids(parse_filters("all", types=["text"])), [])
        self.assertEqual(ids(parse_filters("all", types="poll")), [103])
        self.assertEqual(ids(parse_filters("7", types=["photo", "video_file"])), [101, 102])
        self.assertIsNotNone(coverage_warning(self.chat, parse_filters("30"), today))
        self.assertIsNone(coverage_warning(self.chat, parse_filters("all"), today))
        self.assertEqual({k for k, _, _ in type_options(self.chat)}, {"photo", "video_file", "poll", "unsupported"})

    def test_presets_and_comparison(self):
        from datetime import date
        from telegram_analiz.filters import format_range, parse_filters, shift_month
        today = date(2026, 11, 3)
        f = parse_filters("this_month")
        self.assertEqual(f.bounds(today), (date(2026, 11, 1), today))
        self.assertEqual(f.comparison(today), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(format_range(*f.bounds(today), today), "1–3-noy")
        self.assertEqual(format_range(*f.comparison(today), today), "1–31-okt")
        f = parse_filters("7")
        self.assertEqual(f.comparison(today), (date(2026, 10, 21), date(2026, 10, 27)))
        f = parse_filters("yesterday")
        self.assertEqual(f.bounds(today), (date(2026, 11, 2), date(2026, 11, 2)))
        f = parse_filters(None, month="2026-09")
        self.assertEqual(f.bounds(today), (date(2026, 9, 1), date(2026, 9, 30)))
        self.assertEqual(f.comparison(today), (date(2026, 8, 1), date(2026, 8, 31)))
        f = parse_filters("last_month")
        self.assertEqual(f.bounds(today), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(shift_month(date(2026, 3, 31)), date(2026, 2, 28))
        self.assertEqual(format_range(date(2026, 10, 28), date(2026, 11, 3), today), "28-okt – 3-noy")
        self.assertEqual(format_range(date(2025, 12, 1), date(2025, 12, 1), today), "1-dek 2025")
        # aniq sana oy va presetdan ustun
        self.assertEqual(parse_filters("7", "2026-10-01", None, month="2026-09").period, "custom")


def _fake_admin_stats():
    """Telegram stats.getBroadcastStats grafik formatidagi sun'iy ma'lumot (2026-09-28 — 2026-11-01)."""
    from datetime import date, datetime, timedelta, timezone
    days = [date(2026, 9, 28) + timedelta(days=i) for i in range(35)]
    xs = [int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000) for d in days]
    joined = [10 + (i % 5) for i in range(35)]
    left = [4 + (i % 3) for i in range(35)]
    total, totals = 5000, []
    for j, lft in zip(joined, left):
        total += j - lft
        totals.append(total)
    return {
        "channel": "@test_academy",
        "graphs": {
            "growth_graph": {"columns": [["x", *xs], ["y0", *totals]], "names": {"y0": "Total followers"}},
            "followers_graph": {"columns": [["x", *xs], ["y0", *joined], ["y1", *left]],
                                "names": {"y0": "Joined", "y1": "Left"}},
        },
        "enabled_notifications": {"part": 30, "total": 100},
    }, days, joined, left, totals


class AdminStatsTests(unittest.TestCase):
    def test_month_summary(self):
        from datetime import date
        from telegram_analiz.admin_stats import daily_series, month_summary, parse_month
        raw, days, joined, left, totals = _fake_admin_stats()
        series = daily_series(raw)
        self.assertEqual(len(series), 35)
        start, end = parse_month("2026-10")
        s = month_summary(series, start, end)
        oct_idx = [i for i, d in enumerate(days) if d.month == 10]
        self.assertTrue(s["complete"])
        self.assertEqual(s["start_total"], totals[oct_idx[0] - 1])  # 30-sentabr oxiridagi son
        self.assertFalse(s["start_estimated"])
        self.assertEqual(s["end_total"], totals[oct_idx[-1]])
        self.assertEqual(s["joined"], sum(joined[i] for i in oct_idx))
        self.assertEqual(s["left"], sum(left[i] for i in oct_idx))
        self.assertEqual(s["total_change"], s["joined"] - s["left"])
        self.assertEqual(s["mismatch"], 0)
        self.assertEqual(len(s["days"]), 31)
        self.assertEqual(parse_month(None, date(2026, 11, 2)), (date(2026, 10, 1), date(2026, 10, 31)))
        with self.assertRaises(ExportError):
            month_summary(series, *parse_month("2025-01"))
        with self.assertRaises(ExportError):
            parse_month("oktabr")

    def test_partial_month_and_estimated_start(self):
        from telegram_analiz.admin_stats import daily_series, month_summary, parse_month
        raw, days, joined, left, totals = _fake_admin_stats()
        s = month_summary(daily_series(raw), *parse_month("2026-11"))
        self.assertFalse(s["complete"])
        self.assertEqual(s["to"], "2026-11-01")
        s = month_summary(daily_series(raw), *parse_month("2026-09"))
        self.assertTrue(s["start_estimated"])
        self.assertEqual(s["start_total"], totals[0] - (joined[0] - left[0]))

    def test_cli_from_json(self):
        from telegram_analiz.admin_stats import main as admin_main
        raw, *_ = _fake_admin_stats()
        with tempfile.TemporaryDirectory() as d:
            src, out_html, out_json = Path(d) / "raw.json", Path(d) / "o.html", Path(d) / "o.json"
            src.write_text(json.dumps(raw), encoding="utf-8")
            self.assertEqual(admin_main(["--from-json", str(src), "--month", "2026-10",
                                         "--html", str(out_html), "--json", str(out_json)]), 0)
            page = out_html.read_text(encoding="utf-8")
            self.assertIn("Oy boshida", page)
            self.assertIn("<svg", page)
            self.assertEqual(json.loads(out_json.read_text(encoding="utf-8"))["month"], "2026-10")
            self.assertEqual(admin_main(["--from-json", str(src), "--month", "2024-01"]), 1)


class FakeRedis:
    """Upstash REST API'ga o'xshatilgan soxta server (urllib opener o'rniga)."""

    def __init__(self):
        self.data = {}

    def __call__(self, request, timeout=None):
        import io
        cmd = json.loads(request.data.decode("utf-8"))
        if cmd[0] == "HSET":
            h = self.data.setdefault(cmd[1], {})
            for k, v in zip(cmd[2::2], cmd[3::2]):
                h[k] = v
            result = len(cmd[2:]) // 2
        elif cmd[0] == "HGETALL":
            result = [x for kv in self.data.get(cmd[1], {}).items() for x in kv]
        else:
            result = None

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return R(json.dumps({"result": result}).encode())


class FollowersTests(unittest.TestCase):
    def test_history_store_roundtrip_and_merge(self):
        from datetime import date
        from telegram_analiz.history import HistoryStore, merge, store_from_env
        fake = FakeRedis()
        store = HistoryStore("https://x.upstash.io", "t", opener=fake)
        store.save("@Junior_Academy", {date(2026, 10, 1): {"total": 6000, "joined": 5, "left": 2}})
        loaded = store.load("junior_academy")
        self.assertEqual(loaded, {date(2026, 10, 1): {"total": 6000, "joined": 5, "left": 2}})
        merged = merge(loaded, {date(2026, 10, 1): {"total": 6001, "joined": None, "left": 3},
                                date(2026, 10, 2): {"total": 6004, "joined": 4, "left": 1}})
        self.assertEqual(merged[date(2026, 10, 1)], {"total": 6001, "joined": 5, "left": 3})
        self.assertEqual(len(merged), 2)
        self.assertIsNone(store_from_env({}))
        self.assertIsNotNone(store_from_env({"KV_REST_API_URL": "u", "KV_REST_API_TOKEN": "t"}))
        s2 = store_from_env({"STORAGE_REST_API_URL": "https://s", "STORAGE_REST_API_TOKEN": "t2"})
        self.assertEqual((s2.url, s2.token), ("https://s", "t2"))
        self.assertIsNone(store_from_env({"STORAGE_REST_API_URL": "https://s"}))

    def _api(self, configured=True, fail=False):
        from unittest import mock
        mod = _load_api()
        page = (FIX / "channel_page.html").read_text(encoding="utf-8")
        mod.fetch_page = lambda channel, before, timeout=10: page if before is None else ""
        raw, *_ = _fake_admin_stats()
        raw["followers"] = {"current": 5237, "previous": 5292}
        raw["views_per_post"] = {"current": 1000, "previous": 1408}
        xs = raw["graphs"]["followers_graph"]["columns"][0]
        raw["graphs"]["new_followers_by_source_graph"] = {
            "columns": [xs, ["y0", *[2] * (len(xs) - 1)], ["y1", *[1] * (len(xs) - 1)]],
            "names": {"y0": "Search", "y1": "Channels"}}

        def fake_fetch(channel):
            if fail:
                raise RuntimeError("tarmoq xatosi")
            return raw
        mod.fetch_admin = fake_fetch
        env = {"TG_API_ID": "1", "TG_API_HASH": "h", "TG_SESSION": "s" * 100} if configured else {}
        return mod, mock.patch.dict(os.environ, env, clear=False), raw

    def test_not_configured(self):
        mod, env, _ = self._api(configured=False)
        with env:
            for k in ("TG_API_ID", "TG_API_HASH", "TG_SESSION"):
                os.environ.pop(k, None)
            _, _, body, _ = mod.run({"month": ["2026-10"]})
        self.assertIn("hali ulanmagan", body)

    def test_followers_block(self):
        mod, env, raw = self._api()
        with env:
            _, _, body, _ = mod.run({"month": ["2026-10"]})
            _, _, js, _ = mod.run({"month": ["2026-10"], "format": ["json"]})
        f = json.loads(js)["followers"]
        self.assertEqual(f["from"], "2026-10-01")
        self.assertIsNotNone(f["start_total"])
        self.assertEqual(f["total_change"], f["joined"] - f["left"])
        import html as _h
        text = _h.unescape(body)
        for label in ("Obunachilar", "Oy boshida", "Qo'shildi", "Chiqib ketdi", "Sof o'zgarish",
                      "Bildirishnoma yoqilgan", "Post boshiga ko'rish", "Har kuni qo'shilgan va chiqib ketgan",
                      "Kunlar bo'yicha jadval", "Yangi obunachilar qayerdan keldi", "Search"):
            self.assertIn(label, text)
        self.assertIn("−55 (1.04%)", text)  # Telegram'dagidek o'zgarish
        main_part = body.split("<section id='p-main'")[1]
        self.assertLess(main_part.index("class='followers'"), main_part.index("<h2 class='sec'>Postlar</h2>"))

    def test_admin_error_does_not_break_dashboard(self):
        mod, env, _ = self._api(fail=True)
        with env:
            status, _, body, _ = mod.run({"month": ["2026-10"]})
        self.assertEqual(status, 200)
        self.assertIn("Telegram statistikasini olib bo", body)
        self.assertIn("id='tab-tips'", body)
