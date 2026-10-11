"""Test sessiyasi pause/resume logikasi."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Attempt, AttemptStatus


@dataclass
class ResumeResult:
    """Resume natijasi."""
    success: bool
    attempt: Attempt | None
    message: str
    remaining_seconds: int | None = None


async def pause_attempt(
    session: AsyncSession, 
    attempt_id: int, 
    reason: str = "network"
) -> ResumeResult:
    """Test sessiyasini pause qilish (internet uzildi, app yopildi, etc)."""
    result = await session.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = result.scalar_one_or_none()
    
    if not attempt:
        return ResumeResult(success=False, attempt=None, message="Urinish topilmadi")
    
    if attempt.status != AttemptStatus.IN_PROGRESS:
        return ResumeResult(
            success=False, 
            attempt=None, 
            message=f"Urinish {attempt.status.value} holatida — pause qilib bo'lmaydi"
        )
    
    attempt.paused_at = dt.datetime.utcnow()
    attempt.pause_reason = reason
    await session.commit()
    
    return ResumeResult(
        success=True, 
        attempt=attempt, 
        message="Sessiya pause qilindi"
    )


async def resume_attempt(
    session: AsyncSession, 
    attempt_id: int
) -> ResumeResult:
    """Paused test-ni davom ettirish."""
    result = await session.execute(select(Attempt).where(Attempt.id == attempt_id))
    attempt = result.scalar_one_or_none()
    
    if not attempt:
        return ResumeResult(success=False, attempt=None, message="Urinish topilmadi")
    
    if attempt.status != AttemptStatus.IN_PROGRESS:
        return ResumeResult(
            success=False, 
            attempt=None, 
            message=f"Urinish {attempt.status.value} holatida — davom ettirib bo'lmaydi"
        )
    
    if attempt.paused_at is None:
        return ResumeResult(
            success=False, 
            attempt=None, 
            message="Bu urinish pause holatida emas"
        )
    
    # Vaqt tugab ketdimi?
    now = dt.datetime.utcnow()
    if now > attempt.deadline_at:
        attempt.status = AttemptStatus.EXPIRED
        await session.commit()
        return ResumeResult(
            success=False, 
            attempt=attempt, 
            message="Test vaqti tugab ketgan — davom ettirb bo'lmaydi"
        )
    
    # Qolgan vaqtni hisoblash va yangi deadline'ni set qilish
    time_remaining = attempt.deadline_at - attempt.paused_at
    new_deadline = now + time_remaining
    
    attempt.deadline_at = new_deadline
    attempt.paused_at = None
    attempt.pause_reason = None
    
    await session.commit()
    
    remaining_seconds = int(time_remaining.total_seconds())
    
    return ResumeResult(
        success=True, 
        attempt=attempt, 
        message="Sessiya davom ettiririldi",
        remaining_seconds=remaining_seconds
    )


async def get_resumable_attempt(
    session: AsyncSession, 
    test_id: int, 
    learner_id: int
) -> Attempt | None:
    """O'quvchining shu testda pause qilingan urinishi mavjudmi?"""
    result = await session.execute(
        select(Attempt).where(
            Attempt.test_id == test_id,
            Attempt.learner_id == learner_id,
            Attempt.status == AttemptStatus.IN_PROGRESS,
            Attempt.paused_at.isnot(None),  # Pause holatida
        )
    )
    return result.scalar_one_or_none()
