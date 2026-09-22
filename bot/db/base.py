from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.config import settings
from bot.db.models import Base

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Jadvallarni yaratadi (birinchi ishga tushirishda). Kelajakda o'zgarishlar
    uchun Alembic migratsiyalariga o'tish tavsiya etiladi."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all faqat YO'Q jadvallarni yaratadi, mavjud jadvalga yangi
        # ustun QO'SHMAYDI — shu sabab avval yaratilgan "attempts" jadvaliga
        # keyinroq qo'shilgan ustunlar (masalan published_at) uchun qo'lda,
        # lekin xavfsiz (bir necha marta ishga tushsa ham xato bermaydigan)
        # ALTER TABLE bajariladi.
        await conn.execute(
            text("ALTER TABLE attempts ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ")
        )
        # Esse baholashning yangi batafsil (12 bandlik xatolar + ogohlantirish)
        # tahlilini saqlash uchun keyinroq qo'shilgan ustunlar
        await conn.execute(
            text("ALTER TABLE essay_responses ADD COLUMN IF NOT EXISTS band_errors JSONB")
        )
        await conn.execute(
            text("ALTER TABLE essay_responses ADD COLUMN IF NOT EXISTS warnings JSONB")
        )


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
