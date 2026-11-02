"""Buyruq qatori interfeysi.

Misollar:
    python -m telegram_analiz @junior_academy --html hisobot.html
    python -m telegram_analiz result.json --chat "Guruh nomi" --json stats.json
    python -m telegram_analiz --saved-html sahifa1.html sahifa2.html --name junior_academy
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analyzer import analyze
from .loader import ExportError, load_chats, select_chat
from .report import to_html, to_json, to_text
from .scraper import load_saved_html, normalize_channel, parse_tz, scrape_channel


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="telegram-analiz",
        description="Telegram kanal/chat tahlili: ochiq kanal (@nom yoki t.me havola) "
        "yoki Telegram Desktop eksporti (result.json).",
    )
    p.add_argument("source", nargs="?", help="@kanal, t.me/kanal havolasi yoki result.json / eksport papkasi")
    p.add_argument("--saved-html", nargs="+", metavar="FAYL", help="brauzerda saqlangan t.me/s sahifalari")
    p.add_argument("--name", help="--saved-html uchun kanal nomi (@siz)")
    p.add_argument("--chat", help="to'liq eksportdan chat nomi yoki ID (bo'lmasa eng kattasi)")
    p.add_argument("--list", action="store_true", help="eksportdagi chatlar ro'yxatini ko'rsatish")
    p.add_argument("--limit", type=int, default=1000, help="kanaldan nechta oxirgi postni olish (standart 1000)")
    p.add_argument("--delay", type=float, default=1.0, help="sahifalar orasidagi pauza, soniya")
    p.add_argument("--tz", help="kanal vaqtlari uchun vaqt zonasi, masalan +5 yoki Asia/Tashkent "
                   "(standart: kompyuter vaqt zonasi)")
    p.add_argument("--top", type=int, default=10, help="TOP ro'yxatlar uzunligi")
    p.add_argument("--html", metavar="FAYL", help="HTML hisobotni saqlash")
    p.add_argument("--json", metavar="FAYL", help="to'liq statistikani JSON qilib saqlash")
    p.add_argument("--quiet", action="store_true", help="konsolga hisobot chiqarmaslik")
    return p


def _looks_like_channel(source: str) -> bool:
    if Path(source).exists():
        return False
    return source.startswith("@") or "t.me/" in source or "telegram.me/" in source or (
        not source.endswith(".json") and "/" not in source and "\\" not in source
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        tz = parse_tz(args.tz)
        if args.saved_html:
            raw = args.name or args.source
            name = normalize_channel(raw) if raw else "kanal"
            chat = load_saved_html(args.saved_html, name, tz)
        elif not args.source:
            build_parser().print_help()
            return 2
        elif _looks_like_channel(args.source):
            name = normalize_channel(args.source)
            print(f"@{name} kanalidan postlar yig'ilmoqda…", file=sys.stderr)
            chat = scrape_channel(
                name,
                max_posts=args.limit,
                delay=args.delay,
                progress=lambda n: print(f"  {n} ta post", file=sys.stderr),
                tz=tz,
            )
        else:
            chats = load_chats(args.source)
            if args.list:
                for c in sorted(chats, key=lambda c: -len(c.messages)):
                    print(f"{len(c.messages):>8}  {c.type:<18} {c.name}  (id={c.id})")
                return 0
            chat = select_chat(chats, args.chat)
    except ExportError as exc:
        print(f"Xato: {exc}", file=sys.stderr)
        return 1

    result = analyze(chat, top_n=args.top)
    if not args.quiet:
        print(to_text(result, top_n=args.top))
    if args.html:
        Path(args.html).write_text(to_html(result), encoding="utf-8")
        print(f"\nHTML hisobot: {args.html}", file=sys.stderr)
    if args.json:
        Path(args.json).write_text(to_json(result), encoding="utf-8")
        print(f"JSON: {args.json}", file=sys.stderr)
    return 0
