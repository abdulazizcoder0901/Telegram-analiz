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
* `--period 30` yoki `--from 2026-01-01 --to 2026-03-31` — davr bo'yicha filtr
* `--type video_file` — post turi bo'yicha filtr (`text`, `photo`, `video_file`, `video_message`, `poll`, …; takrorlash mumkin)

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

## Veb-versiya (Vercel)

Sayt ochilganda (`/`) to'g'ridan-to'g'ri **@junior_academy** dashboardi chiqadi
(`api/analyze.py` dagi `DEFAULT_CHANNEL`). Boshqa kanal: `/api/analyze?channel=@kanal&limit=300&tz=+5`,
JSON uchun `&format=json`.
Hisobot tepasida filtrlar bor: davr (7/30/90/365 kun yoki sanalar), post turi va yig'iladigan postlar soni
(`&period=30`, `&from=2026-01-01&to=2026-03-31`, `&type=photo`).
Vercel funksiyasi 60 soniya bilan cheklangani uchun veb-versiya oxirgi 600 tagacha postni tahlil qiladi.

```bash
npx vercel deploy --prod
```

## Obunachilar: qo'shilgan, chiqib ketgan, oy boshi/oxiri (admin uchun)

Bu ma'lumot ochiq sahifada yo'q — faqat kanal adminlariga Telegram statistikasida ko'rinadi.
Shuning uchun o'z akkauntingiz bilan **o'z kompyuteringizda** ishga tushirasiz:

1. https://my.telegram.org → **API development tools** → `api_id` va `api_hash` oling.
2. Telethon'ni o'rnating:

```bash
pip install telethon
```

3. Ishga tushiring (birinchi marta telefon raqam va Telegram yuborgan kod so'raladi):

```bash
python -m telegram_analiz.admin_stats @junior_academy --month 2026-10 --api-id 12345 --api-hash abcdef... --html obunachilar.html --save-json admin_stats.json
```

Natija: oy boshidagi va oxiridagi obunachilar, qo'shilganlar, chiqib ketganlar, sof o'zgarish,
chiqib ketish foizi, kunlik grafik va jadval. `--save-json` bilan saqlangan fayldan keyin
login qilmasdan boshqa oylarni ham ko'rish mumkin: `--from-json admin_stats.json --month 2026-09`.

* Akkauntingiz kanalda **admin** bo'lishi kerak.
* `telegram_analiz.session` fayli akkauntingizga kirish kalitidir — hech kimga bermang, GitHub'ga yuklamang
  (`.gitignore` da bor).
* Telegram statistikasi odatda oxirgi bir necha oyni qamraydi; eski oylar bo'lmasligi mumkin.

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
