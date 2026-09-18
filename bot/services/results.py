"""Test natijalarini hisoblash va (admin bossa) talabgorlarga e'lon qilish.

MUHIM: 44 ta test bali (Rasch) va sertifikat darajasi faqat ADMIN
"Natijalarni yuborish" tugmasini bosgandagina barcha (shu paytgacha
to'plangan) 1-urinishlar asosida QAYTA hisoblanadi va e'lon qilinadi — bu
foydalanuvchi talabiga mos: "Daraja va umumiy natija test yakunlangach emas,
men yuborganimda e'lon qilinadi".

TODO (keyingi bosqich): 2-urinishlar uchun (counts_for_rasch=False) item
qiyinliklarini 1-urinishlardan meros qilib, faqat shu kishining o'z balini
hisoblash. Hozircha bu funksiya faqat 1-urinishlarni hisoblaydi.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import Answer, Attempt, AttemptStatus, LearnerUser, Test
from bot.services.rasch import estimate_rasch
from bot.services.scoring import compute_final


@dataclass
class PublishSummary:
    total_attempts_scored: int
    results: list[Attempt]


async def recompute_test_results(session: AsyncSession, test_id: int) -> PublishSummary:
    """Shu testning barcha 1-urinish (counts_for_rasch=True), yakunlangan
    urinishlari uchun Rasch balini qayta hisoblab, Attempt.rasch_score_75 va
    (esse bali mavjud bo'lsa) final_score/final_grade'ni yangilaydi."""

    result = await session.execute(
        select(Attempt)
        .where(
            Attempt.test_id == test_id,
            Attempt.counts_for_rasch.is_(True),
            Attempt.status == AttemptStatus.FINISHED,
        )
        .options(selectinload(Attempt.answers), selectinload(Attempt.essay))
    )
    attempts = list(result.scalars().all())
    if not attempts:
        return PublishSummary(total_attempts_scored=0, results=[])

    responses: dict[int, dict[int, int]] = {}
    for attempt in attempts:
        answered = {
            a.question_id: (1 if a.is_correct else 0)
            for a in attempt.answers
            if a.is_correct is not None  # belgilanmagan savol hisobga kirmaydi
        }
        if answered:
            responses[attempt.id] = answered

    rasch = estimate_rasch(responses)

    for attempt in attempts:
        score = rasch.person_scores_75.get(attempt.id)
        if score is None:
            continue
        attempt.raw_correct_count = sum(
            1 for a in attempt.answers if a.is_correct
        )
        attempt.rasch_score_75 = score

        essay_score = attempt.essay_score_75
        if essay_score is None and attempt.essay is not None:
            essay_score = attempt.essay.converted_score_75
            attempt.essay_score_75 = essay_score

        if essay_score is not None:
            final, grade = compute_final(score, essay_score)
            attempt.final_score = final
            attempt.final_grade = grade

    await session.commit()
    return PublishSummary(total_attempts_scored=len(attempts), results=attempts)


async def get_learner(session: AsyncSession, attempt: Attempt) -> LearnerUser:
    result = await session.execute(select(LearnerUser).where(LearnerUser.id == attempt.learner_id))
    return result.scalar_one()


async def get_test(session: AsyncSession, test_id: int) -> Test:
    result = await session.execute(select(Test).where(Test.id == test_id))
    return result.scalar_one()
