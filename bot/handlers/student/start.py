"""O'quvchi tomoni: /start -> guruh a'zoligini tekshirish -> ro'yxatdan
o'tish (ism, test kodi, toifa) -> urinishlar sonini tekshirish -> Attempt
yaratish -> Web App tugmasi bilan test oynasini ochish.

Haqiqiy test ishlash interfeysi (savollar, taymer, moslashtirish jadvali,
ranglar) Telegram WEB APP (Mini App) ichida ishlaydi — bu repo'dagi
`webapp/` papkasida. Bu fayl faqat "ro'yxatdan o'tish -> testni boshlash"
oqimini boshqaradi.
"""
from __future__ import annotations

import datetime as dt

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy import func, select

from bot.config import settings
from bot.db.base import get_session
from bot.db.models import (
    Attempt,
    AttemptStatus,
    Category,
    LearnerUser,
    Test,
    TestStatus,
)

router = Router(name="student_start")

CATEGORY_LABELS = {
    Category.FILOLOG: "Filolog o'qituvchisi",
    Category.BOSHLANGICH: "Boshlang'ich o'qituvchisi",
    Category.ABITURIYENT_ASOSIY: "Abituriyent (asosiy blok)",
    Category.ABITURIYENT_MAJBURIY: "Abituriyent (majburiy blok)",
}

MAX_ATTEMPTS = 2


class TakeTest(StatesGroup):
    entering_name = State()
    entering_code = State()
    choosing_category = State()


async def _is_group_member(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(settings.allowed_group_id, user_id)
    except Exception:
        return False
    return member.status not in ("left", "kicked")


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    if not await _is_group_member(bot, message.from_user.id):
        await message.answer(
            "❌ Botdan foydalanish uchun avval belgilangan guruhga a'zo bo'lishingiz kerak."
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Test ishlash", callback_data="begin_test")]]
    )
    await message.answer(
        "Assalomu alaykum! Milliy sertifikat testini ishlashni boshlash uchun tugmani bosing.",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "begin_test")
async def on_begin_test(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    if not await _is_group_member(bot, callback.from_user.id):
        await callback.answer("Avval guruhga a'zo bo'ling.", show_alert=True)
        return
    await state.set_state(TakeTest.entering_name)
    await callback.message.answer("Ism va familiyangizni kiriting:")
    await callback.answer()


@router.message(TakeTest.entering_name)
async def on_name_entered(message: Message, state: FSMContext) -> None:
    full_name = (message.text or "").strip()
    if len(full_name) < 3:
        await message.answer("❌ Iltimos, to'liq ism-familiyangizni kiriting.")
        return
    await state.update_data(full_name=full_name)
    await state.set_state(TakeTest.entering_code)
    await message.answer("Test kodini kiriting:")


@router.message(TakeTest.entering_code)
async def on_code_entered(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip().upper()
    async with get_session() as session:
        result = await session.execute(select(Test).where(Test.code == code))
        test = result.scalar_one_or_none()

    if test is None or test.status == TestStatus.DRAFT:
        await message.answer("❌ Bunday kod bilan test topilmadi. Qaytadan kiriting.")
        return
    if test.status == TestStatus.CLOSED:
        await message.answer("❌ Bu test yopilgan, endi urinish qabul qilinmaydi.")
        await state.clear()
        return

    await state.update_data(test_id=test.id, test_code=test.code)
    await state.set_state(TakeTest.choosing_category)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"category:{cat.value}")]
            for cat, label in CATEGORY_LABELS.items()
        ]
    )
    await message.answer("Quyidagilardan mosini belgilang:", reply_markup=keyboard)


@router.callback_query(TakeTest.choosing_category, F.data.startswith("category:"))
async def on_category_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    category = Category(callback.data.split(":", 1)[1])
    data = await state.get_data()

    async with get_session() as session:
        # Learner (foydalanuvchi) ni topish yoki yaratish
        result = await session.execute(
            select(LearnerUser).where(LearnerUser.telegram_id == callback.from_user.id)
        )
        learner = result.scalar_one_or_none()
        if learner is None:
            learner = LearnerUser(telegram_id=callback.from_user.id, full_name=data["full_name"])
            session.add(learner)
            await session.flush()
        else:
            learner.full_name = data["full_name"]

        test_result = await session.execute(select(Test).where(Test.id == data["test_id"]))
        test = test_result.scalar_one()

        # Nechta urinish qilganini sanash
        count_result = await session.execute(
            select(func.count(Attempt.id)).where(
                Attempt.test_id == test.id, Attempt.learner_id == learner.id
            )
        )
        attempts_so_far = count_result.scalar_one()

        if attempts_so_far >= MAX_ATTEMPTS:
            await callback.message.edit_text(
                "❌ Siz bu testga allaqachon 2 marta urinib bo'lgansiz. Boshqa urinish mumkin emas."
            )
            await state.clear()
            await callback.answer()
            return

        attempt_number = attempts_so_far + 1
        now = dt.datetime.utcnow()
        attempt = Attempt(
            test_id=test.id,
            learner_id=learner.id,
            category=category,
            attempt_number=attempt_number,
            counts_for_rasch=(attempt_number == 1),
            status=AttemptStatus.IN_PROGRESS,
            started_at=now,
            deadline_at=now + dt.timedelta(minutes=test.duration_minutes),
        )
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)

    await state.clear()

    warning = (
        f"⏰ Sizga {test.duration_minutes // 60} soat vaqt beriladi, vaqtni to'xtatib bo'lmaydi.\n"
        f"Bu sizning {attempt_number}-urinishingiz (jami 2 marta urinish mumkin)."
    )
    if attempt_number == 1:
        warning += "\n\n⚠️ 1-urinish ustozga ko'rinadi va sizning rasmiy natijangiz hisoblanadi."
    else:
        warning += "\n\n⚠️ Bu 2-urinish — faqat o'zingiz uchun, rasmiy natijaga ta'sir qilmaydi."

    if settings.webapp_base_url:
        webapp_url = f"{settings.webapp_base_url}/test?attempt_id={attempt.id}"
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🚀 Testni boshlash", web_app=WebAppInfo(url=webapp_url))]
            ]
        )
        await callback.message.edit_text(warning, reply_markup=keyboard)
    else:
        await callback.message.edit_text(
            warning + "\n\n⚠️ WEBAPP_BASE_URL sozlanmagan, shuning uchun test oynasi ochilmaydi. "
            "Admin .env faylida WEBAPP_BASE_URL'ni to'ldirishi kerak."
        )
    await callback.answer()
