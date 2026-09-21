"""O'quvchi test ishlaydigan Web App uchun yengil backend (FastAPI).

Bu Telegram bot'dan ALOHIDA jarayon sifatida ishga tushadi (Railway'da
alohida service sifatida deploy qilinadi):
    uvicorn webapp_server.app:app --host 0.0.0.0 --port $PORT

Vazifasi:
  - POST /api/register                       -> ism-familiya/test kodi/toifani
        WebApp ichida qabul qilib, Attempt yaratadi (chatda so'rov yo'q).
        Admin (ADMIN_IDS) uchun 2 martalik urinish chegarasi qo'llanilmaydi.
  - GET  /api/attempt/{attempt_id}          -> shu urinishga tegishli test
        tuzilishini (savollar, variantlar, passage'lar) TO'G'RI JAVOBLARSIZ
        qaytaradi, taymer uchun deadline bilan birga.
  - POST /api/attempt/{attempt_id}/answer   -> bitta savolga javobni saqlaydi
        va to'g'ri/xato ekanligini (faqat serverda) belgilaydi.
  - POST /api/attempt/{attempt_id}/essay    -> 2-tur uchun esse matnini
        saqlaydi (yakunlashda AI tekshiradi).
  - POST /api/attempt/{attempt_id}/finish   -> urinishni yakunlaydi, xom
        natijani (necha/44) qaytaradi. Rasch bali va daraja BU YERDA
        HISOBLANMAYDI — admin "Natijalarni yuborish"ni bosganda hisoblanadi
        (services/results.py).
  - GET  /api/attempt/{attempt_id}/review   -> yakunlangach javob/izohlarni
        ko'rish uchun to'liq ma'lumot (✅/⚠️ bilan).
  - static/ -> webapp/ papkasidagi HTML/CSS/JS fayllarni xizmat qiladi.

DIQQAT: bu MVP darajasidagi ilova. Aniq vizual talablar (33-35 uchun
sariq-qiya fon, so'z birikmalari uchun ko'k ramka va h.k.) `webapp/style.css`
faylida CSS class'lar sifatida belgilangan — dizaynni yanada silliqlashtirish
kerak bo'lsa shu joyni boyitish kifoya, backend struktura o'zgarmaydi.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from bot.config import settings
from bot.db.base import get_session
from bot.db.models import (
    Answer,
    Attempt,
    AttemptStatus,
    Category,
    EssayResponse,
    LearnerUser,
    Question,
    QuestionType,
    Test,
    TestStatus,
    TestType,
)
from bot.services.essay import NotConfiguredError, grade_essay
from bot.services.scoring import MIN_ESSAY_WORDS

MAX_ATTEMPTS = 2

logger = logging.getLogger(__name__)

app = FastAPI(title="Milliy Sertifikat Test WebApp API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

WEBAPP_DIR = Path(__file__).resolve().parent.parent / "webapp"
if WEBAPP_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEBAPP_DIR)), name="static")


@app.get("/test")
async def serve_test_page() -> FileResponse:
    return FileResponse(str(WEBAPP_DIR / "index.html"))


@app.get("/register")
async def serve_register_page() -> FileResponse:
    return FileResponse(str(WEBAPP_DIR / "register.html"))


# --------------------------------------------------------------------------- #
# Pydantic sxemalar
# --------------------------------------------------------------------------- #

class AnswerIn(BaseModel):
    question_id: int
    sub_part: str | None = None  # "A" yoki "B" (faqat 40-44 uchun)
    given_answer: str


class EssayIn(BaseModel):
    text: str


class RegisterIn(BaseModel):
    init_data: str
    full_name: str
    test_code: str
    category: str


# --------------------------------------------------------------------------- #
# Telegram WebApp initData'ni tekshirish (ro'yxatdan o'tish uchun) — chatda
# hech narsa so'ralmasdan, to'g'ridan-to'g'ri WebApp ichida ism/kod/toifa
# olinganda, foydalanuvchi ID'sini Telegram tomonidan imzolangan holda
# ishonchli tekshirish shart (aks holda telegram_id'ni soxtalashtirish mumkin
# bo'lardi). Rasmiy algoritm:
# https://core.telegram.org/bots/webapps#validating-data-received-via-the-web-app
# --------------------------------------------------------------------------- #

def _verify_init_data(init_data: str) -> dict[str, Any]:
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        raise HTTPException(401, "Noto'g'ri ma'lumot (init_data)")

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise HTTPException(401, "Tekshiruv ma'lumoti topilmadi")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise HTTPException(401, "Ma'lumot tasdiqlanmadi. Botni Telegram ichida qaytadan oching.")

    import json as _json

    user_raw = pairs.get("user")
    if not user_raw:
        raise HTTPException(401, "Foydalanuvchi ma'lumoti topilmadi")
    return _json.loads(user_raw)


async def _is_group_member(user_id: int) -> bool:
    url = f"https://api.telegram.org/bot{settings.bot_token}/getChatMember"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                url, params={"chat_id": settings.allowed_group_id, "user_id": user_id}
            )
        data = resp.json()
    except Exception:
        return False
    if not data.get("ok"):
        return False
    status = data["result"].get("status")
    return status not in ("left", "kicked")


def _naive_utc(value: dt.datetime) -> dt.datetime:
    """DB'dan timezone-aware yoki naive qaytishidan qat'i nazar, taqqoslash
    uchun har doim naive (tzinfo'siz) UTC datetime qaytaradi. Buning aksi
    (naive va aware datetime'larni to'g'ridan-to'g'ri solishtirish) Python'da
    TypeError beradi va bu /finish endpointida 500 xatolikka olib kelishi
    mumkin edi."""
    if value.tzinfo is not None:
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value


def _check_answer(question: Question, sub_part: str | None, given: str) -> bool:
    given_norm = given.strip().lower()
    if question.question_type in (QuestionType.SINGLE_CHOICE, QuestionType.MATCHING):
        return given_norm.upper() == (question.correct_option or "").upper()

    if question.question_type == QuestionType.SHORT_ANSWER:
        accepted = [a.strip().lower() for a in (question.accepted_answers or [])]
        return given_norm in accepted

    if question.question_type == QuestionType.TWO_PART_SHORT:
        if sub_part == "A":
            accepted = [a.strip().lower() for a in (question.accepted_answers or [])]
        else:
            accepted = [a.strip().lower() for a in (question.part_b_accepted_answers or [])]
        return given_norm in accepted

    return False


# --------------------------------------------------------------------------- #
# Endpointlar
# --------------------------------------------------------------------------- #

@app.post("/api/register")
async def register(payload: RegisterIn) -> dict[str, Any]:
    """Ism-familiya / test kodi / toifani WebApp ichida qabul qilib, Attempt
    yaratadi — bot chatida hech qanday savol-javob bo'lmaydi."""
    tg_user = _verify_init_data(payload.init_data)
    telegram_id = tg_user.get("id")
    if telegram_id is None:
        raise HTTPException(401, "Foydalanuvchi ID topilmadi")

    if not await _is_group_member(telegram_id):
        raise HTTPException(
            403, "Botdan foydalanish uchun avval belgilangan guruhga a'zo bo'lishingiz kerak."
        )

    full_name = payload.full_name.strip()
    if len(full_name) < 3:
        raise HTTPException(400, "Iltimos, to'liq ism-familiyangizni kiriting.")

    try:
        category = Category(payload.category)
    except ValueError:
        raise HTTPException(400, "Noto'g'ri toifa tanlandi.")

    code = payload.test_code.strip().upper()

    async with get_session() as session:
        test_result = await session.execute(select(Test).where(Test.code == code))
        test = test_result.scalar_one_or_none()

        if test is None or test.status == TestStatus.DRAFT:
            raise HTTPException(404, "Bunday kod bilan test topilmadi. Qaytadan kiriting.")
        if test.status == TestStatus.CLOSED:
            raise HTTPException(400, "Bu test yopilgan, endi urinish qabul qilinmaydi.")

        learner_result = await session.execute(
            select(LearnerUser).where(LearnerUser.telegram_id == telegram_id)
        )
        learner = learner_result.scalar_one_or_none()
        if learner is None:
            learner = LearnerUser(telegram_id=telegram_id, full_name=full_name)
            session.add(learner)
            await session.flush()
        else:
            learner.full_name = full_name

        count_result = await session.execute(
            select(func.count(Attempt.id)).where(
                Attempt.test_id == test.id, Attempt.learner_id == learner.id
            )
        )
        attempts_so_far = count_result.scalar_one()

        # Admin (ADMIN_IDS ro'yxatidagi Telegram ID'lar) uchun 2 martalik
        # urinish chegarasi qo'llanilmaydi — cheksiz urinish mumkin.
        is_admin = telegram_id in settings.admin_id_list
        if not is_admin and attempts_so_far >= MAX_ATTEMPTS:
            raise HTTPException(
                400, "Siz bu testga allaqachon 2 marta urinib bo'lgansiz. Boshqa urinish mumkin emas."
            )

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

        return {
            "attempt_id": attempt.id,
            "attempt_number": attempt_number,
            "duration_minutes": test.duration_minutes,
        }


@app.get("/api/attempt/{attempt_id}")
async def get_attempt(attempt_id: int) -> dict[str, Any]:
    async with get_session() as session:
        result = await session.execute(
            select(Attempt)
            .where(Attempt.id == attempt_id)
            .options(selectinload(Attempt.test).selectinload(Test.questions).selectinload(Question.passage))
        )
        attempt = result.scalar_one_or_none()
        if attempt is None:
            raise HTTPException(404, "Urinish topilmadi")

        test = attempt.test
        questions_payload = []
        for q in sorted(test.questions, key=lambda x: x.order_no):
            item: dict[str, Any] = {
                "id": q.id,
                "order_no": q.order_no,
                "type": q.question_type.value,
                "text": q.text,
            }
            if q.passage is not None:
                item["passage"] = {"type": q.passage.passage_type.value, "text": q.passage.text}
            if q.question_type in (QuestionType.SINGLE_CHOICE, QuestionType.MATCHING):
                item["options"] = q.options
            if q.question_type == QuestionType.TWO_PART_SHORT:
                item["part_b_text"] = q.part_b_text
            questions_payload.append(item)

        return {
            "attempt_id": attempt.id,
            "test_type": test.test_type.value,
            "deadline_at": attempt.deadline_at.isoformat(),
            "essay_topic": test.essay_topic,
            "essay_min_words": MIN_ESSAY_WORDS,
            "status": attempt.status.value,
            "questions": questions_payload,
        }


@app.post("/api/attempt/{attempt_id}/answer")
async def submit_answer(attempt_id: int, payload: AnswerIn) -> dict[str, Any]:
    async with get_session() as session:
        attempt_result = await session.execute(select(Attempt).where(Attempt.id == attempt_id))
        attempt = attempt_result.scalar_one_or_none()
        if attempt is None:
            raise HTTPException(404, "Urinish topilmadi")
        if attempt.status != AttemptStatus.IN_PROGRESS:
            raise HTTPException(400, "Bu urinish allaqachon yakunlangan")
        if dt.datetime.utcnow() > _naive_utc(attempt.deadline_at):
            raise HTTPException(400, "Vaqt tugagan")

        question_result = await session.execute(select(Question).where(Question.id == payload.question_id))
        question = question_result.scalar_one_or_none()
        if question is None:
            raise HTTPException(404, "Savol topilmadi")

        is_correct = _check_answer(question, payload.sub_part, payload.given_answer)

        existing_result = await session.execute(
            select(Answer).where(
                Answer.attempt_id == attempt_id,
                Answer.question_id == payload.question_id,
                Answer.sub_part == payload.sub_part,
            )
        )
        answer = existing_result.scalar_one_or_none()
        if answer is None:
            answer = Answer(
                attempt_id=attempt_id,
                question_id=payload.question_id,
                sub_part=payload.sub_part,
            )
            session.add(answer)
        answer.given_answer = payload.given_answer
        answer.is_correct = is_correct

        await session.commit()
        return {"saved": True}


@app.post("/api/attempt/{attempt_id}/essay")
async def submit_essay_draft(attempt_id: int, payload: EssayIn) -> dict[str, Any]:
    """Esse matnini (hali yakunlanmagan holatda ham) saqlab boradi, shunda
    vaqt tugab avto-yakunlansa ham yozilgan matn yo'qolmaydi."""
    async with get_session() as session:
        attempt_result = await session.execute(select(Attempt).where(Attempt.id == attempt_id))
        attempt = attempt_result.scalar_one_or_none()
        if attempt is None:
            raise HTTPException(404, "Urinish topilmadi")

        essay_result = await session.execute(select(EssayResponse).where(EssayResponse.attempt_id == attempt_id))
        essay = essay_result.scalar_one_or_none()
        if essay is None:
            essay = EssayResponse(attempt_id=attempt_id, text="", word_count=0)
            session.add(essay)
        essay.text = payload.text
        essay.word_count = len([w for w in payload.text.split() if w.strip()])
        await session.commit()
        return {"saved": True, "word_count": essay.word_count}


@app.post("/api/attempt/{attempt_id}/finish")
async def finish_attempt(attempt_id: int) -> dict[str, Any]:
    async with get_session() as session:
        try:
            result = await session.execute(
                select(Attempt)
                .where(Attempt.id == attempt_id)
                .options(
                    selectinload(Attempt.answers),
                    selectinload(Attempt.essay),
                    selectinload(Attempt.test),
                )
            )
            attempt = result.scalar_one_or_none()
            if attempt is None:
                raise HTTPException(404, "Urinish topilmadi")
            if attempt.status == AttemptStatus.FINISHED:
                return {"already_finished": True}

            was_expired = dt.datetime.utcnow() > _naive_utc(attempt.deadline_at)
            attempt.status = AttemptStatus.EXPIRED if was_expired else AttemptStatus.FINISHED
            attempt.finished_at = dt.datetime.utcnow()

            raw_correct = sum(1 for a in attempt.answers if a.is_correct)
            attempt.raw_correct_count = raw_correct

            essay_score_75 = None
            if attempt.test.test_type == TestType.WITH_ESSAY:
                essay_text = attempt.essay.text if attempt.essay else ""
                try:
                    grade_result = await grade_essay(essay_text, attempt.test.essay_topic or "")
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
                    essay_score_75 = grade_result.converted_score_75
                    attempt.essay_score_75 = essay_score_75
                except NotConfiguredError:
                    # AI hali ulanmagan — esse matni saqlanadi, ball keyinroq
                    # admin tomonidan qo'lda ham kiritilishi mumkin
                    pass
                except Exception:
                    # OpenAI vaqtincha ishlamasa (400/429/500 va h.k.) ham
                    # o'quvchi testni yakunlay olishi kerak — esse bali
                    # keyinroq admin tomonidan qayta hisoblanishi mumkin.
                    logger.exception(
                        "Esse AI baholashda xato (attempt_id=%s), test baribir yakunlanadi",
                        attempt_id,
                    )

            await session.commit()

            return {
                "status": attempt.status.value,
                "raw_correct_count": raw_correct,
                "total_questions": 44,
                "essay_score_75": essay_score_75,
                "note": "Daraja va yakuniy ball test yakunlangach EMAS, admin natijalarni e'lon qilganda chiqadi.",
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("finish_attempt xatosi (attempt_id=%s)", attempt_id)
            raise HTTPException(
                500,
                f"Ichki xatolik yuz berdi (attempt_id={attempt_id}). Admin bilan bog'laning, "
                "Railway loglarida batafsili xato ko'rsatilgan.",
            )


@app.get("/api/attempt/{attempt_id}/review")
async def review_attempt(attempt_id: int) -> dict[str, Any]:
    async with get_session() as session:
        result = await session.execute(
            select(Attempt)
            .where(Attempt.id == attempt_id)
            .options(
                selectinload(Attempt.answers).selectinload(Answer.question),
                selectinload(Attempt.essay),
            )
        )
        attempt = result.scalar_one_or_none()
        if attempt is None:
            raise HTTPException(404, "Urinish topilmadi")
        if attempt.status == AttemptStatus.IN_PROGRESS:
            raise HTTPException(400, "Test hali yakunlanmagan")

        items = []
        for a in sorted(attempt.answers, key=lambda x: x.question.order_no):
            q = a.question
            explanation = q.explanation
            if q.question_type == QuestionType.TWO_PART_SHORT and a.sub_part == "B":
                explanation = q.part_b_explanation
            items.append(
                {
                    "order_no": q.order_no,
                    "sub_part": a.sub_part,
                    "question_text": q.text,
                    "given_answer": a.given_answer,
                    "correct_option": q.correct_option,
                    "is_correct": a.is_correct,
                    "explanation": explanation,
                }
            )

        return {
            "final_score": attempt.final_score,
            "final_grade": attempt.final_grade,
            "rasch_score_75": attempt.rasch_score_75,
            "essay_score_75": attempt.essay_score_75,
            "items": items,
        }
