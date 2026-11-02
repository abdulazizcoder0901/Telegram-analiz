import json
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


class VercelFunctionTests(unittest.TestCase):
    def test_run(self):
        import importlib.util
        from unittest import mock

        spec = importlib.util.spec_from_file_location("api_analyze", Path(__file__).parent.parent / "api" / "analyze.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        page = (FIX / "channel_page.html").read_text(encoding="utf-8")
        with mock.patch("telegram_analiz.scraper.fetch_page", lambda c, b, timeout=10: page if b is None else ""):
            status, ctype, body = mod.run({"channel": ["@test_academy"], "limit": ["100"]})
            self.assertEqual(status, 200)
            self.assertIn("Test Academy", body)
            self.assertIn("Boshqa kanal", body)
            status, ctype, body = mod.run({"channel": ["test_academy"], "format": ["json"]})
            self.assertEqual(json.loads(body)["channel"]["total_views"], 5410)
        self.assertEqual(mod.run({})[0], 400)
        self.assertEqual(mod.run({"channel": ["a b"]})[0], 400)
