"""Esse (yozma ish)ni tekshirish xizmati — to'g'ridan-to'g'ri OpenAI API orqali.

Oqim:
  1. Oddiy (kod bilan tekshiriladigan) shartlar — AI'ga umuman yuborilmaydi:
       - yozilmagan / bo'sh -> 0 ball
       - 100 so'zdan kam -> 2 ball (avtomatik, tahlilsiz)
  2. Shu shartlarga tushmasa -> OpenAI'ga to'liq 12 bandli rasmiy mezon
     (barcha 5 daraja tavsifi bilan) VA har bir band bo'yicha juda batafsil,
     qattiq tekshiruv qoidalari (grammatik istisnolar, hallucination taqig'i,
     "qora ro'yxat" va h.k.) yuboriladi. AI har bir banddan 0/0.5/1/1.5/2 ball
     qo'yadi HAMDA har bir banddagi ANIQ xatolarni (mavjud bo'lsa) sanab
     beradi. 24 ballik yig'indi olinib, rasmiy jadval orqali 75 ballikka
     o'tkaziladi (scoring.py).
  3. Natija (har band bo'yicha ball + aniq xatolar + ogohlantirishlar +
     umumiy izoh) `format_evaluation_messages()` orqali talabgorga
     yuboriladigan tayyor HTML xabar(lar)ga aylantiriladi.

Ishlatish uchun: Railway'da (yoki .env'da) OPENAI_API_KEY'ni qo'ying.
Boshqa hech narsa sozlash shart emas — bu fayl to'g'ridan-to'g'ri
https://api.openai.com/v1/chat/completions'ga so'rov yuboradi.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx

from bot.config import settings
from bot.services.scoring import (
    AUTO_REJECT_SCORE_24,
    AUTO_ZERO_SCORE_24,
    MIN_ESSAY_WORDS,
    convert_essay_24_to_75,
)

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


class NotConfiguredError(RuntimeError):
    """OPENAI_API_KEY sozlanmagan bo'lsa ko'tariladi."""


class AutoRejectReason:
    NOT_WRITTEN = "yozilmagan"
    TOO_SHORT = "100 so'zdan kam"


@dataclass
class EssayGradeResult:
    criteria_scores: dict[str, float] | None  # None bo'lsa avto-rad qilingan (yozilmagan/qisqa)
    total_score_24: float
    converted_score_75: int
    auto_reject_reason: str | None
    feedback: str | None = None  # umumiy_izoh
    band_errors: dict[str, list[str]] | None = None  # {"1": ["xato — to'g'risi: ..."], ...}
    warnings: list[str] = field(default_factory=list)  # ball kesmaydigan ogohlantirishlar


def count_words(text: str) -> int:
    return len([w for w in text.split() if w.strip()])


# --------------------------------------------------------------------------- #
# Rasmiy 12 bandli mezon — har biri 5 daraja tavsifi bilan TO'LIQ.
# Manba: "Yozma ish (esse)ni baholash mezoni" rasmiy hujjati.
# Har bir band: 2 / 1.5 / 1 / 0.5 / 0 ball darajalari.
# --------------------------------------------------------------------------- #
CRITERIA_RUBRIC = """
JAMI 12 BAND, HAR BIRI 0 DAN 2 BALLGACHA (0 / 0.5 / 1 / 1.5 / 2), JAMI MAKSIMAL 24 BALL.

TOPSHIRIQ TALABLARINING BAJARILGANLIGI:

1-band — Uslub:
  2: Esse to'liq publitsistik uslubda yozilgan.
  1.5: Ayrim o'rinlarda publitsistik uslubdan chekinilgan.
  1: Esse qisman publitsistik uslubda yozilgan.
  0.5: Esse to'liq badiiy uslubda yozilgan.
  0: Esse to'liq so'zlashuv uslubida yozilgan.

2-band — Vaziyat yuzasidan qarashlar va shaxsiy fikr:
  2: Har ikkala qarash hamda talabgorning shaxsiy qarashlari to'la yoritilgan.
  1.5: Har ikkala qarash yoritilgan, talabgorning shaxsiy fikri yoritilmagan.
  1: Qarashlarning bittasi to'la yoritilgan.
  0.5: Qarashlarning faqat bittasi qisman yoritilgan.
  0: Qarashlar yoritilmagan.

3-band — Dalillash:
  2: Har ikkala qarash dalillar bilan asoslangan.
  1.5: Faqat bitta qarash dalillangan.
  1: Har ikkala qarash uchun keltirilgan ayrim dalillar vaziyatga mos emas.
  0.5: Har ikkala qarash uchun keltirilgan dalillar vaziyatga mos emas.
  0: Har ikkala qarash dalillanmagan.

MATN YAXLITLIGI (NUTQ KOMPOZITSIYASI, NUTQNING MANTIQIYLIGI):

4-band — Kirish/asosiy qism/xulosa:
  2: Kirish, asosiy qism va xulosa to'la yoritib berilgan.
  1.5: Esse qismlaridan faqat ikkitasi to'la yoritilgan.
  1: Esse qismlaridan ikkitasi yuza yoritilgan.
  0.5: Esse qismlaridan faqat bittasi to'la yoritilgan.
  0: Esse qismlaridan faqat bittasi yuza yoritilgan.

5-band — Mantiqiy qurilish va xatboshilar:
  2: Mantiqiy qurilishda xatolik kuzatilmagan, xatboshilarga to'g'ri ajratilgan.
  1.5: Mantiqiy qurilishda yoki xatboshilarga ajratishda 1-2 o'rinda xatolik.
  1: Mantiqiy qurilishda yoki xatboshilarga ajratishda 3-4 o'rinda xatolik.
  0.5: Mantiqiy qurilishda yoki xatboshilarga ajratishda 5-6 o'rinda xatolik.
  0: Mantiqiy qurilishda 7 va undan ko'p o'rinda xatolik, xatboshilarga umuman ajratilmagan.

6-band — Mantiqiy-mazmuniy izchillik:
  2: To'liq rioya qilingan, fikrlar takrori kuzatilmagan.
  1.5: Fikrlar takrori 1-2 o'rinda, izchillik buzilmagan.
  1: Fikrlar takrori 3-4 o'rinda, izchillik buzilgan.
  0.5: Fikrlar takrori 5-6 o'rinda, izchillik buzilgan.
  0: Fikrlar takrori 7 va undan ortiq o'rinda, izchillik buzilgan.

SAVODXONLIK (NUTQNING TO'G'RILIGI):

7-band — Imlo:
  2: Imlo xatoligi umuman yo'q.
  1.5: Imlo xatoligi 1-2 o'rinda.
  1: Imlo xatoligi 3-4 o'rinda.
  0.5: Imlo xatoligi 5-6 o'rinda.
  0: Imlo xatoligi 7 va undan ortiq o'rinda.

8-band — Punktuatsiya:
  2: Punktuatsion xatolik umuman yo'q.
  1.5: 1-2 o'rinda.
  1: 3-4 o'rinda.
  0.5: 5-6 o'rinda.
  0: 7 va undan ortiq o'rinda.

TIL BIRLIKLARI USLUBIYATI (NUTQNING JO'YALILIGI):

9-band — Qo'shimcha qo'llash:
  2: Xatolik umuman yo'q.
  1.5: 1-2 o'rinda xatolik.
  1: 3-4 o'rinda xatolik.
  0.5: 5-6 o'rinda xatolik.
  0: 7 va undan ortiq o'rinda xatolik.

10-band — So'z qo'llash bilan bog'liq uslubiy xatolar (so'zni noto'g'ri qo'llash,
noo'rin takrorlash, ortiqcha qo'llash, tushirib qoldirish, bog'lovchi/kiritma bilan
bog'liq xatolik):
  2: Kuzatilmagan.
  1.5: 1-2 o'rinda.
  1: 3-4 o'rinda.
  0.5: 5-6 o'rinda.
  0: 7 va undan ko'p o'rinda.

LUG'AT BOYLIGI (NUTQNING BOYLIGI, IFODALILIGI VA SOFLIGI):

11-band — Leksik xilma-xillik:
  2: Tasviriy ifodalar, maxsus leksik birliklar, barqaror birikmalardan unumli foydalanilgan.
  1.5: Shulardan ayrim o'rinlarda foydalanilgan.
  1: Foydalanilgan, lekin ayrim o'rinlarda noo'rin foydalanilgan.
  0.5: Leksik xilma-xillik kuzatilmagan, noo'rin foydalanilgan.
  0: Leksik xilma-xillik kuzatilmagan, umuman foydalanilmagan.

12-band — Sheva so'zlari, vulgarizm, varvarizm, parazit so'zlar:
  2: Umuman uchramaydi.
  1.5: 1-2 o'rinda uchragan, uslubiy g'alizlik yuzaga kelmagan.
  1: 3-4 o'rinda uchragan, uslubiy g'alizlik yuzaga kelgan.
  0.5: 5-6 o'rinda uchragan, uslubiy g'alizlik yuzaga kelgan.
  0: 7 va undan ko'p o'rinda uchragan, uslubiy g'alizlik yuzaga kelgan.

ESSE YOZILISHIGA QO'YILADIGAN TALABLAR (baholashda hisobga oling):
  - Fikr-mulohazalar publitsistik uslubda bayon qilinishi kerak.
  - Fikrlar mantiqiy izchillikda, adabiy til me'yorlariga amal qilgan holda ifodalanishi kerak.
  - Berilgan vaziyat matni aynan ko'chirilmasligi kerak.
  - Esse uch qismdan iborat bo'lishi kerak: kirish, asosiy qism, xulosa.
  - Esse uchun reja tuzilmaydi, epigraf qo'yilmaydi.
""".strip()

# Har bir band nomi — talabgorga yuboriladigan xabarda sarlavha sifatida ishlatiladi
BAND_TITLES: dict[str, str] = {
    "1": "Uslub",
    "2": "Vaziyat yuzasidan qarashlar va shaxsiy fikr",
    "3": "Dalillash",
    "4": "Kirish/asosiy qism/xulosa",
    "5": "Mantiqiy qurilish va xatboshilar",
    "6": "Mantiqiy-mazmuniy izchillik",
    "7": "Imlo",
    "8": "Punktuatsiya",
    "9": "Qo'shimcha qo'llash",
    "10": "So'z qo'llash bilan bog'liq uslubiy xatolar",
    "11": "Leksik xilma-xillik",
    "12": "Sheva so'zlari, vulgarizm, varvarizm, parazit so'zlar",
}

# --------------------------------------------------------------------------- #
# AI'ga yuboriladigan tizim ko'rsatmasi — juda batafsil, aniq va qattiq
# tekshiruv qoidalari bilan (grammatik istisnolar, hallucination taqig'i,
# hyperkorreksiya taqig'i va h.k.). "%%RUBRIC%%" o'rniga yuqoridagi
# CRITERIA_RUBRIC matni qo'yiladi.
# --------------------------------------------------------------------------- #
_SYSTEM_TEMPLATE = """Sen O'zbekiston Milliy Sertifikat (Attestatsiya) tizimida ona tili va adabiyot fanidan yoziladigan ESSE (yozma ish)ni rasmiy mezon asosida baholovchi ekspertsan. Sen juda tajribali, ammo AYNI PAYTDA juda ANIQ, XOLIS va CHUQUR tahlil qiluvchi ekspertsan — hech qachon sust/yuzaki tekshiruv qilmaysan, hech qachon xato "o'ylab topmaysan" (hallucinate qilmaysan), faqat essening o'zida haqiqatan mavjud bo'lgan narsani xato deb belgilaysan. Har bir xatoni topganda "aynan shu so'z/jumlani shunday yozib xato qildingiz" tarzda ANIQ ko'rsating.

Quyida to'liq rasmiy baholash mezoni berilgan:

%%RUBRIC%%

=== A) KIRISH QISMI TUZILISHI (1, 2, 4, 5-bandlar uchun muhim) ===

To'g'ri kirish 3 qismdan iborat bo'lishi kerak:
1. UMUMIY GAP — mavzu mavzusini umumiy tarzda tanishtiruvchi jumla. MUHIM: bu gap mavhum/mantiqsiz shiorlar bilan boshlanmasligi kerak — masalan "Zamin shiddat bilan rivojlanmoqda", "Globallashuv zamonida" kabi umumiy, mavzuga bevosita bog'lanmagan jumlalar bilan boshlanishi MANTIQIY XATO hisoblanadi. Bunday xatolarni 5-band (mantiqiy qurilish)da aniq ko'rsat.
   Yaxshi namunalar: "Hozirda an'anaviy va zamonaviy [mavzu] masalasi kishilar orasida bahslarga sabab bo'lmoqda", "Bugungi kunda [mavzu] haqida turlicha fikrlar mavjud", "[Mavzu] hayotimizning ajralmas qismiga aylangan."
2. MAVZUNI QAYTA ISHLASH (PARAFRAZ) — berilgan vaziyat matni/mavzusi so'zma-so'z ko'chirilmasdan, xuddi shu mazmunni boshqacha so'zlar va gap qurilishi bilan ifodalashi kerak. Agar talabgor mavzu matnini deyarli aynan ko'chirgan bo'lsa — buni 5-band yoki umumiy izohda ta'kidla.
   MUHIM GRAMMATIK XATO: ikkala tomonni bog'lashda "sa" va "esa" qo'shimchasini BIRGA ishlatish xato (masalan "Ayrimlar telefon ijobiy desa, boshqalar esa foydali deydi" — bu noto'g'ri, chunki "desa" va "esa" ikkalasi ham qarama-qarshilik bildiruvchi vosita, ikkalasini birga ishlatish ortiqcha/noto'g'ri qurilish). To'g'ri variant: "Ayrimlar telefon ijobiy desa, boshqalar salbiy deydi" YOKI "Ayrimlar telefonni ijobiy deydi, boshqalar esa salbiy deydi" (faqat bittasi ishlatilsin). Bu xatoni albatta 5-band (gap qurilishi)da izlab top va ko'rsat.
3. TEZIS (IXTIYORIY, majburiy emas — bo'lmasa xato emas) — masalan "Ushbu esseda shu haqida fikr yuritamiz", "Mazkur esseda shu haqida ko'rib chiqamiz" kabi.

=== B) ASOSIY QISM TUZILISHI (2, 3, 4-bandlar uchun muhim) ===

Asosiy qism kamida 3 ta xatboshidan iborat bo'lishi kerak (1-tomon fikri, 2-tomon fikri, shaxsiy fikr — yoki shunga yaqin taqsimot). Har bir band tahlilida quyidagilarni tekshir:

- Xatboshi ochilishi (indent/yangi qatordan boshlanishi) borligini tekshir.
- Xatboshi maqol bilan boshlansa — bu xato EMAS agar maqol mazmunga mos bo'lsa. Agar maqol mos kelmasa yoki sun'iy qo'shilgan bo'lsa, buni izchillik (6-band) xatosi sifatida ko'rsat.
- Har bir tomon uchun avvalo QAYSI FIKR BOSHLANAYOTGANI haqida ishora bo'lishi kerak (masalan "Ayrimlar telefonni ijobiy deydi va fikrlarini quyidagicha dalillaydi" kabi kirish jumlasi). "Birinchidan, ikkinchidan" shart emas — "avvaliga", "keyingisi", "bundan tashqari" kabi so'zlar ham bo'ladi.
- HAR BIR TOMON UCHUN QUYIDAGI STRUKTURANI QIDIR: FIKR (aniq da'vo/pozitsiya) + IZOH/SABAB (nima uchun shu fikr to'g'ri ekanini tushuntirish) + DALIL (buni tasdiqlovchi aniq isbot). Dalil quyidagilardan biri bo'lishi mumkin: statistika, tadqiqot natijasi, tajriba, mutaxassislar fikri, universitet tadqiqotlari, sayt/gazeta/jurnal ma'lumotlari, YOKI jamiyat hayotidan olingan hayotiy misol.
  MUHIM: bitta tomon uchun BITTA yaxshi rivojlantirilgan fikr+izoh+dalil ZANJIRI YETARLI (2 ball uchun to'liq hisoblanadi), ikkitasi bo'lsa yanada yaxshi, lekin shart emas. Asosiysi — izchillik va mavzuga aloqadorlik.
  Agar biror tomonda faqat FAKT/TAVSIF berilib (masalan "bu kanal 15 yildan buyon ishlaydi"), lekin bu FAKTNING NIMA UCHUN YAXSHI/FOYDALI ekanligi (fikr+izoh) ochib berilmagan bo'lsa — bu YETARLI DALIL EMAS, chunki shunchaki ma'lumot berilgan, mulohaza yuritilmagan. Bunday holatda 2-band va 3-bandda ballni pasaytir va buni aniq tushuntir.
  ESLATMA: dalilning matn ichidagi joylashuvi qat'iy emas — muhimi, gap o'zidan oldingi gapga mantiqan bog'langan, izchil ekanligi. Statistik raqamning "haqiqiyligini" tekshirish shart emas — faqat uning matn ichida mantiqan o'rinli ishlatilganini bahola.

=== C) SHAXSIY FIKR (2-band uchun) ===

Shaxsiy fikr QISQA bo'lishi kerak — aniq BITTA tomon tanlanishi kifoya (masalan "Menimcha, ..."). Xohlasa 1-2 ta qisqa sabab qo'shishi mumkin, lekin bu shart emas. MUHIM: 3-band (dalillanganlik) mezoni FAQAT ikkala tomonning dalillariga tegishli — shaxsiy fikr uchun alohida dalil talab qilinmaydi, shaxsiy fikrning o'zi (aniq tomon tanlash) yetarli.

=== D) XULOSA QISMI (2, 4-bandlar uchun) ===

Xulosa maqol bilan boshlanishi mumkin (ixtiyoriy, bo'lmasa xato emas). MUHIM: xulosa NEYTRAL/BALANSLANGAN bo'lmasligi kerak — talabgor shaxsiy fikrida tanlagan tomonning ustunligini ANIQ va OCHIQ tarzda yozib yakunlashi kerak (masalan "har ikkala tarafning fikri o'rinli, lekin ... tomon ustunroq" kabi). Agar xulosa faqat ikkala tomonni tenglashtirib, hech qanday tomon afzalligini bildirmasdan tugasa — buni 2-band yoki umumiy izohda kamchilik sifatida ko'rsat.
MUHIM ANIQLIK: xulosaning shaxsiy fikrda tanlangan tomon bilan MOS/O'XSHASH bo'lishi — bu XATO EMAS, aksincha TALAB QILINGAN va TO'G'RI holat. Buni 4-bandda yoki boshqa bandda kamchilik sifatida ko'rsatma. FAQAT agar xulosa va shaxsiy fikr bo'limlari SO'ZMA-SO'Z AYNAN bir xil gaplardan iborat bo'lsa — buni 6-band (fikrlar takrori)da xato sifatida ko'rsat, 4-bandda emas.

=== E) SAVODXONLIK — CHUQUR VA QATTIQ TEKSHIRUV (7, 8, 9, 10-bandlar) ===

Bu bandlarni SUST/YUZAKI emas, CHUQUR tekshir — har bir jumlani diqqat bilan o'qib chiq:
- Imlo (7-band): so'zlarning noto'g'ri yozilishini top (apostrof variantlari bundan mustasno — pastda tushuntiriladi).
- Punktuatsiya (8-band): vergul, nuqta, tire va boshqa belgilarning noto'g'ri/yetishmasligini top (vergüldan keyingi bo'shliq bundan mustasno). AYNIQSA tekshir: haqiqiy KIRISH SO'ZLARIDAN (modal/diskurs so'zlari — masalan "demak", "xullas", "afsuski", "shubhasiz", "albatta" kabi, gap boshida alohida mustaqil kirish sifatida kelganda) keyin vergul QO'YILISHI SHART.
  MUHIM ISTISNO: "natijada", "oqibatda" kabi so'zlar odatiy RAVISH (ergash gap bo'lagi) sifatida ishlatilganda, ular kirish so'z EMAS — bunday hollarda ulardan keyin vergul talab qilinMAYDI, vergul bo'lmasligi XATO EMAS.
- Qo'shimcha xatolari (9-band): kelishik qo'shimchalarining noto'g'ri ishlatilishini AYNIQSA diqqat bilan tekshir — masalan qaratqich/tushum kelishigi chalkashtirilishi keng tarqalgan xato: "ning" o'rniga "ni" ishlatilishi, yoki egalik qo'shimchasi xatosi.
  MUHIM ISTISNO — IZOFA TURI 2: o'zbek tilida ikki ot yonma-yon kelib, birinchisi "-ning" qo'shimchasisiz umumiy/tur ma'nosini bildirishi TO'LIQ TO'G'RI — masalan "davlat bog'i", "shahar hokimi", "hudud ob-havosi" kabi qurilmalar TO'G'RI, ularga "-ning" YETISHMAYAPTI deb hech qachon xato qo'yma.
- Uslubiy xato (10-band): so'zni noto'g'ri qo'llash, noo'rin takrorlash, ortiqcha qo'llash, tushirib qoldirish, bog'lovchi vositalar bilan bog'liq xato.
  MUHIM — ORTIQCHA QATTIQQO'LLIKDAN SAQLAN (hyperkorreksiya taqiqlanadi): faqat haqiqiy xatoni xato deb ko'rsat. Agar asl ibora grammatik jihatdan to'g'ri va keng qo'llanadigan bo'lsa — buni faqat sen "yanada chiroyliroq" variant taklif qila olishing sababli xato deb ko'rsatish TAQIQLANADI.
- Qo'pol, varvar, sheva so'zlarni AYNIQSA diqqat bilan qidir (12-band).

=== F) IZCHILLIK VA MAVZUGA ALOQADORLIK (6-band) ===

Har bir gap/xatboshi MAVZUGA bevosita aloqadorligini albatta tekshir. Agar biror gap mavzudan chetga chiqsa — buni 6-band (izchillik)da aniq xato sifatida ko'rsat.

=== G) LEKSIK XILMA-XILLIK — KENGAYTIRILGAN MEZON (11-band) ===

Sinonimlardan foydalanish, neologizm/o'zlashma so'zlarning o'rinli qo'llanishi, maqol/ibora/barqaror birikmalar — barchasi IJOBIY omil.

=== H) MAXSUS HOLAT: 2 BALL BILAN BAHOLASH ===

Agar esse to'liq mavzudan chetga chiqib ketgan bo'lsa YOKI talabgor mavzuni umuman tushunmagan bo'lib chiqsa — rasmiy mezonga ko'ra JAMI 2 BALL beriladi (barcha bandlar bo'yicha juda past ball qo'yish orqali).

=== MUHIM QO'SHIMCHA QOIDALAR ===

1) APOSTROF/HARF VARIANTLARI ("o'", "oʻ", "o'", "o'", "ŏ", "ò" va h.k., xuddi shunday "g'" variantlari) HECH QANDAY BANDDA XATO EMAS — bu qoida 1 dan 12 gacha BARCHA bandlarga taalluqli. Boshqa bandga yashirib jarima qilish ham TAQIQLANADI.

1-B) TIRE VARIANTLARI ("-", "–", "—") HAM XATO EMAS — texnik farq.

2) VERGULDAN KEYIN BO'SHLIQ YO'QLIGI hech qanday bandda ball kesmaydi.

3) MAQOL/IBORA 1-bandga (uslub) TA'SIR QILMAYDI.

4) XATONI TO'QIMA (hallucination qilma) — faqat real mavjud xatoni ko'rsat.

5) BIR XIL XATO TAKRORLANSA — BITTA holat sifatida hisobla, "N marta takrorlangan" deb yoz.

6) Har bandda MAVZUGA ALOQADORLIKNI tekshir.

7) YAQIN SO'Z TAKRORI — 6 yoki 10-bandda ko'rsat.

8) Gap bog'lovchi bilan mustaqil boshlansa — 5-bandda xato, qo'shma gap tavsiya etiladi.
   MUHIM ISTISNO: "Chunki" bilan gap boshlanishi XATO EMAS — o'zbek tilida to'liq me'yoriy holat.

10) IMLO (7-band) — MEXANIK TEKSHIRUV: har so'zni solishtir, xususan "fikr"→"fikir", "sabr"→"sabir", "umr"→"umur", "shukr"→"shukur", "hukm"→"hukum" kabi unli orttirish xatolarini qidir.

11) O'ZINI TEKSHIRISH — MAJBURIY: har xatoni yozishdan oldin "essede aynan shu bormi?" deb so'ra, aks holda yozma.

12) 8-bandda vergul-bo'shliqni umuman yozma.

13) 3-BAND (DALILLANGANLIK) — ENG MUHIM TEKSHIRUV: ikkala tomonda FIKR+IZOH+DALIL borligini tekshir. Agar biror tomonda faqat FAKT SANAB O'TILGAN bo'lsa (masalan "bu telekanal N yildan buyon ishlaydi" — bu shunchaki tavsif, DALIL EMAS) — 3-bandga hech qachon to'liq 2 ball qo'yilmasin (kamida 1 yoki 1.5, holatga qarab pastroq).

14) CHUQUR MANTIQIY-MAZMUNIY TEKSHIRUV: Har bir FIKR+IZOH+DALIL zanjirini tekshir:
   a) FIKR mavzuning aynan shu tomoniga tegishlimi?
   b) IZOH haqiqatan FIKRni oqlaydimi (sabab-natija bog'lanishi)?
   c) DALIL aynan shu IZOHni tasdiqlaydimi?
   d) Butun zanjir mantiqiy chiziqni saqlaydimi?
   Uzilish bo'lsa — tegishli bandda (3, 5 yoki 6) ko'rsat.

15) "GAP TOMONNI OCHISHGA XIZMAT QILMAYDI" TURIDAGI XATO — 6-BAND: Agar biror gap o'zi joylashgan xatboshidagi tomonni rivojlantirishga hech qanday hissa qo'shmasa — buni 6-band xatosi sifatida ko'rsat. Format: "'[gap]' jumlasi [1/2]-tomonni ochishga xizmat qilmaydi — bu gap mavzuga/tomonga aloqasiz yoki ortiqcha."

=== YAKUNIY QORA RO'YXAT ===

Javobni yuborishdan oldin tekshir — bular HECH QACHON paydo bo'lmasin: maqol sababli 1-band pasaytirilishi, vergul-bo'shliq xato deb ko'rsatilishi, harf variantlari xato deb ko'rsatilishi, "to'g'risi" asl so'z bilan bir xil bo'lishi, xulosa-shaxsiy fikr mosligi xato deb ko'rsatilishi, 3-bandga sust tekshirib to'liq ball berilishi, izofa turi 2 qurilmalariga "-ning" yetishmayapti deb xato ko'rsatilishi, "natijada"/"oqibatda"dan keyin vergul yo'qligi xato deb ko'rsatilishi, tutuq belgisi/tire variantlari xato deb ko'rsatilishi, 10-bandda faqat "chiroyliroq" bahonasi bilan xato ko'rsatilishi, "Chunki" bilan boshlangan gap xato deb ko'rsatilishi.

=== JAVOB FORMATI ===

Javobni FAQAT quyidagi JSON formatida qaytar, hech qanday qo'shimcha matn yozma:

{
  "bands": [
    {"number": 1, "ball": 1.5, "xatolar": ["Xato — to'g'risi: tuzatilgan variant"]},
    ... (1 dan 12 gacha, HAMMASI bo'lishi shart)
  ],
  "ogohlantirishlar": ["Ball kesmaydigan eslatmalar"],
  "umumiy_izoh": "2-4 jumlalik umumiy xulosa"
}

- "ball": faqat 2, 1.5, 1, 0.5, 0.
- Xato yo'q bo'lsa xatolar ro'yxatida "Xatolik aniqlanmadi" deb yoz.
- Har xato 30 so'zdan oshmasin.
- Javob HECH QACHON 12 banddan kam bo'lmasin."""

SYSTEM_INSTRUCTIONS = _SYSTEM_TEMPLATE.replace("%%RUBRIC%%", CRITERIA_RUBRIC)


def _build_prompt(text: str, topic: str, word_count: int) -> list[dict]:
    user = f"""ESSE MAVZUSI: {topic}

TALABGOR YOZGAN ESSE MATNI ({word_count} so'z):
\"\"\"
{text}
\"\"\"

Yuqoridagi barcha qoidalarga QAT'IY rioya qilib, esseni 12 band bo'yicha batafsil tahlil qil va FAQAT belgilangan JSON formatida javob ber."""
    return [
        {"role": "system", "content": SYSTEM_INSTRUCTIONS},
        {"role": "user", "content": user},
    ]


async def grade_essay(text: str | None, topic: str) -> EssayGradeResult:
    """Asosiy kirish nuqtasi: esseni tekshirib, EssayGradeResult qaytaradi."""
    if not text or not text.strip():
        return EssayGradeResult(
            criteria_scores=None,
            total_score_24=AUTO_ZERO_SCORE_24,
            converted_score_75=0,
            auto_reject_reason=AutoRejectReason.NOT_WRITTEN,
        )

    word_count = count_words(text)
    if word_count < MIN_ESSAY_WORDS:
        return EssayGradeResult(
            criteria_scores=None,
            total_score_24=AUTO_REJECT_SCORE_24,
            converted_score_75=convert_essay_24_to_75(AUTO_REJECT_SCORE_24),
            auto_reject_reason=AutoRejectReason.TOO_SHORT,
        )

    return await grade_with_openai(text=text, topic=topic, word_count=word_count)


async def grade_with_openai(text: str, topic: str, word_count: int) -> EssayGradeResult:
    if not settings.openai_api_key:
        raise NotConfiguredError(
            "OPENAI_API_KEY sozlanmagan. Railway'da (yoki .env'da) OPENAI_API_KEY "
            "muhit o'zgaruvchisini qo'ying — boshqa hech narsa kerak emas."
        )

    # Railway'da OPENAI_MODEL o'zgaruvchisi bo'sh qatorga o'rnatilgan bo'lsa ham
    # (masalan avval yaratilgan-u to'ldirilmagan bo'lsa), OpenAI'ga bo'sh model
    # nomi yuborilib "400 Bad Request" bermasligi uchun standart (arzon)
    # qiymatga qaytamiz.
    model = settings.openai_model.strip() or "gpt-4o-mini"

    payload = {
        "model": model,
        "messages": _build_prompt(text, topic, word_count),
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        # Xarajatni nazorat qilish uchun javob uzunligiga chegara — 12 band +
        # xatolar + izohlar odatda bundan ancha kam sig'adi, lekin narxni
        # nazoratsiz oshirib yubormasligi uchun xavfsizlik chegarasi qo'yamiz.
        "max_tokens": 3000,
    }
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(OPENAI_CHAT_URL, json=payload, headers=headers)
        resp.raise_for_status()
        raw = resp.json()

    content = raw["choices"][0]["message"]["content"]
    data = json.loads(content)

    allowed = [0, 0.5, 1, 1.5, 2]
    clean_scores: dict[str, float] = {}
    band_errors: dict[str, list[str]] = {}

    for band_data in data.get("bands", []):
        try:
            number = str(int(band_data.get("number")))
        except (TypeError, ValueError):
            continue
        if number not in [str(i) for i in range(1, 13)]:
            continue
        val = float(band_data.get("ball", 0) or 0)
        val = max(0.0, min(2.0, val))
        clean_scores[number] = min(allowed, key=lambda a: abs(a - val))
        errors = band_data.get("xatolar") or []
        band_errors[number] = [str(e).strip() for e in errors if str(e).strip()] or ["Xatolik aniqlanmadi"]

    # Modelning javobida biror band tushib qolgan bo'lsa ham tizim yiqilmasin —
    # yetishmagan bandlarga 0 ball va ogohlantiruvchi izoh bilan to'ldiramiz.
    for i in range(1, 13):
        key = str(i)
        if key not in clean_scores:
            clean_scores[key] = 0.0
            band_errors[key] = ["Model javobida bu band topilmadi (texnik xatolik)"]

    total_24 = round(sum(clean_scores.values()), 2)
    warnings = [str(w).strip() for w in (data.get("ogohlantirishlar") or []) if str(w).strip()]

    return EssayGradeResult(
        criteria_scores=clean_scores,
        total_score_24=total_24,
        converted_score_75=convert_essay_24_to_75(total_24),
        auto_reject_reason=None,
        feedback=data.get("umumiy_izoh"),
        band_errors=band_errors,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Talabgorga yuboriladigan batafsil (12 bandlik) natija xabari
# --------------------------------------------------------------------------- #

# Telegram xabar chegarasi 4096 belgi — xavfsizlik uchun pastroq chegara olamiz,
# shunda bir nechta xabarga bo'linsa ham har biri kafolatlangan holda yetadi.
_MAX_TG_MESSAGE_LEN = 3500


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------- #
# 12 bandni rasmiy mezonning o'zidagi 5 ta tabiiy guruhga birlashtiramiz.
# Talabgorga aniq band raqami/ball emas — guruh darajasida Yaxshi/O'rtacha/Zaif
# ko'rsatiladi, chunki band-band aniq iqtibos (xato matnini keltirish) o'quvchi
# tomonidan e'tirozlarga sabab bo'lyapti. Bu yerda ESSE MATNIDAN HECH QANDAY
# IQTIBOS ishlatilmaydi — faqat qaysi guruhga ko'proq e'tibor kerakligi
# umumiy tarzda ko'rsatiladi.
# --------------------------------------------------------------------------- #
_GROUPS: list[tuple[str, str, list[str]]] = [
    ("1️⃣", "Topshiriq talablari (uslub, qarashlar, dalillash)", ["1", "2", "3"]),
    ("2️⃣", "Matn yaxlitligi (kirish, asosiy qism, xulosa, mantiqiy qurilish)", ["4", "5", "6"]),
    ("3️⃣", "Savodxonlik (imlo, punktuatsiya)", ["7", "8"]),
    ("4️⃣", "Til birliklari uslubiyati", ["9", "10"]),
    ("5️⃣", "Lug'at boyligi", ["11", "12"]),
]


def _group_label(avg: float) -> str:
    if avg >= 1.6:
        return "Yaxshi"
    if avg >= 0.9:
        return "O'rtacha"
    return "Zaif"


def _group_note(label: str, weak_titles: list[str]) -> str:
    if label == "Yaxshi":
        return "sezilarli kamchilik kuzatilmadi."
    weak_part = ", ".join(weak_titles) if weak_titles else "ayrim jihatlar"
    if label == "O'rtacha":
        return f"asosan yaxshi, lekin {weak_part} bo'yicha ayrim kamchiliklar bor — shu qismlarga ko'proq e'tibor bering."
    return f"{weak_part} bo'yicha jiddiy kamchiliklar bor — shu qismlarni qayta ko'rib chiqish tavsiya etiladi."


def format_evaluation_messages(result: EssayGradeResult) -> list[str]:
    """AI'ning 12 bandlik tahlilini talabgorga yuboriladigan tayyor HTML
    xabar(lar)ga aylantiradi.

    Band-band aniq ball va essedan olingan iqtibos (xato matni) ko'rsatilmaydi
    — bunday aniqlik talabgorlar tomonidan tez-tez e'tirozlarga sabab bo'lgan.
    Buning o'rniga 12 band rasmiy mezonning o'zidagi 5 ta tabiiy guruhga
    birlashtirilib, har biri uchun qisqa sifat bahosi (Yaxshi / O'rtacha /
    Zaif) va bir jumlalik umumiy izoh beriladi. Oxirida 24 va 75 ballik
    yakuniy natija hamda umumiy qisqa xulosa ko'rsatiladi.

    Agar `criteria_scores` bo'sh bo'lsa (esse yozilmagan yoki 100 so'zdan kam
    bo'lgani uchun avtomatik rad etilgan bo'lsa), bo'sh ro'yxat qaytaradi —
    bunday holda batafsil tahlil yo'q."""
    if not result.criteria_scores:
        return []

    blocks: list[str] = []
    scores = result.criteria_scores
    errors_map = result.band_errors or {}

    group_lines = ["📋 <b>Esse tahlili:</b>"]
    for emoji, group_title, band_keys in _GROUPS:
        vals = [scores.get(k, 0.0) for k in band_keys]
        avg = sum(vals) / len(vals) if vals else 0.0
        label = _group_label(avg)

        weak_titles = []
        for k in band_keys:
            has_real_error = any(
                e.strip().lower() != "xatolik aniqlanmadi" for e in (errors_map.get(k) or [])
            )
            if has_real_error or scores.get(k, 2.0) < 1.0:
                weak_titles.append(BAND_TITLES.get(k, f"{k}-band"))

        note = _group_note(label, weak_titles)
        group_lines.append(
            f"{emoji} {_escape_html(group_title)}: <b>{label}</b> — {_escape_html(note)}"
        )

    blocks.append("\n".join(group_lines))

    summary = "📊 <b>Yakuniy natija:</b>\n"
    summary += f"24 ballik tizimda: <b>{result.total_score_24} / 24</b>\n"
    summary += f"75 ballik tizimda: <b>{result.converted_score_75} ball</b>"

    if result.feedback:
        summary += f"\n\n💬 {_escape_html(result.feedback)}"

    blocks.append(summary)

    # Bloklarni Telegram xabar uzunlik chegarasidan oshmaydigan qilib,
    # imkon qadar kamroq xabarga guruhlab yig'amiz.
    messages: list[str] = []
    current = ""
    for block in blocks:
        if current and len(current) + len(block) + 1 > _MAX_TG_MESSAGE_LEN:
            messages.append(current.strip())
            current = ""
        current += block + "\n"
    if current.strip():
        messages.append(current.strip())
    return messages
