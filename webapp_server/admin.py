"""Admin paneli (veb): yaratilgan testlar ro'yxati, tahrirlash, to'xtatish /
qayta ochish, natijalarni ko'rish va PDF olish.

Hamma endpointlar Telegram WebApp initData (X-Init-Data sarlavhasi) bilan
tasdiqlanadi va faqat settings.admin_id_list dagi adminlarga ruxsat beradi."""
from __future__ import annotations

import unicodedata
from typing import Any

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from bot.config import settings
from bot.db.base import get_session
from bot.db.models import (
    Answer,
    Attempt,
    AttemptStatus,
    Passage,
    Question,
    Test,
    TestStatus,
)
from bot.services.pdf_report import generate_results_pdf
from bot.services.results import recompute_test_results

router = APIRouter(prefix="/api/admin")

CATEGORY_LABELS = {
    "filolog": "Filolog o'qituvchisi",
    "boshlangich": "Boshlang'ich o'qituvchisi",
    "abituriyent_asosiy": "Abituriyent (asosiy)",
    "abituriyent_majburiy": "Abituriyent (majburiy)",
}
STATUS_LABELS = {"draft": "Qoralama", "ready": "Ochiq", "closed": "To'xtatilgan"}


def _admin_id(init_data: str | None) -> int:
    from webapp_server.app import _verify_init_data  # kech import: aylanma bog'liqlik yo'q

    if not init_data:
        raise HTTPException(401, "Telegram ichida oching")
    user = _verify_init_data(init_data)
    uid = user.get("id")
    if uid not in settings.admin_id_list:
        raise HTTPException(403, "Bu bo'lim faqat adminlar uchun")
    return uid


def _clean(name: str | None) -> str:
    return unicodedata.normalize("NFKC", name) if name else "Noma'lum"


@router.get("/tests")
async def list_tests(x_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    _admin_id(x_init_data)
    async with get_session() as session:
        tests = (await session.execute(select(Test).order_by(Test.created_at, Test.id))).scalars().all()
        counts = {}
        rows = await session.execute(
            select(Attempt.test_id, Attempt.status, func.count(Attempt.id)).group_by(Attempt.test_id, Attempt.status)
        )
        for tid, st, n in rows:
            counts.setdefault(tid, {})[st.value] = n
        items = []
        for i, t in enumerate(tests, start=1):
            c = counts.get(t.id, {})
            items.append(
                {
                    "n": i,
                    "id": t.id,
                    "code": t.code,
                    "title": t.title,
                    "status": t.status.value,
                    "status_label": STATUS_LABELS.get(t.status.value, t.status.value),
                    "finished": c.get("finished", 0) + c.get("expired", 0),
                    "in_progress": c.get("in_progress", 0),
                }
            )
    return {"tests": items}


def _q_payload(q: Question) -> dict[str, Any]:
    return {
        "id": q.id,
        "order_no": q.order_no,
        "type": q.question_type.value,
        "text": q.text,
        "options": q.options,
        "correct_option": q.correct_option,
        "accepted_answers": q.accepted_answers,
        "part_a_text": q.part_a_text,
        "part_b_text": q.part_b_text,
        "part_b_accepted_answers": q.part_b_accepted_answers,
        "part_b_explanation": q.part_b_explanation,
        "explanation": q.explanation,
    }


@router.get("/tests/{test_id}")
async def test_detail(test_id: int, x_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    _admin_id(x_init_data)
    async with get_session() as session:
        t = (
            await session.execute(
                select(Test).where(Test.id == test_id).options(selectinload(Test.questions), selectinload(Test.passages))
            )
        ).scalar_one_or_none()
        if t is None:
            raise HTTPException(404, "Test topilmadi")
        return {
            "id": t.id,
            "code": t.code,
            "title": t.title,
            "status": t.status.value,
            "status_label": STATUS_LABELS.get(t.status.value, t.status.value),
            "duration_minutes": t.duration_minutes,
            "questions": [_q_payload(q) for q in sorted(t.questions, key=lambda x: x.order_no)],
            "passages": [{"id": p.id, "type": p.passage_type.value, "text": p.text} for p in t.passages],
        }


class TestEdit(BaseModel):
    title: str | None = None
    duration_minutes: int | None = None


@router.put("/tests/{test_id}")
async def edit_test(test_id: int, payload: TestEdit, x_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    _admin_id(x_init_data)
    async with get_session() as session:
        t = (await session.execute(select(Test).where(Test.id == test_id))).scalar_one_or_none()
        if t is None:
            raise HTTPException(404, "Test topilmadi")
        if payload.title is not None:
            t.title = payload.title.strip()[:255]
        if payload.duration_minutes is not None:
            if not 1 <= payload.duration_minutes <= 600:
                raise HTTPException(400, "Davomiylik 1–600 daqiqa bo'lishi kerak")
            t.duration_minutes = payload.duration_minutes
        await session.commit()
    return {"ok": True}


class QuestionEdit(BaseModel):
    text: str | None = None
    options: dict[str, str] | None = None
    correct_option: str | None = None
    accepted_answers: list[str] | None = None
    part_a_text: str | None = None
    part_b_text: str | None = None
    part_b_accepted_answers: list[str] | None = None
    part_b_explanation: str | None = None
    explanation: str | None = None


@router.put("/questions/{qid}")
async def edit_question(qid: int, payload: QuestionEdit, x_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    _admin_id(x_init_data)
    data = payload.model_dump(exclude_unset=True)
    async with get_session() as session:
        q = (await session.execute(select(Question).where(Question.id == qid))).scalar_one_or_none()
        if q is None:
            raise HTTPException(404, "Savol topilmadi")
        for k, v in data.items():
            if k in ("accepted_answers", "part_b_accepted_answers") and v is not None:
                v = [x.strip() for x in v if x.strip()]
            if k == "correct_option" and v:
                v = v.strip().upper()[:2]
            setattr(q, k, v)
        await session.commit()
    return {"ok": True}


class PassageEdit(BaseModel):
    text: str


@router.put("/passages/{pid}")
async def edit_passage(pid: int, payload: PassageEdit, x_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    _admin_id(x_init_data)
    async with get_session() as session:
        p = (await session.execute(select(Passage).where(Passage.id == pid))).scalar_one_or_none()
        if p is None:
            raise HTTPException(404, "Matn topilmadi")
        p.text = payload.text
        await session.commit()
    return {"ok": True}


class StatusChange(BaseModel):
    action: str  # "close" | "reopen"


@router.post("/tests/{test_id}/status")
async def change_status(test_id: int, payload: StatusChange, x_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    _admin_id(x_init_data)
    async with get_session() as session:
        t = (await session.execute(select(Test).where(Test.id == test_id))).scalar_one_or_none()
        if t is None:
            raise HTTPException(404, "Test topilmadi")
        if payload.action == "close":
            t.status = TestStatus.CLOSED
        elif payload.action == "reopen":
            t.status = TestStatus.READY
        else:
            raise HTTPException(400, "Noto'g'ri amal")
        await session.commit()
        return {"status": t.status.value, "status_label": STATUS_LABELS[t.status.value]}


@router.get("/tests/{test_id}/results")
async def test_results(test_id: int, x_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    _admin_id(x_init_data)
    async with get_session() as session:
        # Faqat bazani yangilaydi (Rasch/yakuniy ball); o'quvchilarga hech narsa yuborilmaydi
        await recompute_test_results(session, test_id)
        res = await session.execute(
            select(Attempt).where(Attempt.test_id == test_id).options(selectinload(Attempt.learner))
        )
        attempts = list(res.scalars().all())
    rows = []
    for a in attempts:
        rows.append(
            {
                "name": _clean(a.learner.full_name),
                "category": CATEGORY_LABELS.get(a.category.value, a.category.value),
                "status": {"in_progress": "Ishlayapti", "finished": "Yakunlagan", "expired": "Vaqt tugagan"}.get(
                    a.status.value, a.status.value
                ),
                "correct": a.raw_correct_count,
                "rasch": round(a.rasch_score_75, 1) if a.rasch_score_75 is not None else None,
                "extra": round(a.essay_score_75, 1) if a.essay_score_75 is not None else None,
                "final": round(a.final_score, 1) if a.final_score is not None else None,
                "grade": a.final_grade,
            }
        )
    rows.sort(key=lambda r: (r["final"] is None, -(r["final"] or 0), -(r["rasch"] or 0)))
    return {"rows": rows}


@router.post("/tests/{test_id}/send-pdf")
async def send_pdf(test_id: int, x_init_data: str | None = Header(default=None)) -> dict[str, Any]:
    admin_id = _admin_id(x_init_data)
    async with get_session() as session:
        await recompute_test_results(session, test_id)
        test = (
            await session.execute(select(Test).where(Test.id == test_id).options(selectinload(Test.created_by)))
        ).scalar_one_or_none()
        if test is None:
            raise HTTPException(404, "Test topilmadi")
        questions = list((await session.execute(select(Question).where(Question.test_id == test_id))).scalars().all())
        attempts = list(
            (
                await session.execute(
                    select(Attempt)
                    .where(Attempt.test_id == test_id, Attempt.status.in_([AttemptStatus.FINISHED, AttemptStatus.EXPIRED]))
                    .options(selectinload(Attempt.learner), selectinload(Attempt.answers).selectinload(Answer.question))
                )
            )
            .scalars()
            .all()
        )
        admin_name = _clean(test.created_by.full_name) if test.created_by else None
        code, title = test.code, test.title
    if not attempts:
        raise HTTPException(400, "Hali hech kim bu testni yakunlamagan.")
    pdf = generate_results_pdf(test, attempts, questions, admin_name=admin_name)
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"https://api.telegram.org/bot{settings.bot_token}/sendDocument",
            data={"chat_id": str(admin_id), "caption": f"📄 {title} ({code}) — {len(attempts)} kishining joriy natijasi."},
            files={"document": (f"{code}_natijalar.pdf", pdf, "application/pdf")},
        )
    if r.status_code != 200:
        raise HTTPException(502, "Faylni Telegramga yuborib bo'lmadi")
    return {"ok": True, "count": len(attempts)}
