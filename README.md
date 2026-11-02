# Telegram analiz

Telegram **kanallari** va **chatlari** uchun statistika va tahlil vositasi.
Faqat Python standart kutubxonasidan foydalanadi: `pip install` ham, API kalit ham kerak emas.

Ikki xil manba bilan ishlaydi:

| Manba | Nima beradi |
|---|---|
| **Ochiq kanal** (`@kanal` yoki `t.me/kanal`) | ko'rishlar soni, ERR, reaksiyalar, eng yaxshi soat, TOP postlar, post turlari samaradorligi, tavsiyalar |
| **Telegram Desktop eksporti** (`result.json`) | guruh/shaxsiy chat: ishtirokchilar, faollik, javob tezligi, so'zlar, media |

## O'rnatish

Python 3.10+ kerak.

```bash
git clone https://github.com/abdulazizcoder0901/Telegram-analiz.git
cd Telegram-analiz
```

Ixtiyoriy: `telegram-analiz` buyrug'ini o'rnatish uchun `pip install -e .`.

## 1. Ochiq kanalni tahlil qilish

```bash
python -m telegram_analiz @junior_academy --tz +5 --html junior_academy.html --json junior_academy.json
```

* `--limit 2000` — nechta oxirgi postni yig'ish (standart 1000)
* `--tz +5` — vaqtlarni Toshkent vaqtida ko'rsatish (standart: kompyuteringiz vaqt zonasi)
* `--delay 1` — sahifalar orasidagi pauza (Telegram cheklamasligi uchun)

Ma'lumot `https://t.me/s/<kanal>` ochiq veb-sahifasidan olinadi, shuning uchun faqat
**ochiq (public)** kanallar ishlaydi va internetda `t.me` ochilishi kerak.

**Oflayn variant:** brauzerda `https://t.me/s/junior_academy` sahifasini oching, pastga
aylantiring, `Ctrl+S` bilan saqlang:

```bash
python -m telegram_analiz --saved-html sahifa.html --name junior_academy --tz +5 --html hisobot.html
```

### Kanal hisobotida nimalar bor

* Obunachilar, o'rtacha/mediana/maks ko'rishlar, **ERR** (o'rtacha ko'rish ÷ obunachilar)
* Reaksiya darajasi (reaksiyalar ÷ ko'rishlar)
* Chiqarilgan **soat** va **hafta kuni** bo'yicha o'rtacha ko'rish (eng yaxshi vaqt)
* **Post turi** (rasm, video, matn, so'rovnoma…) va **matn uzunligi** bo'yicha samaradorlik
* Oylar bo'yicha ko'rishlar trendi (oxirgi 2 kundagi "pishmagan" postlarsiz)
* Eng ko'p / eng kam ko'rilgan va eng ko'p reaksiya olgan postlar (havolalari bilan)
* Heshteglar, @eslatmalar, havola domenlari, ko'p ishlatilgan so'zlar, emoji
* Avtomatik **tavsiyalar**

## 2. Chat eksportini tahlil qilish

Telegram Desktop → chat → ⋮ → **Export chat history** → Format: **Machine-readable JSON**.

```bash
python -m telegram_analiz ~/Downloads/Telegram\ Desktop/ChatExport_2026-11-02/result.json --html chat.html
```

To'liq akkaunt eksporti (Settings → Advanced → Export Telegram data) ham ishlaydi:

```bash
python -m telegram_analiz result.json --list
```

```bash
python -m telegram_analiz result.json --chat "Guruh nomi" --html guruh.html
```

## Natijalar

* **Konsol** — qisqa matnli hisobot
* `--html FAYL` — grafiklar bilan bitta faylli hisobot (oflayn ochiladi, qorong'i rejim bor)
* `--json FAYL` — barcha raqamlar, boshqa vositalarda ishlatish uchun

## Testlar

```bash
python -m unittest discover -s tests -v
```

## Loyiha tuzilishi

```
telegram_analiz/
  loader.py    — result.json o'qish (oddiy va to'liq eksport)
  scraper.py   — t.me/s/<kanal> sahifalaridan postlarni yig'ish
  analyzer.py  — statistika va tavsiyalar
  report.py    — konsol / HTML / JSON hisobot
  cli.py       — buyruq qatori
tests/         — testlar va sun'iy namunaviy ma'lumotlar
```
