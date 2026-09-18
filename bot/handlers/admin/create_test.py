"""Admin uchun /yangitest — yangi test yaratish FSM oqimi.

Bosqichlar:
  1. Test turini tanlash (tugmalar): faqat 44 ta test / 44 ta test + esse
  2. 1-17-savollar (bir tanlovli), ketma-ket xabar bilan
  3. Ilmiy matn (passage) -> 18-22-savollar
  4. Badiiy matn (passage) -> 23-27-savollar
  5. G'azal (passage) -> 28-32-savollar
  6. 33-35 moslashtirish savoli (bitta xabarda)
  7. 36-39 qisqa yozma javobli savollar
  8. 40-44 ikki qismli savollar
  9. (faqat WITH_ESSAY bo'lsa) esse mavzusini kiritish
  10. Test kodi generatsiya qilinadi, tayyor xabar shabloni chiqadi

Har bir bosqichda admin xato yuborsa, parser xatosi tushuntirilib qaytadan
so'raladi. /bekor — butun jarayonni bekor qiladi.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.db.base import get_session
from bot.db.models import (
    AdminUser,
    Passage,
    PassageType,
    Question,
    QuestionType,
    Test,
    TestStatus,
    TestType,
)
from bot.services import question_parser as qp
from bot.utils.codes import generate_test_code

router = Router(name="admin_create_test")

DURATION_BY_TYPE = {
    TestType.ONLY_44: 120,   # 2 soat
    TestType.WITH_ESSAY: 180,  # 3 soat
}


class CreateTest(StatesGroup):
    choosing_type = State()
    q_1_17 = State()
    passage_ilmiy = State()
    q_18_22 = State()
    passage_badiiy = State()
    q_23_27 = State()
    passage_gazal = State()
    q_28_32 = State()
    q_33_35 = State()
    q_36_39 = State()
    q_40_44 = State()
    essay_topic = State()


def _type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Faqat 44 ta test olish", callback_data="ttype:only_44")],
            [InlineKeyboardButton(text="44 ta test + esse olish", callback_data="ttype:with_essay")],
        ]
    )


@router.message(Command("yangitest"))
async def cmd_new_test(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CreateTest.choosing_type)
    await message.answer(
        "Yangi test yaratamiz. Test turini tanlang:",
        reply_markup=_type_keyboard(),
    )


@router.message(Command("bekor"), StateFilter(CreateTest))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Test yaratish bekor qilindi.")


@router.callback_query(CreateTest.choosing_type, F.data.startswith("ttype:"))
async def on_type_chosen(callback: CallbackQuery, state: FSMContext) -> None:
    test_type = TestType(callback.data.split(":", 1)[1])
    await state.update_data(test_type=test_type.value, questions=[], passages={})
    await state.set_state(CreateTest.q_1_17)
    await state.update_data(next_order=1)
    await callback.message.edit_text(
        f"Tanlandi: {'Faqat 44 ta test' if test_type == TestType.ONLY_44 else '44 ta test + esse'}.\n\n"
        "Endi 1-savoldan boshlab, har birini alohida xabar sifatida yuboring "
        "(format: ⁉️1. ... / 🔷A) ... / ✅Javob: B / ⚠️Izoh: ...).\n"
        "Jarayonni bekor qilish uchun /bekor buyrug'ini yuboring."
    )
    await callback.answer()


def _save_question(data: dict, q: dict) -> None:
    data["questions"].append(q)


@router.message(CreateTest.q_1_17)
async def on_q_1_17(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    expected = data.get("next_order", 1)
    try:
        parsed = qp.parse_single_choice(message.text or "")
    except qp.ParseError as e:
        await message.answer(f"❌ Format xato: {e}\nQaytadan yuboring.")
        return
    if parsed.order_no != expected:
        await message.answer(f"⚠️ Kutilayotgan savol raqami {expected}, siz {parsed.order_no} yubordingiz. Qaytadan yuboring.")
        return

    _save_question(
        data,
        dict(
            order_no=parsed.order_no,
            question_type=QuestionType.SINGLE_CHOICE.value,
            text=parsed.text,
            options=parsed.options,
            correct_option=parsed.correct_option,
            explanation=parsed.explanation,
            passage_type=None,
        ),
    )

    if expected < 17:
        data["next_order"] = expected + 1
        await state.set_data(data)
        await message.answer(f"✅ {expected}-savol qabul qilindi. Endi {expected + 1}-savolni yuboring.")
    else:
        await state.set_data(data)
        await state.set_state(CreateTest.passage_ilmiy)
        await message.answer(
            "✅ 17-savol qabul qilindi.\n\nEndi 18-22-savollarga tegishli ILMIY MATNni yuboring "
            "(format: ‼️ ... matn ... ‼️)."
        )


@router.message(CreateTest.passage_ilmiy)
async def on_passage_ilmiy(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = qp.parse_passage(message.text or "")
    if not text:
        await message.answer("❌ Matn bo'sh bo'lib qoldi. Qaytadan yuboring.")
        return
    data["passages"]["ilmiy"] = text
    data["next_order"] = 18
    await state.set_data(data)
    await state.set_state(CreateTest.q_18_22)
    await message.answer("✅ Ilmiy matn qabul qilindi. Endi 18-savolni yuboring.")


async def _handle_passage_linked_range(
    message: Message,
    state: FSMContext,
    passage_type: str,
    start: int,
    end: int,
    next_state,
    next_prompt: str,
) -> None:
    data = await state.get_data()
    expected = data.get("next_order", start)
    try:
        parsed = qp.parse_single_choice(message.text or "")
    except qp.ParseError as e:
        await message.answer(f"❌ Format xato: {e}\nQaytadan yuboring.")
        return
    if parsed.order_no != expected:
        await message.answer(f"⚠️ Kutilayotgan savol raqami {expected}, siz {parsed.order_no} yubordingiz. Qaytadan yuboring.")
        return

    _save_question(
        data,
        dict(
            order_no=parsed.order_no,
            question_type=QuestionType.SINGLE_CHOICE.value,
            text=parsed.text,
            options=parsed.options,
            correct_option=parsed.correct_option,
            explanation=parsed.explanation,
            passage_type=passage_type,
        ),
    )

    if expected < end:
        data["next_order"] = expected + 1
        await state.set_data(data)
        await message.answer(f"✅ {expected}-savol qabul qilindi. Endi {expected + 1}-savolni yuboring.")
    else:
        await state.set_data(data)
        if next_state is not None:
            await state.set_state(next_state)
        await message.answer(f"✅ {expected}-savol qabul qilindi.\n\n{next_prompt}")


@router.message(CreateTest.q_18_22)
async def on_q_18_22(message: Message, state: FSMContext) -> None:
    await _handle_passage_linked_range(
        message, state, "ilmiy", 18, 22,
        CreateTest.passage_badiiy,
        "Endi 23-27-savollarga tegishli BADIIY MATNni yuboring (format: ‼️ ... matn ... ‼️).",
    )


@router.message(CreateTest.passage_badiiy)
async def on_passage_badiiy(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = qp.parse_passage(message.text or "")
    if not text:
        await message.answer("❌ Matn bo'sh bo'lib qoldi. Qaytadan yuboring.")
        return
    data["passages"]["badiiy"] = text
    data["next_order"] = 23
    await state.set_data(data)
    await state.set_state(CreateTest.q_23_27)
    await message.answer("✅ Badiiy matn qabul qilindi. Endi 23-savolni yuboring.")


@router.message(CreateTest.q_23_27)
async def on_q_23_27(message: Message, state: FSMContext) -> None:
    await _handle_passage_linked_range(
        message, state, "badiiy", 23, 27,
        CreateTest.passage_gazal,
        "Endi 28-32-savollarga tegishli G'AZALni yuboring (format: ‼️ ... matn ... ‼️).",
    )


@router.message(CreateTest.passage_gazal)
async def on_passage_gazal(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = qp.parse_passage(message.text or "")
    if not text:
        await message.answer("❌ Matn bo'sh bo'lib qoldi. Qaytadan yuboring.")
        return
    data["passages"]["gazal"] = text
    data["next_order"] = 28
    await state.set_data(data)
    await state.set_state(CreateTest.q_28_32)
    await message.answer("✅ G'azal qabul qilindi. Endi 28-savolni yuboring.")


@router.message(CreateTest.q_28_32)
async def on_q_28_32(message: Message, state: FSMContext) -> None:
    await _handle_passage_linked_range(
        message, state, "gazal", 28, 32,
        CreateTest.q_33_35,
        "Endi 33-35-savollarni (moslashtirish, BITTA xabarda) yuboring.",
    )


@router.message(CreateTest.q_33_35)
async def on_q_33_35(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    try:
        parsed = qp.parse_matching(message.text or "")
    except qp.ParseError as e:
        await message.answer(f"❌ Format xato: {e}\nQaytadan yuboring.")
        return

    for order_no in parsed.order_nos:
        _save_question(
            data,
            dict(
                order_no=order_no,
                question_type=QuestionType.MATCHING.value,
                text=parsed.texts[order_no],
                options=parsed.options,
                correct_option=parsed.correct[order_no],
                explanation=parsed.explanation,
                passage_type=None,
            ),
        )
    data["next_order"] = 36
    await state.set_data(data)
    await state.set_state(CreateTest.q_36_39)
    await message.answer("✅ 33-35-savollar qabul qilindi. Endi 36-savolni yuboring.")


@router.message(CreateTest.q_36_39)
async def on_q_36_39(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    expected = data.get("next_order", 36)
    try:
        parsed = qp.parse_short_answer(message.text or "")
    except qp.ParseError as e:
        await message.answer(f"❌ Format xato: {e}\nQaytadan yuboring.")
        return
    if parsed.order_no != expected:
        await message.answer(f"⚠️ Kutilayotgan savol raqami {expected}, siz {parsed.order_no} yubordingiz. Qaytadan yuboring.")
        return

    _save_question(
        data,
        dict(
            order_no=parsed.order_no,
            question_type=QuestionType.SHORT_ANSWER.value,
            text=parsed.text,
            accepted_answers=parsed.accepted_answers,
            explanation=parsed.explanation,
            passage_type=None,
        ),
    )

    if expected < 39:
        data["next_order"] = expected + 1
        await state.set_data(data)
        await message.answer(f"✅ {expected}-savol qabul qilindi. Endi {expected + 1}-savolni yuboring.")
    else:
        data["next_order"] = 40
        await state.set_data(data)
        await state.set_state(CreateTest.q_40_44)
        await message.answer("✅ 39-savol qabul qilindi.\n\nEndi 40-savolni yuboring (ikki qismli, A) va B) bilan).")


@router.message(CreateTest.q_40_44)
async def on_q_40_44(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    expected = data.get("next_order", 40)
    try:
        parsed = qp.parse_two_part_short(message.text or "")
    except qp.ParseError as e:
        await message.answer(f"❌ Format xato: {e}\nQaytadan yuboring.")
        return
    if parsed.order_no != expected:
        await message.answer(f"⚠️ Kutilayotgan savol raqami {expected}, siz {parsed.order_no} yubordingiz. Qaytadan yuboring.")
        return

    _save_question(
        data,
        dict(
            order_no=parsed.order_no,
            question_type=QuestionType.TWO_PART_SHORT.value,
            text=parsed.text,
            accepted_answers=parsed.part_a_answers,
            explanation=parsed.part_a_explanation,
            part_b_text=parsed.part_b_text,
            part_b_accepted_answers=parsed.part_b_answers,
            part_b_explanation=parsed.part_b_explanation,
            passage_type=None,
        ),
    )

    if expected < 44:
        data["next_order"] = expected + 1
        await state.set_data(data)
        await message.answer(f"✅ {expected}-savol qabul qilindi. Endi {expected + 1}-savolni yuboring.")
        return

    await state.set_data(data)
    test_type = TestType(data["test_type"])
    if test_type == TestType.WITH_ESSAY:
        await state.set_state(CreateTest.essay_topic)
        await message.answer("✅ 44-savol qabul qilindi.\n\n44 ta test qabul qilindi. Esse mavzusini kiriting.")
    else:
        await _finalize_test(message, state)


@router.message(CreateTest.essay_topic)
async def on_essay_topic(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    data["essay_topic"] = (message.text or "").strip()
    if not data["essay_topic"]:
        await message.answer("❌ Esse mavzusi bo'sh bo'lmasligi kerak. Qaytadan yuboring.")
        return
    await state.set_data(data)
    await message.answer("✅ Qabul qilindi.")
    await _finalize_test(message, state)


async def _finalize_test(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    test_type = TestType(data["test_type"])
    code = generate_test_code()

    async with get_session() as session:
        admin = await _get_or_create_admin(session, message.from_user.id, message.from_user.full_name)

        test = Test(
            code=code,
            title=f"{message.from_user.full_name} testi",
            test_type=test_type,
            status=TestStatus.READY,
            duration_minutes=DURATION_BY_TYPE[test_type],
            essay_topic=data.get("essay_topic"),
            created_by=admin,
        )
        session.add(test)
        await session.flush()

        passage_rows: dict[str, Passage] = {}
        for ptype_str, ptext in data.get("passages", {}).items():
            passage = Passage(test_id=test.id, passage_type=PassageType(ptype_str), text=ptext)
            session.add(passage)
            passage_rows[ptype_str] = passage
        await session.flush()

        for q in data["questions"]:
            passage = passage_rows.get(q.get("passage_type")) if q.get("passage_type") else None
            session.add(
                Question(
                    test_id=test.id,
                    order_no=q["order_no"],
                    question_type=QuestionType(q["question_type"]),
                    passage_id=passage.id if passage else None,
                    text=q["text"],
                    options=q.get("options"),
                    correct_option=q.get("correct_option"),
                    accepted_answers=q.get("accepted_answers"),
                    part_b_text=q.get("part_b_text"),
                    part_b_accepted_answers=q.get("part_b_accepted_answers"),
                    part_b_explanation=q.get("part_b_explanation"),
                    explanation=q.get("explanation"),
                )
            )

        await session.commit()

    await state.clear()
    await _send_ready_message(message, code=code, test_type=test_type)


async def _get_or_create_admin(session, telegram_id: int, full_name: str) -> AdminUser:
    from sqlalchemy import select

    result = await session.execute(select(AdminUser).where(AdminUser.telegram_id == telegram_id))
    admin = result.scalar_one_or_none()
    if admin is None:
        admin = AdminUser(telegram_id=telegram_id, full_name=full_name or "")
        session.add(admin)
        await session.flush()
    return admin


async def _send_ready_message(message: Message, code: str, test_type: TestType) -> None:
    hours = DURATION_BY_TYPE[test_type] // 60
    essay_line = (
        "Esse ham yoziladi (bot ichida)" if test_type == TestType.WITH_ESSAY else "Ball kiritiladi (0-75)"
    )
    text = (
        "✅ Test tuzdingiz!\n\n"
        f"Test kodi: <code>{code}</code>\n\n"
        "O'quvchilarga yuborish uchun xabar:\n\n"
        "<pre>"
        "Assalomu alaykum! Ona tili va adabiyot fanidan Milliy sertifikat "
        "testini maxsus botda ishlang.\n\n"
        f"Vaqt: {hours} soat\n"
        "Savollar soni: 44 ta\n"
        f"Esse uchun: {essay_line}\n\n"
        f"Test kodi: {code}\n\n"
        "Bot linki: @Olimovna_MsBot"
        "</pre>"
    )
    await message.answer(text, parse_mode="HTML")
