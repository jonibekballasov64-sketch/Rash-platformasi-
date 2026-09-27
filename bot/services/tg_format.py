"""Telegram xabarlaridan **qalin**/__qiya__ belgilarini TO'G'RI o'qib olish.

MUAMMO: Telegram mobil ilovasi xabar yozish paytida "**matn**" yozilsa, buni
avtomatik chin QALIN formatga aylantiradi va xabar matnidan (message.text)
"**" belgilarini butunlay OLIB TASHLAYDI — o'rniga formatlash haqidagi
ma'lumotni alohida "entities" ro'yxatida yuboradi (masalan
MessageEntity(type="bold", offset=10, length=5)). Xuddi shunday "__matn__"
ham chin QIYA (italic) formatga aylanadi.

Natijada admin botga "**qalin**" deb yozib yuborsa ham, bot
`message.text` orqali o'qiganda u yerda "**" belgilari umuman yo'q bo'lib
chiqadi — chunki Telegram ularni entity'ga aylantirib, matndan olib
tashlagan. Shu sabab bizning parser (question_parser.py) `**`/`__`
belgilarini hech qachon topa olmaydi va savol matnlarida qalin/qiya
ko'rinmay qoladi.

YECHIM: aiogram Message'ning `html_text` xususiyati orqali xabarni HTML
ko'rinishida (entity'lar HTML teglariga aylantirilgan holda) olamiz, keyin
<b>/<strong> -> "**", <i>/<em> -> "__" ga QAYTARIB qo'yamiz. Shunda parser
o'zining oddiy "**"/"__" regexlari bilan ishlashda davom etadi — na
question_parser.py, na uni chaqiruvchi kodning qolgan qismini o'zgartirish
shart emas, faqat xabar matnini o'qiyotgan bitta joyni shu funksiyaga
almashtirish kifoya.
"""
from __future__ import annotations

import re

from aiogram.types import Message

_BOLD_OPEN = re.compile(r"<(?:b|strong)>", re.IGNORECASE)
_BOLD_CLOSE = re.compile(r"</(?:b|strong)>", re.IGNORECASE)
_ITALIC_OPEN = re.compile(r"<(?:i|em)>", re.IGNORECASE)
_ITALIC_CLOSE = re.compile(r"</(?:i|em)>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]+>")


def message_text_with_markers(message: Message) -> str:
    """Xabar matnini qaytaradi — Telegram tomonidan chin bold/italic'ga
    aylantirilgan qismlar qaytadan "**"/"__" belgilariga o'giriladi, shunda
    admin "**qalin**" yoki "__qiya__" deb yozganida — Telegram buni avtomatik
    chin formatga aylantirib yuborgan bo'lsa ham — parser baribir to'g'ri
    o'qiy oladi. Agar admin haqiqatan ham literal "**"/"__" belgilarini
    (formatlanmagan holda) yuborgan bo'lsa, ular allaqachon message.text
    ichida bor va bu funksiya ularga tegmaydi."""
    html = message.html_text or message.text or ""
    html = _BOLD_OPEN.sub("**", html)
    html = _BOLD_CLOSE.sub("**", html)
    html = _ITALIC_OPEN.sub("__", html)
    html = _ITALIC_CLOSE.sub("__", html)
    # Boshqa teglar (masalan <u>, <s>, <code>, <a>) bo'lsa — ichidagi matnni
    # saqlab, tegning o'zini olib tashlaymiz (bizning formatimizda ular yo'q).
    html = _ANY_TAG.sub("", html)
    # aiogram html_text HTML-maxsus belgilarni escape qilgan (&lt; va h.k.) —
    # ularni asl holiga qaytaramiz.
    html = (
        html.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#x27;", "'")
        .replace("&amp;", "&")
    )
    return html
