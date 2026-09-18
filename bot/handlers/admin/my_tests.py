"""Admin uchun /testlarim — yaratilgan testlar ro'yxati, joriy natijalar va
natijalarni talabgorlarga yuborish."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.db.base import get_session
from bot.db.models import AdminUser, Attempt, AttemptStatus, LearnerUser, Test
from bot.services.results import recompute_test_results

router = Router(name="admin_my_tests")


@router.message(Command("testlarim"))
async def cmd_my_tests(message: Message) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(Test)
            .join(AdminUser)
            .where(AdminUser.telegram_id == message.from_user.id)
            .order_by(Test.created_at.desc())
        )
        tests = list(result.scalars().all())

    if not tests:
        await message.answer("Hali sizda testlar yo'q. /yangitest bilan yarating.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{t.code} — {t.title}", callback_data=f"test:{t.id}")]
            for t in tests
        ]
    )
    await message.answer("Testlaringiz:", reply_markup=keyboard)


async def _build_test_detail(test_id: int) -> tuple[str, InlineKeyboardMarkup]:
    async with get_session() as session:
        result = await session.execute(
            select(Attempt)
            .where(Attempt.test_id == test_id)
            .options(selectinload(Attempt.learner))
        )
        attempts = list(result.scalars().all())

        test_result = await session.execute(select(Test).where(Test.id == test_id))
        test = test_result.scalar_one()

    finished = [a for a in attempts if a.status == AttemptStatus.FINISHED]
    in_progress = [a for a in attempts if a.status == AttemptStatus.IN_PROGRESS]

    lines = [
        f"📋 <b>{test.title}</b>",
        f"Kod: <code>{test.code}</code>",
        f"Holat: {test.status.value}",
        "",
        f"Yakunlaganlar: {len(finished)} kishi",
        f"Hozir ishlayotganlar: {len(in_progress)} kishi",
        "",
    ]
    if finished:
        lines.append("So'nggi natijalar:")
        for a in finished[-10:]:
            score = a.final_score if a.final_score is not None else "hisoblanmagan"
            grade = a.final_grade or "-"
            lines.append(f"  • {a.learner.full_name}: {score} ({grade})")
    else:
        lines.append("Hali hech kim yakunlamagan.")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Natijalarni yangilash va yuborish", callback_data=f"publish:{test_id}")],
        ]
    )
    return "\n".join(lines), keyboard


@router.callback_query(F.data.startswith("test:"))
async def on_test_selected(callback: CallbackQuery) -> None:
    test_id = int(callback.data.split(":", 1)[1])
    text, keyboard = await _build_test_detail(test_id)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("publish:"))
async def on_publish_results(callback: CallbackQuery, bot: Bot) -> None:
    test_id = int(callback.data.split(":", 1)[1])
    await callback.answer("Hisoblanmoqda...")

    async with get_session() as session:
        summary = await recompute_test_results(session, test_id)

        # Har bir hisoblangan urinish egasiga natija xabari yuboriladi
        sent = 0
        for attempt in summary.results:
            if attempt.final_score is None:
                continue  # esse bali hali kelmagan bo'lsa, kutamiz
            learner_result = await session.execute(
                select(LearnerUser).where(LearnerUser.id == attempt.learner_id)
            )
            learner = learner_result.scalar_one()
            try:
                await bot.send_message(
                    learner.telegram_id,
                    (
                        f"📊 Natijangiz e'lon qilindi!\n\n"
                        f"44 ta test bali: {attempt.rasch_score_75}\n"
                        f"Esse bali: {attempt.essay_score_75}\n"
                        f"Yakuniy ball: {attempt.final_score}\n"
                        f"Daraja: {attempt.final_grade}\n\n"
                        "Batafsil javob va izohlarni ko'rish uchun natija xabaringizdagi "
                        "tugmadan foydalaning."
                    ),
                )
                sent += 1
            except Exception:
                # Foydalanuvchi botni bloklagan yoki boshqa yetkazish xatosi —
                # jarayon davom etadi, faqat shu kishiga yubormaydi
                pass

    text, keyboard = await _build_test_detail(test_id)
    await callback.message.edit_text(
        f"{text}\n\n✅ {sent} talabgorga natija yuborildi.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
