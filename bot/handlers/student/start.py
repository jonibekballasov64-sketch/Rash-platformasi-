"""O'quvchi tomoni: /start -> guruh a'zoligini tekshirish -> to'g'ridan-to'g'ri
Web App (Mini App) ochiladi.

Ism-familiya, test kodi va toifa endi CHATDA emas, balki shu WebApp ichida
(`webapp/register.html`) so'raladi va u yerdan `webapp_server/app.py`dagi
`/api/register` orqali Attempt yaratiladi. Bu fayl endi faqat guruh
a'zoligini tekshirib, WebApp tugmasini ko'rsatadi.
"""
from __future__ import annotations

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from sqlalchemy import select

from bot.config import settings
from bot.db.base import get_session
from bot.db.models import Attempt, AttemptStatus, LearnerUser

router = Router(name="student_start")


async def _is_group_member(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(settings.allowed_group_id, user_id)
    except Exception:
        return False
    return member.status not in ("left", "kicked")


@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot) -> None:
    if not await _is_group_member(bot, message.from_user.id):
        await message.answer(
            "❌ Botdan foydalanish uchun avval belgilangan guruhga a'zo bo'lishingiz kerak."
        )
        return

    if not settings.webapp_base_url:
        await message.answer(
            "⚠️ WEBAPP_BASE_URL sozlanmagan, shuning uchun test oynasi ochilmaydi. "
            "Admin .env faylida WEBAPP_BASE_URL'ni to'ldirishi kerak."
        )
        return

    rows = [
        [
            InlineKeyboardButton(
                text="✅ Test ishlash",
                web_app=WebAppInfo(url=f"{settings.webapp_base_url}/register"),
            )
        ]
    ]
    text = (
        "🌟 <b>Nargiza Olimovna akademiyasi</b>\n"
        "<i>Milliy sertifikat · Onlayn test platformasi</i>\n\n"
        "Assalomu alaykum! Testni boshlash uchun pastdagi <b>«✅ Test ishlash»</b> tugmasini bosing.\n\n"
        "📝 Test faqat <b>bir marta</b> topshiriladi\n"
        "⏱ Uzilib qolsangiz — davom ettirish mumkin"
    )
    # «Davom ettirish» faqat tugallanmagan testi bor o'quvchilarga ko'rinadi
    async with get_session() as session:
        pending = await session.execute(
            select(Attempt.id)
            .join(LearnerUser, LearnerUser.id == Attempt.learner_id)
            .where(
                LearnerUser.telegram_id == message.from_user.id,
                Attempt.status == AttemptStatus.IN_PROGRESS,
            )
            .limit(1)
        )
        has_pending = pending.scalar_one_or_none() is not None
    if has_pending:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔄 Davom ettirish",
                    web_app=WebAppInfo(url=f"{settings.webapp_base_url}/register?resume=1"),
                )
            ]
        )
        text = (
            "🌟 <b>Nargiza Olimovna akademiyasi</b>\n\n"
            "Sizda tugallanmagan test bor. <b>«🔄 Davom ettirish»</b> tugmasini bosib test kodini kiriting — "
            "uzilgan joyingizdan davom etasiz."
        )
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
