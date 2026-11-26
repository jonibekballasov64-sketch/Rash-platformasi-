"""Test sessiyasini uzilib qolganda davom ettirish mantiqi.

G'oya: o'quvchi to'satdan chiqib ketsa (internet uzildi, Telegram yopildi),
vaqt "to'xtab turgan" hisoblanadi — davom ettirganda qolgan vaqt uzilgan
paytdagidek bo'ladi va o'quvchi o'sha savoldan davom etadi.
Suiiste'molning oldini olish uchun to'xtab turgan vaqt RESUME_GRACE_MINUTES
bilan cheklanadi: undan uzoq uzilib qolsa, ortiqcha vaqt qaytarilmaydi."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Attempt, AttemptStatus

RESUME_GRACE_MINUTES = 30


@dataclass
class ResumeResult:
    success: bool
    attempt: Attempt | None
    message: str
    remaining_seconds: int | None = None


def _naive(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value


async def pause_attempt(session: AsyncSession, attempt_id: int, reason: str = "network") -> ResumeResult:
    """O'quvchi oynani yopganini bildirganda (pagehide) uzilgan vaqtni belgilaydi."""
    result = await session.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = result.scalar_one_or_none()
    if not attempt:
        return ResumeResult(success=False, attempt=None, message="Urinish topilmadi")
    if attempt.status != AttemptStatus.IN_PROGRESS:
        return ResumeResult(success=False, attempt=None, message="Urinish yakunlangan")
    attempt.paused_at = dt.datetime.utcnow()
    attempt.pause_reason = reason
    await session.commit()
    return ResumeResult(success=True, attempt=attempt, message="Sessiya pauza qilindi")


async def touch_attempt(session: AsyncSession, attempt: Attempt, index: int | None) -> None:
    """WebApp "tirik" ekanini bildiradi (har ~10 soniyada)."""
    attempt.last_seen_at = dt.datetime.utcnow()
    attempt.paused_at = None
    if index is not None and index >= 0:
        attempt.last_index = index
    await session.commit()


async def find_resumable_attempt(session: AsyncSession, test_id: int, learner_id: int) -> Attempt | None:
    """O'quvchining shu testdagi tugallanmagan urinishi (eng oxirgisi)."""
    result = await session.execute(
        select(Attempt)
        .where(
            Attempt.test_id == test_id,
            Attempt.learner_id == learner_id,
            Attempt.status == AttemptStatus.IN_PROGRESS,
        )
        .order_by(Attempt.id.desc())
    )
    return result.scalars().first()


async def apply_resume(session: AsyncSession, attempt: Attempt) -> int:
    """Davom ettirish: uzilgan vaqtni deadline'ga qo'shadi va qolgan soniyalarni
    qaytaradi (<= 0 bo'lsa, vaqt tugagan — WebApp o'zi yakunlaydi)."""
    now = dt.datetime.utcnow()
    deadline = _naive(attempt.deadline_at)
    left_at = _naive(attempt.paused_at) or _naive(attempt.last_seen_at)

    if left_at is not None and left_at < deadline:
        away = now - left_at
        grace = dt.timedelta(minutes=RESUME_GRACE_MINUTES)
        credit = min(max(away, dt.timedelta(0)), grace)
        deadline = deadline + credit
        attempt.deadline_at = deadline

    attempt.paused_at = None
    attempt.pause_reason = None
    attempt.last_seen_at = now
    await session.commit()
    return int((deadline - now).total_seconds())
