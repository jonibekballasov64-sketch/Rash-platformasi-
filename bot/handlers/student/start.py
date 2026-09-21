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

from bot.config import settings

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

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Test ishlash",
                    web_app=WebAppInfo(url=f"{settings.webapp_base_url}/register"),
                )
            ]
        ]
    )
    await message.answer(
        "Assalomu alaykum! Milliy sertifikat testini ishlashni boshlash uchun tugmani bosing.",
        reply_markup=keyboard,
    )
