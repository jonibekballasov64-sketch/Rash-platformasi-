"""Admin uchun /testlarim — yaratilgan testlar ro'yxati, joriy natijalar,
ONLY_44 testlar uchun qo'lda ball (esse/qo'shimcha) kiritish, natijalarni
talabgorlarga yuborish va joriy natijalarni Excel fayl qilib olish."""
from __future__ import annotations

import datetime as dt
import tempfile
import unicodedata
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.db.base import get_session
from bot.db.models import (
    AdminUser,
    Answer,
    Attempt,
    AttemptStatus,
    EssayResponse,
    LearnerUser,
    Test,
    TestType,
)
from bot.services.essay import NotConfiguredError, grade_essay
from bot.services.results import recompute_test_results

router = Router(name="admin_my_tests")


def _clean_name(name: str | None) -> str:
    """Bazada ilgari stilize Unicode shriftda saqlanib qolgan ismlarni ham
    (yangi ro'yxatdan o'tishlar endi tozalangan holda saqlanadi, lekin eski
    yozuvlar bazada o'zgarmagan) ko'rsatishda oddiy harflarga aylantiradi."""
    if not name:
        return "Noma'lum"
    return unicodedata.normalize("NFKC", name)


def _retry_keyboard(attempt_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Esseni qayta tekshirish", callback_data=f"retryessay:{attempt_id}")]
        ]
    )


class EnterScore(StatesGroup):
    entering_score = State()


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

    # Ball yakuniy natijaga kirishi uchun essay_score_75 (esse yoki qo'lda
    # kiritiladigan qo'shimcha ball) to'ldirilgan bo'lishi kerak. Ular
    # to'ldirilmagan bo'lsa, natija "hisoblanmagan" bo'lib qolaveradi —
    # shu sabab har biriga alohida "✍️ Ball kiritish" tugmasi chiqariladi.
    needs_score = [a for a in finished if a.essay_score_75 is None]

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
            lines.append(f"  • {_clean_name(a.learner.full_name)}: {score} ({grade})")
    else:
        lines.append("Hali hech kim yakunlamagan.")

    if needs_score:
        lines.append("")
        lines.append(
            "⚠️ Quyidagilarga hali ball kiritilmagan — kiritmaguningizcha "
            "natijasi \"hisoblanmagan\" bo'lib qolaveradi:"
        )

    keyboard_rows: list[list[InlineKeyboardButton]] = []
    for a in needs_score[:15]:
        keyboard_rows.append(
            [
                InlineKeyboardButton(
                    text=f"✍️ {_clean_name(a.learner.full_name)} — ball kiritish",
                    callback_data=f"setscore:{a.id}:{test_id}",
                )
            ]
        )
    keyboard_rows.append(
        [InlineKeyboardButton(text="🔄 Natijalarni yangilash va yuborish", callback_data=f"publish:{test_id}")]
    )
    keyboard_rows.append(
        [InlineKeyboardButton(text="📄 Joriy natijani olish (fayl)", callback_data=f"export:{test_id}")]
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows)
    return "\n".join(lines), keyboard


@router.callback_query(F.data.startswith("test:"))
async def on_test_selected(callback: CallbackQuery) -> None:
    # Eski "Testlaringiz:" ro'yxat xabarini o'zgartirmaymiz (edit_text emas) —
    # aks holda ro'yxat test tafsilotiga almashib, boshqa testni ko'rish uchun
    # /testlarim'ni qaytadan bosish kerak bo'lardi. Shu sabab tafsilot pastda
    # YANGI xabar sifatida chiqadi, ro'yxat esa joyida turadi.
    test_id = int(callback.data.split(":", 1)[1])
    text, keyboard = await _build_test_detail(test_id)
    await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("setscore:"))
async def on_setscore_start(callback: CallbackQuery, state: FSMContext) -> None:
    _, attempt_id_str, test_id_str = callback.data.split(":")
    attempt_id, test_id = int(attempt_id_str), int(test_id_str)

    async with get_session() as session:
        result = await session.execute(
            select(Attempt).where(Attempt.id == attempt_id).options(selectinload(Attempt.learner))
        )
        attempt = result.scalar_one_or_none()

    if attempt is None:
        await callback.answer("Urinish topilmadi", show_alert=True)
        return

    await state.set_state(EnterScore.entering_score)
    await state.update_data(attempt_id=attempt_id, test_id=test_id)
    await callback.message.answer(
        f"✍️ <b>{_clean_name(attempt.learner.full_name)}</b> uchun ball kiriting (0 dan 75 gacha, "
        "masalan: 62 yoki 62.5):",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(StateFilter(EnterScore.entering_score))
async def on_score_entered(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    try:
        score = float(raw)
    except ValueError:
        await message.answer("❌ Iltimos, faqat son kiriting (masalan: 62 yoki 62.5).")
        return

    if not (0 <= score <= 75):
        await message.answer("❌ Ball 0 dan 75 gacha bo'lishi kerak. Qaytadan kiriting:")
        return

    data = await state.get_data()
    attempt_id = data["attempt_id"]
    test_id = data["test_id"]
    await state.clear()

    async with get_session() as session:
        result = await session.execute(select(Attempt).where(Attempt.id == attempt_id))
        attempt = result.scalar_one_or_none()
        if attempt is None:
            await message.answer("❌ Urinish topilmadi (o'chirilgan bo'lishi mumkin).")
            return
        attempt.essay_score_75 = score
        await session.commit()

    text, keyboard = await _build_test_detail(test_id)
    await message.answer(
        f"✅ Ball saqlandi: {score}\n\n{text}",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("publish:"))
async def on_publish_results(callback: CallbackQuery, bot: Bot) -> None:
    test_id = int(callback.data.split(":", 1)[1])
    await callback.answer("Hisoblanmoqda...")

    async with get_session() as session:
        # mark_published=True: faqat HALI E'LON QILINMAGAN urinishlar
        # hisoblanadi va "qulflanadi" — avval e'lon qilingan kishilarning
        # bali endi qayta o'zgarmaydi va ularga ikkinchi marta xabar
        # yuborilmaydi, keyingi safar tugma bosilganda faqat YANGI
        # qo'shilganlar hisoblab, e'lon qilinadi.
        summary = await recompute_test_results(session, test_id, mark_published=True)

        # Har bir YANGI hisoblangan (avval e'lon qilinmagan) urinish egasiga
        # natija xabari yuboriladi
        sent = 0
        for attempt in summary.results:
            if attempt.final_score is None:
                continue  # esse/qo'lda ball hali kiritilmagan bo'lsa, kutamiz
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


CATEGORY_LABELS = {
    "filolog": "Filolog o'qituvchisi",
    "boshlangich": "Boshlang'ich o'qituvchisi",
    "abituriyent_asosiy": "Abituriyent (asosiy blok)",
    "abituriyent_majburiy": "Abituriyent (majburiy blok)",
}


@router.callback_query(F.data.startswith("export:"))
async def on_export_results(callback: CallbackQuery, bot: Bot) -> None:
    """Test yaratilgandan shu paytgacha uni ishlagan barcha talabgorlarning
    natijasini (Ism, 44-test bali, esse/qo'shimcha bali, yakuniy ball, daraja,
    xato belgilagan savollar) Excel faylga yig'ib, eng yaxshi natijadan
    pastga qarab saralangan holda yuboradi."""
    test_id = int(callback.data.split(":", 1)[1])
    await callback.answer("Fayl tayyorlanmoqda...")

    async with get_session() as session:
        # Fayl "joriy natija"ni ko'rsatishi kerak — shuning uchun eksportdan
        # oldin 44-test (Rasch) bali va (esse/qo'shimcha ball allaqachon
        # kiritilgan bo'lsa) yakuniy ball/daraja QAYTA hisoblanadi. Bu faqat
        # bazani yangilaydi — talabgorlarga hech narsa yuborilmaydi, e'lon
        # qilish uchun baribir alohida "Natijalarni yangilash va yuborish"
        # tugmasi bosiladi.
        await recompute_test_results(session, test_id)

        test_result = await session.execute(select(Test).where(Test.id == test_id))
        test = test_result.scalar_one()

        result = await session.execute(
            select(Attempt)
            .where(
                Attempt.test_id == test_id,
                Attempt.status.in_([AttemptStatus.FINISHED, AttemptStatus.EXPIRED]),
            )
            .options(selectinload(Attempt.learner), selectinload(Attempt.answers).selectinload(Answer.question))
        )
        attempts = list(result.scalars().all())

    if not attempts:
        await callback.message.answer("Hali hech kim bu testni yakunlamagan.")
        return

    def sort_key(a: Attempt):
        # Yakuniy ball bor bo'lsa shu bo'yicha, bo'lmasa xom to'g'ri javoblar
        # soni bo'yicha, eng yaxshisi tepada bo'ladigan qilib saralaymiz.
        primary = a.final_score if a.final_score is not None else -1
        secondary = a.raw_correct_count if a.raw_correct_count is not None else -1
        return (primary, secondary)

    attempts.sort(key=sort_key, reverse=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Natijalar"
    headers = [
        "№",
        "Ism-familiya",
        "Toifa",
        "Urinish",
        "44-test bali (Rasch)",
        "Esse/qo'shimcha bali",
        "Yakuniy ball",
        "Daraja",
        "Xato belgilagan savollar",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for i, a in enumerate(attempts, start=1):
        wrong_numbers = sorted(
            ans.question.order_no for ans in a.answers if ans.is_correct is False
        )
        ws.append(
            [
                i,
                _clean_name(a.learner.full_name),
                CATEGORY_LABELS.get(a.category.value, a.category.value),
                a.attempt_number,
                a.rasch_score_75 if a.rasch_score_75 is not None else "-",
                a.essay_score_75 if a.essay_score_75 is not None else "-",
                a.final_score if a.final_score is not None else "-",
                a.final_grade or "-",
                ", ".join(str(n) for n in wrong_numbers) if wrong_numbers else "-",
            ]
        )

    for column_cells in ws.columns:
        length = max(len(str(cell.value)) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = min(max(length + 2, 10), 60)

    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = Path(tmp_dir) / f"{test.code}_natijalar.xlsx"
        wb.save(file_path)
        await bot.send_document(
            callback.from_user.id,
            BufferedInputFile(file_path.read_bytes(), filename=file_path.name),
            caption=f"📄 {test.title} ({test.code}) — {len(attempts)} kishining joriy natijasi.",
        )


@router.callback_query(F.data.startswith("retryessay:"))
async def on_retry_essay(callback: CallbackQuery) -> None:
    """Esse AI tekshiruvi xato bergan bo'lsa (masalan OpenAI balans/limit
    tugagan), admin shu tugmani bosib esseni qayta tekshirtiradi. Esse matni
    bazada (EssayResponse.text) saqlanib turgani uchun hech qachon yo'qolmaydi
    — faqat AI baholash bosqichi qayta ishga tushiriladi. Bu FAQAT adminga
    ko'rinadigan tugma, talabgorga yubormaydi."""
    attempt_id = int(callback.data.split(":", 1)[1])
    await callback.answer("Esse qayta tekshirilmoqda...")

    async with get_session() as session:
        result = await session.execute(
            select(Attempt)
            .where(Attempt.id == attempt_id)
            .options(
                selectinload(Attempt.essay),
                selectinload(Attempt.test),
                selectinload(Attempt.learner),
            )
        )
        attempt = result.scalar_one_or_none()
        if attempt is None:
            await callback.message.answer("❌ Urinish topilmadi (o'chirilgan bo'lishi mumkin).")
            return
        if attempt.test.test_type != TestType.WITH_ESSAY:
            await callback.message.answer("Bu test uchun esse tekshiruvi kerak emas.")
            return

        essay_text = attempt.essay.text if attempt.essay else ""
        if not essay_text.strip():
            await callback.message.answer(
                "⚠️ Bu urinishda esse matni umuman saqlanmagan (talabgor yozmagan yoki "
                "vaqt tugab bo'sh yakunlangan). Qayta tekshirishning ma'nosi yo'q — "
                "ball \"✍️ ball kiritish\" orqali qo'lda kiritilsin."
            )
            return

        try:
            grade_result = await grade_essay(essay_text, attempt.test.essay_topic or "")
        except NotConfiguredError:
            await callback.message.answer(
                "⚠️ OPENAI_API_KEY hali sozlanmagan (yoki noto'g'ri). Railway'dagi "
                "webapp servisi (affectionate-elegance) Variables bo'limini tekshirib, "
                "qayta urinib ko'ring.",
                reply_markup=_retry_keyboard(attempt_id),
            )
            return
        except Exception:
            await callback.message.answer(
                "⚠️ Esse AI tekshiruvida yana xatolik yuz berdi (masalan, OpenAI hisobida "
                "balans/limit tugagan bo'lishi mumkin). Hisobni to'ldirib, birozdan so'ng "
                "qayta urinib ko'ring — esse matni yo'qolmagan, saqlanib turibdi.",
                reply_markup=_retry_keyboard(attempt_id),
            )
            return

        if attempt.essay is None:
            attempt.essay = EssayResponse(attempt_id=attempt.id, text=essay_text, word_count=0)
            session.add(attempt.essay)
        attempt.essay.word_count = len([w for w in essay_text.split() if w.strip()])
        attempt.essay.criteria_scores = grade_result.criteria_scores
        attempt.essay.total_score_24 = grade_result.total_score_24
        attempt.essay.converted_score_75 = grade_result.converted_score_75
        attempt.essay.auto_reject_reason = grade_result.auto_reject_reason
        attempt.essay.ai_feedback = grade_result.feedback
        attempt.essay.scored_at = dt.datetime.utcnow()
        attempt.essay_score_75 = grade_result.converted_score_75
        learner_name = _clean_name(attempt.learner.full_name if attempt.learner else None)
        test_id = attempt.test_id
        await session.commit()

    text, keyboard = await _build_test_detail(test_id)
    await callback.message.answer(
        f"✅ <b>{learner_name}</b> uchun esse qayta tekshirildi!\n\n"
        f"Esse bali: {grade_result.total_score_24}/24 ({grade_result.converted_score_75}/75)\n\n"
        "Endi pastdagi \"🔄 Natijalarni yangilash va yuborish\" tugmasini bosib, "
        "natijani talabgorga e'lon qiling.\n\n"
        f"{text}",
        reply_markup=keyboard,
        parse_mode="HTML",
        )
