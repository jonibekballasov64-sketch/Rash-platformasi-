"""O'quvchi test ishlaydigan Web App uchun yengil backend (FastAPI).

Bu Telegram bot'dan ALOHIDA jarayon sifatida ishga tushadi (Railway'da
alohida service sifatida deploy qilinadi):
    uvicorn webapp_server.app:app --host 0.0.0.0 --port $PORT

Vazifasi:
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
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.db.base import get_session
from bot.db.models import (
    Answer,
    Attempt,
    AttemptStatus,
    EssayResponse,
    Question,
    QuestionType,
    Test,
    TestType,
)
from bot.services.essay import NotConfiguredError, grade_essay
from bot.services.scoring import MIN_ESSAY_WORDS

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


# --------------------------------------------------------------------------- #
# Pydantic sxemalar
# --------------------------------------------------------------------------- #


class AnswerIn(BaseModel):
    question_id: int
    sub_part: str | None = None  # "A" yoki "B" (faqat 40-44 uchun)
    given_answer: str


class EssayIn(BaseModel):
    text: str


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
