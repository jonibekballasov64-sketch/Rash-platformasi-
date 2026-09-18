"""Esse (yozma ish)ni tekshirish xizmati — to'g'ridan-to'g'ri OpenAI API orqali.

Oqim:
  1. Oddiy (kod bilan tekshiriladigan) shartlar — AI'ga umuman yuborilmaydi:
       - yozilmagan / bo'sh -> 0 ball
       - 100 so'zdan kam -> 2 ball (avtomatik, tahlilsiz)
  2. Shu shartlarga tushmasa -> OpenAI'ga to'liq 12 bandli rasmiy mezon
     (barcha 5 daraja tavsifi bilan) yuboriladi, u har bir band uchun
     0/0.5/1/1.5/2 ball qo'yadi va mavzuga mosligini/ko'chirilganligini ham
     baholaydi. 24 ballik yig'indi olinib, rasmiy jadval orqali 75 ballikka
     o'tkaziladi (scoring.py).

Ishlatish uchun: Railway'da (yoki .env'da) OPENAI_API_KEY'ni qo'ying.
Boshqa hech narsa sozlash shart emas — bu fayl to'g'ridan-to'g'ri
https://api.openai.com/v1/chat/completions'ga so'rov yuboradi.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

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
    OFF_TOPIC = "mavzuga mos emas"
    PLAGIARIZED = "ko'chirilgan"


@dataclass
class EssayGradeResult:
    criteria_scores: dict[str, float] | None  # None bo'lsa avto-rad qilingan
    total_score_24: float
    converted_score_75: int
    auto_reject_reason: str | None
    feedback: str | None = None


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


def _build_prompt(text: str, topic: str, word_count: int) -> list[dict]:
    system = (
        "Siz Ona tili va adabiyot fanidan Milliy sertifikat imtihonidagi ESSE "
        "(yozma ish)ni rasmiy 12 bandli mezon asosida baholaydigan tajribali "
        "ekspertsiz. Faqat berilgan mezonga qat'iy amal qiling, boshqa hech "
        "qanday mezondan foydalanmang. Har bir banddan aniq 0, 0.5, 1, 1.5 "
        "yoki 2 ball qo'ying — oraliq boshqa qiymat yo'q. Natijani FAQAT "
        "JSON ko'rinishida qaytaring, hech qanday qo'shimcha matn yozmang."
    )
    user = f"""MEZON:
{CRITERIA_RUBRIC}

ESSE MAVZUSI: {topic}

TALABGOR YOZGAN ESSE MATNI ({word_count} so'z):
\"\"\"
{text}
\"\"\"

Vazifa:
1. Avval tekshiring: esse berilgan mavzuga umuman aloqasi yo'qmi (off_topic)?
   Yoki boshqa manbadan ko'chirilganga o'xshaydimi (plagiarized) — masalan
   umumiy qabul qilingan, "andoza" formatidagi, shaxsiy fikr yo'q, shubhali
   silliq matn bo'lsa shubha bildiring.
2. Agar off_topic yoki plagiarized bo'lsa, criteria_scores'ni bo'sh ({{}})
   qoldiring.
3. Aks holda, yuqoridagi 12 bandning HAR BIRI bo'yicha alohida tahlil qilib,
   0/0.5/1/1.5/2 ball qo'ying.
4. Qisqa (2-3 gap) umumiy izoh yozing (feedback) — asosiy kuchli va zaif
   tomonlarni ayting.

Javobni FAQAT quyidagi JSON formatida qaytaring:
{{
  "off_topic": true yoki false,
  "plagiarized": true yoki false,
  "criteria_scores": {{"1": 2, "2": 1.5, "3": 1, "4": 2, "5": 1.5, "6": 2, "7": 1, "8": 1.5, "9": 2, "10": 1, "11": 1.5, "12": 2}},
  "feedback": "qisqa umumiy izoh"
}}"""
    return [
        {"role": "system", "content": system},
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

    payload = {
        "model": settings.openai_model,
        "messages": _build_prompt(text, topic, word_count),
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
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

    if data.get("off_topic"):
        return EssayGradeResult(
            criteria_scores=None,
            total_score_24=AUTO_REJECT_SCORE_24,
            converted_score_75=convert_essay_24_to_75(AUTO_REJECT_SCORE_24),
            auto_reject_reason=AutoRejectReason.OFF_TOPIC,
            feedback=data.get("feedback"),
        )
    if data.get("plagiarized"):
        return EssayGradeResult(
            criteria_scores=None,
            total_score_24=AUTO_REJECT_SCORE_24,
            converted_score_75=convert_essay_24_to_75(AUTO_REJECT_SCORE_24),
            auto_reject_reason=AutoRejectReason.PLAGIARIZED,
            feedback=data.get("feedback"),
        )

    raw_scores: dict[str, float] = data.get("criteria_scores", {})
    # Har bir bandni 0/0.5/1/1.5/2 ga eng yaqiniga yaxlitlab, xavfsizlik uchun
    # 0-2 oralig'ida ushlab turamiz (model xato qiymat qaytarsa ham tizim yiqilmasin)
    allowed = [0, 0.5, 1, 1.5, 2]
    clean_scores: dict[str, float] = {}
    for band in [str(i) for i in range(1, 13)]:
        val = float(raw_scores.get(band, 0))
        val = max(0.0, min(2.0, val))
        clean_scores[band] = min(allowed, key=lambda a: abs(a - val))

    total_24 = round(sum(clean_scores.values()), 2)
    return EssayGradeResult(
        criteria_scores=clean_scores,
        total_score_24=total_24,
        converted_score_75=convert_essay_24_to_75(total_24),
        auto_reject_reason=None,
        feedback=data.get("feedback"),
  )
