"""Admin uchun /tahrirlash — allaqachon yaratilgan testdagi bitta yoki bir
nechta savolni TUZATISH (matnini, variantlarini, javobini, izohini
almashtirish), butun testni qayta yaratmasdan.

Ishlash tartibi:
  1. Admin /tahrirlash buyrug'ini yuboradi.
  2. Bot test kodini so'raydi (masalan: AB12CD) — faqat SHU admin yaratgan
     testlar qabul qilinadi.
  3. Kod to'g'ri bo'lsa, admin o'zgartirmoqchi bo'lgan savol(lar)ni XUDDI
     /yangitest'dagi kabi formatda (⁉️41. ..., 🔷A) ..., ✅Javob: ... va h.k.)
     qayta yuboradi — savol raqami (⁉️N.) qaysi bo'lsa, o'sha raqamli MAVJUD
     savol bazada yangi matn bilan ALMASHTIRILADI (yangi savol qo'shilmaydi —
     testda hali umuman yo'q raqam yuborilsa, xato qaytariladi).
  4. Bitta xabarda bir nechta savolni ham yuborish mumkin. 33-35 (moslashtirish)
     ham /yangitest'dagi kabi bitta xabarda, uchtasi birga yuboriladi.
  5. Agar Telegram xabarni avtomatik bo'lib yuborsa (savol matni juda uzun
     bo'lganda), bot buni ham /yangitest kabi avtomatik ulaydi.
  6. /bekor — tahrirlashni tugatadi (test hali READY holatida qoladi, allaqachon
     saqlangan o'zgarishlar bekor qilinmaydi — faqat rejim tugaydi).
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy import select

from bot.db.base import get_session
from bot.db.models import AdminUser, Question, QuestionType, Test
from bot.services import question_parser as qp

router = Router(name="admin_edit_test")


class EditTest(StatesGroup):
    entering_code = State()
    editing = State()


@router.message(Command("tahrirlash"))
async def cmd_edit_test(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(EditTest.entering_code)
    await message.answer(
        "✏️ Qaysi testni tahrirlaysiz? Test kodini yuboring (masalan: AB12CD).\n"
        "Bekor qilish uchun /bekor."
    )


@router.message(Command("bekor"), StateFilter(EditTest))
async def cmd_cancel_edit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Tahrirlash rejimi tugatildi.")


@router.message(StateFilter(EditTest.entering_code))
async def on_code_entered(message: Message, state: FSMContext) -> None:
    code = (message.text or "").strip().upper()
    if not code:
        await message.answer("❌ Test kodini kiriting (masalan: AB12CD), yoki /bekor.")
        return

    async with get_session() as session:
        result = await session.execute(
            select(Test)
            .join(AdminUser)
            .where(Test.code == code, AdminUser.telegram_id == message.from_user.id)
        )
        test = result.scalar_one_or_none()

    if test is None:
        await message.answer(
            "❌ Bunday kodli test topilmadi (yoki bu sizning testingiz emas). "
            "Qaytadan kiriting yoki /bekor."
        )
        return

    await state.update_data(
        test_id=test.id,
        test_code=test.code,
        open_question_lines=None,
        open_question_retries=0,
    )
    await state.set_state(EditTest.editing)
    await message.answer(
        f"✅ Test topildi: <b>{test.title}</b> ({test.code}).\n\n"
        "Endi o'zgartirmoqchi bo'lgan savol(lar)ni XUDDI /yangitest kiritish "
        "formatida qayta yuboring, masalan:\n\n"
        "⁉️41. Savol matni\n"
        "A) A-qism savoli\n"
        "✅Javob: ...\n"
        "⚠️Izoh: ...\n"
        "B) B-qism savoli\n"
        "✅Javob: ...\n"
        "⚠️Izoh: ...\n\n"
        "Savol raqami (⁉️41.) qaysi bo'lsa, o'sha raqamli MAVJUD savol shu bilan "
        "ALMASHTIRILADI. Bitta xabarda bir nechta savolni ham yuborish mumkin.\n\n"
        "Tugatgach /bekor bilan chiqing.",
        parse_mode="HTML",
    )


@router.message(StateFilter(EditTest.editing))
async def on_edit_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    test_id = data["test_id"]
    raw_lines = (message.text or "").replace("\r\n", "\n").split("\n")

    # Oldingi xabardan davom etayotgan (Telegram tomonidan bo'lib yuborilgan)
    # savol bo'lsa, avval shuni davom ettiramiz.
    if data.get("open_question_lines") is not None:
        raw_lines = data["open_question_lines"] + raw_lines
        data["open_question_lines"] = None

    replies: list[str] = []
    errors: list[str] = []

    i = 0
    n = len(raw_lines)
    while i < n:
        line = raw_lines[i]
        if line.strip() == "":
            i += 1
            continue

        order_no = qp.question_order_no(line)
        if order_no is None:
            errors.append(f"⚠️ Tushunarsiz qator (e'tiborsiz qoldirildi): {line[:60]!r}")
            i += 1
            continue

        j = i + 1
        reached_end = False
        if order_no in (33, 34, 35):
            while j < n:
                nxt = qp.question_order_no(raw_lines[j])
                if nxt is not None and nxt not in (33, 34, 35):
                    break
                j += 1
            else:
                reached_end = True
        else:
            while j < n:
                if qp.question_order_no(raw_lines[j]) is not None:
                    break
                j += 1
            else:
                reached_end = True

        block_lines = raw_lines[i:j]
        try:
            kind, parsed = qp.classify_and_parse_block(block_lines)
        except qp.ParseError as e:
            retries = data.get("open_question_retries", 0)
            if reached_end and retries < 5:
                data["open_question_lines"] = block_lines
                data["open_question_retries"] = retries + 1
                await state.set_data(data)
                if replies:
                    await message.answer("\n".join(replies))
                if errors:
                    await message.answer("\n".join(errors))
                await message.answer(
                    f"⏳ {order_no}-savol matni davom etmoqda (xabar Telegram "
                    "tomonidan avtomatik bo'lib yuborilgan bo'lishi mumkin). "
                    "Davomini keyingi xabar(lar)da yuboring."
                )
                return
            data["open_question_retries"] = 0
            errors.append(f"❌ {order_no}-savol atrofida xato: {e}")
            i = j
            continue

        data["open_question_retries"] = 0

        if kind == "matching":
            msg = await _update_matching(test_id, parsed)
        elif kind == "single":
            msg = await _update_single(test_id, parsed)
        elif kind == "short":
            msg = await _update_short(test_id, parsed)
        else:  # twopart
            msg = await _update_twopart(test_id, parsed)

        (replies if msg.startswith("✅") else errors).append(msg)
        i = j

    await state.set_data(data)

    parts = []
    if replies:
        parts.append("\n".join(replies))
    if errors:
        parts.append("\n".join(errors))
    if not parts:
        parts.append("Hech narsa qabul qilinmadi.")
    parts.append("Yana savol yuborishingiz mumkin, tugatgach /bekor bilan chiqing.")
    await message.answer("\n\n".join(parts))


async def _get_question(session, test_id: int, order_no: int) -> Question | None:
    result = await session.execute(
        select(Question).where(Question.test_id == test_id, Question.order_no == order_no)
    )
    return result.scalar_one_or_none()


async def _update_single(test_id: int, parsed) -> str:
    async with get_session() as session:
        q = await _get_question(session, test_id, parsed.order_no)
        if q is None:
            return f"❌ {parsed.order_no}-savol bu testda topilmadi — bu testda mavjud bo'lmagan raqamga yangi savol qo'shib bo'lmaydi."
        if q.question_type != QuestionType.SINGLE_CHOICE:
            return f"❌ {parsed.order_no}-savol bu testda boshqa turdagi savol ({q.question_type.value}) — bir tanlovli formatga almashtirib bo'lmaydi."
        q.text = parsed.text
        q.options = parsed.options
        q.correct_option = parsed.correct_option
        q.explanation = parsed.explanation
        await session.commit()
    return f"✅ {parsed.order_no}-savol yangilandi."


async def _update_short(test_id: int, parsed) -> str:
    async with get_session() as session:
        q = await _get_question(session, test_id, parsed.order_no)
        if q is None:
            return f"❌ {parsed.order_no}-savol bu testda topilmadi — bu testda mavjud bo'lmagan raqamga yangi savol qo'shib bo'lmaydi."
        if q.question_type != QuestionType.SHORT_ANSWER:
            return f"❌ {parsed.order_no}-savol bu testda boshqa turdagi savol ({q.question_type.value}) — qisqa javob formatiga almashtirib bo'lmaydi."
        q.text = parsed.text
        q.accepted_answers = parsed.accepted_answers
        q.explanation = parsed.explanation
        await session.commit()
    return f"✅ {parsed.order_no}-savol yangilandi."


async def _update_twopart(test_id: int, parsed) -> str:
    async with get_session() as session:
        q = await _get_question(session, test_id, parsed.order_no)
        if q is None:
            return f"❌ {parsed.order_no}-savol bu testda topilmadi — bu testda mavjud bo'lmagan raqamga yangi savol qo'shib bo'lmaydi."
        if q.question_type != QuestionType.TWO_PART_SHORT:
            return f"❌ {parsed.order_no}-savol bu testda boshqa turdagi savol ({q.question_type.value}) — ikki qismli (A/B) formatga almashtirib bo'lmaydi."
        q.text = parsed.text
        q.accepted_answers = parsed.part_a_answers
        q.explanation = parsed.part_a_explanation
        q.part_b_text = parsed.part_b_text
        q.part_b_accepted_answers = parsed.part_b_answers
        q.part_b_explanation = parsed.part_b_explanation
        await session.commit()
    return f"✅ {parsed.order_no}-savol (A va B) yangilandi."


async def _update_matching(test_id: int, parsed) -> str:
    updated = []
    async with get_session() as session:
        for qn in parsed.order_nos:
            q = await _get_question(session, test_id, qn)
            if q is None:
                return f"❌ {qn}-savol bu testda topilmadi — 33-35 uchtasi ham mavjud bo'lishi kerak."
            if q.question_type != QuestionType.MATCHING:
                return f"❌ {qn}-savol bu testda boshqa turdagi savol ({q.question_type.value}) — moslashtirish formatiga almashtirib bo'lmaydi."
            q.text = parsed.texts[qn]
            q.options = parsed.options
            q.correct_option = parsed.correct[qn]
            q.explanation = parsed.explanation
            updated.append(qn)
        await session.commit()
    return "✅ " + ", ".join(str(n) for n in updated) + "-savollar yangilandi."
