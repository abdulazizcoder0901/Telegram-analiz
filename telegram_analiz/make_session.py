"""Vercel uchun Telegram sessiya kalitini (TG_SESSION) yaratish.

O'z kompyuteringizda ishga tushiring:

    pip install telethon
    python -m telegram_analiz.make_session

Telefon raqam, Telegram yuborgan kod (va 2FA paroli, agar yoqilgan bo'lsa) shu yerda,
terminalda so'raladi — hech kimga, jumladan chatga ham yubormang. Oxirida chiqqan uzun
satrni Vercel → telegram-analiz → Settings → Environment Variables ga TG_SESSION nomi bilan
qo'shing (TG_API_ID va TG_API_HASH bilan birga).

Bu kalit akkauntingizga to'liq kirish beradi. Kerak bo'lmay qolsa: Telegram → Sozlamalar →
Qurilmalar → shu sessiyani "Tugatish" — kalit darhol ishlamay qoladi.
"""

from __future__ import annotations

import getpass
import os
import sys


def main() -> int:
    try:
        from telethon.sessions import StringSession
        from telethon.sync import TelegramClient
    except ImportError:
        print("Avval o'rnating: pip install telethon", file=sys.stderr)
        return 1

    api_id = os.environ.get("TG_API_ID") or input("api_id (my.telegram.org): ").strip()
    api_hash = os.environ.get("TG_API_HASH") or getpass.getpass("api_hash (ko'rinmaydi): ").strip()
    with TelegramClient(StringSession(), int(api_id), api_hash,
                        device_model="Junior Telegram dashboard") as client:
        me = client.get_me()
        session = client.session.save()
    print(f"\nKirildi: {me.first_name or ''} (@{me.username or '—'})\n")
    print("Vercel → Settings → Environment Variables ga qo'shing:\n")
    print(f"  TG_API_ID   = {api_id}")
    print("  TG_API_HASH = (my.telegram.org dagi api_hash)")
    print(f"  TG_SESSION  = {session}\n")
    print("TG_SESSION ni hech kimga bermang va chatga yozmang.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
