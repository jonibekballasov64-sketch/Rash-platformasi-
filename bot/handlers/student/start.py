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
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings
from bot.db.base import get_session
from bot.db.models import Attempt, AttemptStatus
from bot.services.session import resume_attempt, get_resumable_attempt
from sqlalchemy import select

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


@router.message(Command("resume"))
async def cmd_resume(message: Message, bot: Bot) -> None:
    """Pause qilingan testni davom ettirish."""
    if not await _is_group_member(bot, message.from_user.id):
        await message.answer("❌ Siz guruhga a'zo emassiz.")
        return
    
    async with get_session() as session:
        # O'quvchining pause qilingan testlarini qidirish
        result = await session.execute(
            select(Attempt).where(
                Attempt.learner_id == message.from_user.id,
                Attempt.status == AttemptStatus.IN_PROGRESS,
                Attempt.paused_at.isnot(None),
            )
        )
        paused_attempts = list(result.scalars().all())
    
    if not paused_attempts:
        await message.answer("📭 Siz uchun pause qilingan test yo'q.")
        return
    
    # Pause qilingan testlarni ko'rsatish
    buttons = []
    for attempt in paused_attempts:
        remaining = int((attempt.deadline_at - attempt.paused_at).total_seconds() / 60)
        buttons.append([
            InlineKeyboardButton(
                text=f"🔄 Test #{attempt.id} ({remaining} min)",
                callback_data=f"resume_{attempt.id}"
            )
        ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(
        "🔄 Davom ettira oladigan testlar:",
        reply_markup=keyboard,
    )


@router.callback_query(lambda c: c.data.startswith("resume_"))
async def process_resume(callback_query, bot: Bot) -> None:
    """Resume tugmasini bosilganda."""
    attempt_id = int(callback_query.data.split("_")[1])
    
    async with get_session() as session:
        resume_result = await resume_attempt(session, attempt_id)
    
    if not resume_result.success:
        await callback_query.answer(f"❌ {resume_result.message}", show_alert=True)
    else:
        remaining_min = resume_result.remaining_seconds // 60
        await callback_query.answer(
            f"✅ Test davom ettiririldi! {remaining_min} minut qoldi",
            show_alert=True
        )
        # WebApp'ni ochish
        if settings.webapp_base_url:
            webapp_url = f"{settings.webapp_base_url}/test/{attempt_id}"
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[
                    InlineKeyboardButton(
                        text="▶️ Davom ettirish",
                        web_app=WebAppInfo(url=webapp_url),
                    )
                ]]
            )
            await callback_query.message.edit_text(
                "✅ Test davom ettiririldi!\n"
                f"Qolgan vaqt: {remaining_min} minut",
                reply_markup=keyboard,
            )
