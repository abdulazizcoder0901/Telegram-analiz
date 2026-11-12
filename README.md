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
* `--period 30` (`this_month`, `last_month`, `7`, `14`…), `--month 2026-10` yoki `--from 2026-01-01 --to 2026-03-31` — davr bo'yicha filtr
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
Tepada panel: Bugun / Kecha / 7 / 14 / 30 kun / Shu oy / O'tgan oy / "O'tgan oyda shu sana" tugmalari,
oy tanlash, sanalar oralig'i, post turi va **↻ Yangilash**. Ko'rsatkichlar solishtirish davriga nisbatan
↑/↓ bilan chiqadi (shu oy → o'tgan oy, oy → oldingi oy, N kun → oldingi N kun).
URL parametrlari: `preset=7|14|30|today|yesterday|this_month|last_month|all`, `month=2026-10`,
`from=2026-10-01&to=2026-10-15`, `type=photo`, `refresh=1`.

Ma'lumot har 20 daqiqada (:00, :20, :40) yangilanadi; ochiq sahifa ham shu vaqtda o'zi qayta yuklanadi.
**↻ Yangilash** postlarni shu zahoti qaytadan yig'adi va `?v=<vaqt>` ga yo'naltiradi — shundan keyingi
barcha tugma va filtrlar aynan shu yangi ma'lumotni ko'rsatadi.
Sayt tanlangan davr va solishtirish davrini qamrash uchun kerakli postlarni o'zi yig'adi
(bitta so'rovda ~45 soniya, 2 500 tagacha post).

```bash
npx vercel deploy --prod
```

## Obunachilar statistikasi saytda (Vercel)

Saytning "Asosiy" bo'limi tepasida **Obunachilar** qismi: hozirgi son (Telegram'dagidek o'zgarish bilan),
oy/davr boshida va oxirida, qo'shilgan, chiqib ketgan, sof o'zgarish, bildirishnoma yoqilganlar,
post boshiga ko'rish/ulashish/reaksiya, jami obunachilar grafigi, kunlik qo'shilgan/chiqqan grafigi
va jadvali, yangi obunachilar manbasi. Ma'lumot Telegram admin statistikasidan har 20 daqiqada olinadi.

Sozlash (bir marta):

1. https://my.telegram.org → **API development tools** → `api_id` va `api_hash`.
2. O'z kompyuteringizda sessiya kalitini yarating (telefon kodi shu yerda so'raladi):

```bash
pip install telethon
```

```bash
python -m telegram_analiz.make_session
```

3. Vercel → **telegram-analiz → Settings → Environment Variables** ga qo'shing:
   `TG_API_ID`, `TG_API_HASH`, `TG_SESSION` (Production). Keyin **Redeploy**.
4. Tarixni saqlash uchun (ixtiyoriy, tavsiya etiladi): Vercel → **Storage → Create Database →
   Upstash for Redis** (bepul) → loyihaga ulang. Kunlik raqamlar shu bazaga yozib boriladi.

`TG_SESSION` akkauntingizga kirish kalitidir: hech kimga bermang. Bekor qilish: Telegram →
Sozlamalar → Qurilmalar → "Junior Telegram dashboard" → Tugatish.

### Oy boshidagi son o'zgarmaydi

Telegram eski kunlardagi jami obunachilar sonini keyinroq tuzatib turadi (masalan, o'chirilgan
akkauntlar). Shuning uchun har oyning boshidagi son birinchi hisoblanganda bazaga
(`tg:<kanal>:month_start:<YYYY-MM>`) bir marta yoziladi va keyin o'zgarmaydi; sof o'zgarish
"oy oxiri − qotirilgan oy boshi" bo'yicha hisoblanadi.

"Oy boshida" kartochkasi har doim ko'rinadi (sayt standart holatda **Shu oy** bilan ochiladi; boshqa davr
tanlansa, yonida alohida "Davr boshida" chiqadi). Kartochkadagi **✎ Tuzatish** orqali sonni qo'lda kiritish
mumkin (Telegram'ning hozirgi hisobi taklif sifatida ko'rsatiladi); **Avtomatikka qaytarish** qo'lda
kiritilganni o'chirib, sonni qayta hisoblatadi. `PLAN_PASSWORD` qo'yilgan bo'lsa, parol so'raladi.

### Yangi va eski auditoriya

"Qo'shildi" va "Chiqib ketdi" kartochkalari bosilsa, tafsilot alohida oynada (modal) ochiladi:

* **Qo'shilganlar:** birinchi marta qo'shilganlar / qaytganlar (oldin chiqib ketgan), va ulardan
  keyin chiqib ketganlar soni va foizi.
* **Chiqib ketganlar:** shu davrda qo'shilganlar (yangi auditoriya) / eski obunachilar (davrdan oldin
  qo'shilgan) / noma'lum.

Manba — kanalning "So'nggi harakatlar" (admin log) jurnali: kim qachon qo'shilgan va chiqqan.
Telegram uni faqat 48 soat saqlaydi, shuning uchun sayt jurnalni yig'ib, Upstash'da saqlab boradi
(`tg:<kanal>:members`; obunachi ID'lari faqat HMAC-xesh ko'rinishida, ism/username saqlanmaydi).
Sayt ochilmasa ham har kuni bir marta yig'ish uchun `vercel.json` da cron bor. Kuzatuv boshlanishidan
oldin qo'shilganlar "noma'lum" bo'ladi; to'liq ajratish kuzatuv boshlangan keyingi oydan.

## Plan bo'limi (sayt)

"Asosiy" va "Tavsiyalar" orasidagi **Plan** bo'limida har oy uchun maqsadlar kiritiladi va fakt bilan
solishtiriladi: fakt / plan, bajarilish foizi, bugungacha qayerda bo'lish kerakligi, holat
(Oldinda / Rejada / Orqada), farq, kuniga qancha kerak va oy oxiri prognozi.

* Avtomatik fakt: qo'shilgan / chiqib ketgan obunachilar, sof o'sish, oy oxiridagi obunachilar
  (admin statistikasi), postlar soni, ko'rishlar, o'rtacha ko'rish, reaksiyalar.
* Qo'lda: "Boshqa" ko'rsatkichlar (masalan, **Sifatli lidlar**) — plan va faktni o'zingiz yozasiz.
* Planlar Upstash bazasida saqlanadi (`/api/plan`), shuning uchun baza ulangan bo'lishi kerak.
* Sayt ochiq bo'lgani uchun Vercel'ga `PLAN_PASSWORD` qo'yishni tavsiya qilamiz: shunda planni faqat
  parolni bilgan kishi o'zgartiradi (ko'rish hammaga ochiq qoladi).

## Obunachilar: qo'shilgan, chiqib ketgan, oy boshi/oxiri (admin uchun, buyruq qatori)

Bu ma'lumot ochiq sahifada yo'q — faqat kanal adminlariga Telegram statistikasida ko'rinadi.
Shuning uchun o'z akkauntingiz bilan **o'z kompyuteringizda** ishga tushirasiz:

1. https://my.telegram.org → **API development tools** → `api_id` va `api_hash` oling.
2. Telethon o'rnatilgan bo'lsin (`pip install telethon`).
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
