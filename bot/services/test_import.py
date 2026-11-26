"""pending_tests/*.json fayllarini ishga tushganda avtomatik bazaga yuklaydi.

Har bir fayl bitta testni tasvirlaydi (kod, nom, turi, matnlar, savollar).
Idempotent: shu kodli test bazada bor bo'lsa, qayta yuklanmaydi (o'quvchilar
natijalari va test holatiga tegilmaydi)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select

from bot.config import settings
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

logger = logging.getLogger(__name__)

PENDING_DIR = Path(__file__).resolve().parent.parent.parent / "pending_tests"


async def import_pending_tests() -> None:
    if not PENDING_DIR.is_dir():
        return
    files = sorted(PENDING_DIR.glob("*.json"))
    if not files:
        return
    admin_ids = settings.admin_id_list
    if not admin_ids:
        logger.warning("AUTO-IMPORT: ADMIN_IDS bo'sh, testlar yuklanmadi")
        return

    for path in files:
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
            await _import_one(spec, admin_ids[0])
        except Exception:
            logger.exception("AUTO-IMPORT: %s yuklanmadi", path.name)


async def _import_one(spec: dict, admin_telegram_id: int) -> None:
    code = spec["code"]
    async with get_session() as session:
        exists = await session.execute(select(Test.id).where(Test.code == code))
        if exists.scalar_one_or_none() is not None:
            logger.info("AUTO-IMPORT: %s allaqachon bor, o'tkazib yuborildi", code)
            return

        res = await session.execute(
            select(AdminUser).where(AdminUser.telegram_id == admin_telegram_id)
        )
        admin = res.scalar_one_or_none()
        if admin is None:
            admin = AdminUser(telegram_id=admin_telegram_id, full_name="")
            session.add(admin)
            await session.flush()

        test_type = TestType(spec.get("test_type", "only_44"))
        test = Test(
            code=code,
            title=spec.get("title", ""),
            test_type=test_type,
            status=TestStatus.READY,
            duration_minutes=int(spec.get("duration_minutes", 120)),
            essay_topic=spec.get("essay_topic"),
            created_by=admin,
        )
        session.add(test)
        await session.flush()

        passages: dict[str, Passage] = {}
        for ptype, text in spec.get("passages", {}).items():
            row = Passage(test_id=test.id, passage_type=PassageType(ptype), text=text)
            session.add(row)
            passages[ptype] = row
        await session.flush()

        for q in spec["questions"]:
            passage = passages.get(q.get("passage_type")) if q.get("passage_type") else None
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
                    part_a_text=q.get("part_a_text"),
                    part_b_text=q.get("part_b_text"),
                    part_b_accepted_answers=q.get("part_b_accepted_answers"),
                    part_b_explanation=q.get("part_b_explanation"),
                    explanation=q.get("explanation"),
                )
            )
        await session.commit()
    logger.info("AUTO-IMPORT: %s kodli test yuklandi (%d savol)", code, len(spec["questions"]))
