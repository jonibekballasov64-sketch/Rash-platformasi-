"""Bot kirish nuqtasi. Railway'da `python -m bot.main` orqali ishga tushadi
(Procfile / railway.json shunga sozlangan)."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.db.base import init_db
from bot.handlers.admin.create_test import router as admin_create_test_router
from bot.handlers.admin.my_tests import router as admin_my_tests_router
from bot.handlers.student.start import router as student_start_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    await init_db()

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(admin_create_test_router)
    dp.include_router(admin_my_tests_router)
    dp.include_router(student_start_router)

    logger.info("Bot ishga tushdi (polling).")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
