"""Admin uchun /yangitest — yangi test yaratish, ERKIN (bulk) rejim.

Eski versiyada har bir savol qat'iy tartibda, alohida xabar sifatida
kiritilishi shart edi. Bu versiyada admin xabarlarni istalgan tartibda va
istalgan miqdorda (bittalab yoki bir nechtasini bittalashtirib) yubora oladi:
  - Bitta xabarda bir nechta savol bo'lishi mumkin (masalan 1-17 barchasi
    birdaniga).
  - Savollar tartib bilan kelishi shart emas — bot ularni order_no bo'yicha
    o'zi tartiblab, saqlab boradi.
  - Uzun matnlar (ilmiy/badiiy/g'azal, ‼️...‼️) bitta xabarga sig'masa, bir
    necha xabarga bo'lib yuborilishi mumkin — bot ‼️ yopilguncha kutadi.
  - Hammasi tayyor bo'lgach, admin /tugatdim buyrug'ini yuboradi. Bot 1-44
    barcha savollar va 3 ta matn borligini tekshiradi, WITH_ESSAY bo'lsa
    esse mavzusini so'raydi, keyin testni yakunlaydi.
  - /holat — hozirgi holatni (nechta savol qabul qilingani, nimalar
    yetishmayotgani) ko'rsatadi.
  - /bekor — butun jarayonni bekor qiladi.
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

TOTAL_QUESTIONS = 44
# 18-22 -> ilmiy, 23-27 -> badiiy, 28-32 -> gazal (test tuzilishi doim shu tartibda)
PASSAGE_TYPE_BY_INDEX = ["ilmiy", "badiiy", "gazal"]


def _passage_type_for_order(order_no: int) -> str | None:
    if 18 <= order_no <= 22:
        return "ilmiy"
    if 23 <= order_no <= 27:
        return "badiiy"
    if 28 <= order_no <= 32:
        return "gazal"
    return None


class CreateTest(StatesGroup):
    choosing_type = State()
    collecting = State()
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
    await state.update_data(
        test_type=test_type.value,
        questions={},
        passages=[],
        open_passage_lines=None,
        essay_topic=None,
    )
    await state.set_state(CreateTest.collecting)
    await callback.message.edit_text(
        f"Tanlandi: {'Faqat 44 ta test' if test_type == TestType.ONLY_44 else '44 ta test + esse'}.\n\n"
        "Endi savollarni yuboring — istalgan tartibda, istalgan miqdorda "
        "(bittalab ham, bir nechtasini bitta xabarga jamlab ham bo'ladi).\n\n"
        "Matnlarni (ilmiy, badiiy, g'azal) TABIIY TARTIBDA — avval ilmiy, "
        "keyin badiiy, keyin g'azal — yuboring. Agar matn uzun bo'lib bitta "
        "xabarga sig'masa, davomini keyingi xabar(lar)da yuborishingiz "
        "mumkin, faqat oxirida ‼️ belgisini qo'yishni unutmang.\n\n"
        "Hammasini yuborib bo'lgach /tugatdim buyrug'ini yuboring.\n"
        "Joriy holatni ko'rish uchun /holat, bekor qilish uchun /bekor."
    )
    await callback.answer()


@router.message(Command("holat"), StateFilter(CreateTest.collecting))
async def cmd_status(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    have = sorted(int(k) for k in data.get("questions", {}).keys())
    missing = [n for n in range(1, TOTAL_QUESTIONS + 1) if n not in have]
    passages_count = len(data.get("passages", []))
    lines = [
        f"Qabul qilingan savollar: {len(have)}/{TOTAL_QUESTIONS}",
        f"Matnlar: {passages_count}/3",
    ]
    if data.get("open_passage_lines") is not None:
        lines.append("⏳ Hozir bitta matn davom etmoqda (‼️ bilan hali yopilmagan).")
    if missing:
        lines.append("Yetishmayotgan savollar: " + ", ".join(map(str, missing)))
    else:
        lines.append("✅ Barcha 44 ta savol qabul qilingan.")
    if not missing and passages_count >= 3:
        lines.append("Tayyor bo'lsa /tugatdim yuboring.")
    await message.answer("\n".join(lines))


@router.message(Command("tugatdim"), StateFilter(CreateTest.collecting))
async def cmd_finish(message: Message, state: FSMContext) -> None:
    data = await state.get_data()

    if data.get("open_passage_lines") is not None:
        await message.answer(
            "❌ Bitta matn hali ‼️ bilan yopilmagan. Uni tugating (oxiriga ‼️ qo'ying), "
            "keyin qaytadan /tugatdim yuboring."
        )
        return

    have = sorted(int(k) for k in data.get("questions", {}).keys())
    missing = [n for n in range(1, TOTAL_QUESTIONS + 1) if n not in have]
    if missing:
        await message.answer(
            "❌ Quyidagi savollar hali yuborilmagan: " + ", ".join(map(str, missing))
        )
        return

    passages = data.get("passages", [])
    if len(passages) < 3:
        await message.answer(
            f"❌ Matnlar yetarli emas ({len(passages)}/3). Ilmiy, badiiy va g'azal "
            "matnlarini (tabiiy tartibda) yuboring."
        )
        return

    test_type = TestType(data["test_type"])
    if test_type == TestType.WITH_ESSAY and not data.get("essay_topic"):
        await state.set_state(CreateTest.essay_topic)
        await message.answer(
            "✅ Barcha 44 ta savol va 3 ta matn qabul qilindi.\n\nEndi esse mavzusini kiriting."
        )
        return

    await _finalize_test(message, state)


@router.message(CreateTest.essay_topic)
async def on_essay_topic(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    essay_topic = (message.text or "").strip()
    if not essay_topic:
        await message.answer("❌ Esse mavzusi bo'sh bo'lmasligi kerak. Qaytadan yuboring.")
        return
    data["essay_topic"] = essay_topic
    await state.set_data(data)
    await message.answer("✅ Qabul qilindi.")
    await _finalize_test(message, state)


@router.message(CreateTest.collecting)
async def on_collecting_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    raw_lines = (message.text or "").replace("\r\n", "\n").split("\n")
    replies: list[str] = []
    errors: list[str] = []

    # 1) Agar oldingi xabar(lar)dan buyon ochiq (hali ‼️ bilan yopilmagan) matn bo'lsa,
    #    avval shuni davom ettiramiz.
    if data.get("open_passage_lines") is not None:
        close_idx = next((i for i, ln in enumerate(raw_lines) if ln.strip() == "‼️"), None)
        if close_idx is None:
            data["open_passage_lines"].extend(raw_lines)
            await state.set_data(data)
            await message.answer(
                "📄 Matn davom etmoqda... Tugagach oxiriga alohida qatorda ‼️ belgisini qo'ying."
            )
            return
        passage_text = "\n".join(data["open_passage_lines"] + raw_lines[:close_idx]).strip()
        data["passages"].append(passage_text)
        replies.append(f"✅ {len(data['passages'])}-matn qabul qilindi.")
        data["open_passage_lines"] = None
        raw_lines = raw_lines[close_idx + 1:]

    # 2) Qolgan qatorlarni savol-bloklarga va matnlarga ajratamiz.
    i = 0
    n = len(raw_lines)
    while i < n:
        line = raw_lines[i]
        if line.strip() == "":
            i += 1
            continue

        if line.strip() == "‼️":
            close_idx = next(
                (k for k in range(i + 1, n) if raw_lines[k].strip() == "‼️"), None
            )
            if close_idx is None:
                data["open_passage_lines"] = raw_lines[i + 1:]
                await state.set_data(data)
                if replies:
                    await message.answer("\n".join(replies))
                await message.answer(
                    "📄 Matn boshlandi, lekin shu xabarda tugamadi. Davomini keyingi "
                    "xabar(lar)da yuboring, oxirida ‼️ qo'yishni unutmang."
                )
                return
            passage_text = "\n".join(raw_lines[i + 1:close_idx]).strip()
            data["passages"].append(passage_text)
            replies.append(f"✅ {len(data['passages'])}-matn qabul qilindi.")
            i = close_idx + 1
            continue

        order_no = qp.question_order_no(line)
        if order_no is None:
            errors.append(f"⚠️ Tushunarsiz qator (e'tiborsiz qoldirildi): {line[:60]!r}")
            i += 1
            continue

        # Blok chegarasini topamiz: 33/34/35 birgalikda bitta blok, qolganlari
        # navbatdagi "⁉️" yoki "‼️" gacha.
        j = i + 1
        if order_no in (33, 34, 35):
            while j < n:
                nxt = qp.question_order_no(raw_lines[j])
                if raw_lines[j].strip() == "‼️":
                    break
                if nxt is not None and nxt not in (33, 34, 35):
                    break
                j += 1
        else:
            while j < n:
                if raw_lines[j].strip() == "‼️":
                    break
                if qp.question_order_no(raw_lines[j]) is not None:
                    break
                j += 1

        block_lines = raw_lines[i:j]
        try:
            kind, parsed = qp.classify_and_parse_block(block_lines)
        except qp.ParseError as e:
            errors.append(f"❌ {order_no}-savol atrofida xato: {e}")
            i = j
            continue

        if kind == "matching":
            for qn in parsed.order_nos:
                data["questions"][str(qn)] = dict(
                    order_no=qn,
                    question_type=QuestionType.MATCHING.value,
                    text=parsed.texts[qn],
                    options=parsed.options,
                    correct_option=parsed.correct[qn],
                    explanation=parsed.explanation,
                    passage_type=None,
                )
            replies.append("✅ 33-35-savollar qabul qilindi.")
        elif kind == "single":
            data["questions"][str(parsed.order_no)] = dict(
                order_no=parsed.order_no,
                question_type=QuestionType.SINGLE_CHOICE.value,
                text=parsed.text,
                options=parsed.options,
                correct_option=parsed.correct_option,
                explanation=parsed.explanation,
                passage_type=_passage_type_for_order(parsed.order_no),
            )
            replies.append(f"✅ {parsed.order_no}-savol qabul qilindi.")
        elif kind == "short":
            data["questions"][str(parsed.order_no)] = dict(
                order_no=parsed.order_no,
                question_type=QuestionType.SHORT_ANSWER.value,
                text=parsed.text,
                accepted_answers=parsed.accepted_answers,
                explanation=parsed.explanation,
                passage_type=None,
            )
            replies.append(f"✅ {parsed.order_no}-savol qabul qilindi.")
        elif kind == "twopart":
            data["questions"][str(parsed.order_no)] = dict(
                order_no=parsed.order_no,
                question_type=QuestionType.TWO_PART_SHORT.value,
                text=parsed.text,
                accepted_answers=parsed.part_a_answers,
                explanation=parsed.part_a_explanation,
                part_b_text=parsed.part_b_text,
                part_b_accepted_answers=parsed.part_b_answers,
                part_b_explanation=parsed.part_b_explanation,
                passage_type=None,
            )
            replies.append(f"✅ {parsed.order_no}-savol qabul qilindi.")

        i = j

    await state.set_data(data)

    have = len(data.get("questions", {}))
    summary_parts = []
    if replies:
        summary_parts.append("\n".join(replies))
    if errors:
        summary_parts.append("\n".join(errors))
    summary_parts.append(
        f"Jami qabul qilingan savollar: {have}/{TOTAL_QUESTIONS}. "
        "Davom eting yoki tayyor bo'lsa /tugatdim yuboring. Holat uchun /holat."
    )
    await message.answer("\n\n".join(summary_parts))


async def _finalize_test(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    test_type = TestType(data["test_type"])
    code = generate_test_code()

    passages_list: list[str] = data.get("passages", [])
    passages_dict = {
        PASSAGE_TYPE_BY_INDEX[idx]: text for idx, text in enumerate(passages_list[:3])
    }

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
        for ptype_str, ptext in passages_dict.items():
            passage = Passage(test_id=test.id, passage_type=PassageType(ptype_str), text=ptext)
            session.add(passage)
            passage_rows[ptype_str] = passage
        await session.flush()

        for order_no in sorted(data["questions"].keys(), key=int):
            q = data["questions"][order_no]
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
