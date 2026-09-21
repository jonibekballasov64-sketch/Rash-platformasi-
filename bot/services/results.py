"""Test natijalarini hisoblash va (admin bossa) talabgorlarga e'lon qilish.

MUHIM (yangi tartib): "Natijalarni yangilash va yuborish" tugmasi bosilganda
Rasch bali hisob-kitobi (item qiyinliklari) ANIQLIK uchun HAR DOIM shu
paytgacha to'plangan BARCHA 1-urinishlar asosida qayta baholanadi — lekin bu
qiymat faqat hali E'LON QILINMAGAN (Attempt.published_at hali bo'sh)
urinishlarga YOZILADI va faqat ularga xabar yuboriladi. Bir marta e'lon
qilingan (published_at to'ldirilgan) urinishning Rasch/yakuniy bali va
darajasi shu zahoti "qulflanadi": undan keyin yana necha marta odam qo'shilib,
tugma qayta bosilsa ham, o'sha urinish boshqa o'zgarmaydi va ikkinchi marta
xabar bormaydi — foydalanuvchi talabiga mos: "Yangilash va natijani
hisoblasam bossam, eski (allaqachon e'lon qilingan) natijalar hisobi
tegilmasdan qoladi, faqat yangi qo'shilgan shaxslar hisoblanadi va yuboriladi".

`mark_published=False` (masalan "Joriy natijani olish (fayl)" eksporti
paytida) hali e'lon qilinmagan urinishlarning JORIY (tentativ) balini
ko'rsatish uchun hisoblab bazaga yozadi, lekin published_at'ni TO'LDIRMAYDI —
shu sabab bu urinishlar keyinroq haqiqiy "Natijalarni yangilash va
yuborish"da baribir qayta hisoblanadi va e'lon qilinadi.

TODO (keyingi bosqich): 2-urinishlar uchun (counts_for_rasch=False) item
qiyinliklarini 1-urinishlardan meros qilib, faqat shu kishining o'z balini
hisoblash. Hozircha bu funksiya faqat 1-urinishlarni hisoblaydi.
"""
from __future__ import annotations

import datetime as dt
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


async def recompute_test_results(
    session: AsyncSession, test_id: int, mark_published: bool = False
) -> PublishSummary:
    """Shu testning barcha 1-urinish (counts_for_rasch=True), yakunlangan
    urinishlari orasidan HALI E'LON QILINMAGANLARI uchun Rasch balini qayta
    hisoblab, Attempt.rasch_score_75 va (esse bali mavjud bo'lsa)
    final_score/final_grade'ni yangilaydi. Allaqachon e'lon qilingan
    (published_at to'ldirilgan) urinishlarga TEGILMAYDI.

    mark_published=True bo'lsa (haqiqiy "Natijalarni yangilash va yuborish"
    bosilganda), yangi hisoblangan urinishlarga published_at=hozir belgilanadi
    va shundan keyin ular boshqa qayta hisoblanmaydi/qayta e'lon qilinmaydi."""

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

    # Item qiyinligini iloji boricha aniq baholash uchun kalibratsiyada
    # BARCHA (eski e'lon qilingan + yangi) urinishlarning javoblari
    # ishlatiladi — faqat natijani YOZISH va E'LON QILISH bosqichida
    # allaqachon e'lon qilinganlar chetlab o'tiladi.
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

    updated: list[Attempt] = []
    for attempt in attempts:
        if attempt.published_at is not None:
            continue  # allaqachon e'lon qilingan — qulflangan, tegilmaymiz

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

        if mark_published:
            attempt.published_at = dt.datetime.utcnow()

        updated.append(attempt)

    await session.commit()
    return PublishSummary(total_attempts_scored=len(updated), results=updated)


async def get_learner(session: AsyncSession, attempt: Attempt) -> LearnerUser:
    result = await session.execute(select(LearnerUser).where(LearnerUser.id == attempt.learner_id))
    return result.scalar_one()


async def get_test(session: AsyncSession, test_id: int) -> Test:
    result = await session.execute(select(Test).where(Test.id == test_id))
    return result.scalar_one()
