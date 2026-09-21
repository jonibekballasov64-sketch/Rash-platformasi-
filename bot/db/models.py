"""Ma'lumotlar bazasi modellari.

Testning tuzilishi:
  1-17   : oddiy bir tanlovli savol (A-D), ba'zilarida gap bo'sh joy (___) bor
  18-22  : "ilmiy matn" passage'iga bog'liq bir tanlovli savollar
  23-27  : "badiiy matn" passage'iga bog'liq bir tanlovli savollar
  28-32  : "g'azal" passage'iga bog'liq bir tanlovli savollar
  33-35  : moslashtirish savoli (variantlar A-F, har biriga bitta harf javob)
  36-39  : qisqa yozma javob (bir nechta to'g'ri variant "/" bilan ajratiladi)
  40-44  : ikki qismli (A va B) qisqa yozma javob
  45     : esse (faqat 2-tur test uchun)
"""
from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncAttrs
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(AsyncAttrs, DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# Enumlar
# --------------------------------------------------------------------------- #

class TestType(str, enum.Enum):
    ONLY_44 = "only_44"          # 1-si: faqat 44 ta test, esse balli qo'lda kiritiladi
    WITH_ESSAY = "with_essay"    # 2-si: 44 ta test + botda yoziladigan va AI tekshiradigan esse


class QuestionType(str, enum.Enum):
    SINGLE_CHOICE = "single_choice"   # 1-32 oralig'i (A-D)
    MATCHING = "matching"             # 33-35
    SHORT_ANSWER = "short_answer"     # 36-39
    TWO_PART_SHORT = "two_part_short" # 40-44 (A va B quyi-savollari)


class PassageType(str, enum.Enum):
    ILMIY = "ilmiy"     # 18-22
    BADIIY = "badiiy"   # 23-27
    GAZAL = "gazal"     # 28-32


class TestStatus(str, enum.Enum):
    DRAFT = "draft"          # admin hali savol kiritmoqda
    READY = "ready"          # kod berilgan, o'quvchilar ishlashi mumkin
    CLOSED = "closed"        # admin yopgan (endi yangi urinish qabul qilinmaydi)


class AttemptStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    EXPIRED = "expired"      # vaqt tugab avto-yakunlangan


class Category(str, enum.Enum):
    FILOLOG = "filolog"
    BOSHLANGICH = "boshlangich"
    ABITURIYENT_ASOSIY = "abituriyent_asosiy"
    ABITURIYENT_MAJBURIY = "abituriyent_majburiy"


# --------------------------------------------------------------------------- #
# Asosiy jadvallar
# --------------------------------------------------------------------------- #

class AdminUser(Base):
    """Test tuzuvchi (admin)."""
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), default="")

    tests: Mapped[list["Test"]] = relationship(back_populates="created_by")


class Test(Base):
    __tablename__ = "tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(6), unique=True, index=True)  # 6 xonali kod
    title: Mapped[str] = mapped_column(String(255), default="")
    test_type: Mapped[TestType] = mapped_column(Enum(TestType))
    status: Mapped[TestStatus] = mapped_column(Enum(TestStatus), default=TestStatus.DRAFT)

    duration_minutes: Mapped[int] = mapped_column(Integer, default=120)  # 1-tur=120, 2-tur=180

    essay_topic: Mapped[str | None] = mapped_column(Text, nullable=True)  # faqat WITH_ESSAY uchun

    created_by_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"))
    created_by: Mapped[AdminUser] = relationship(back_populates="tests")

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)

    passages: Mapped[list["Passage"]] = relationship(back_populates="test", cascade="all, delete-orphan")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="test", cascade="all, delete-orphan", order_by="Question.order_no"
    )
    attempts: Mapped[list["Attempt"]] = relationship(back_populates="test", cascade="all, delete-orphan")


class Passage(Base):
    """18-22 (ilmiy), 23-27 (badiiy), 28-32 (g'azal) uchun umumiy matn."""
    __tablename__ = "passages"

    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id"))
    passage_type: Mapped[PassageType] = mapped_column(Enum(PassageType))
    text: Mapped[str] = mapped_column(Text)

    test: Mapped[Test] = relationship(back_populates="passages")
    questions: Mapped[list["Question"]] = relationship(back_populates="passage")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (UniqueConstraint("test_id", "order_no", name="uq_test_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id"))
    order_no: Mapped[int] = mapped_column(Integer)  # 1..44
    question_type: Mapped[QuestionType] = mapped_column(Enum(QuestionType))

    passage_id: Mapped[int | None] = mapped_column(ForeignKey("passages.id"), nullable=True)
    passage: Mapped[Passage | None] = relationship(back_populates="questions")

    text: Mapped[str] = mapped_column(Text)  # savol matni (gap bo'sh joy bilan bo'lishi mumkin)

    # SINGLE_CHOICE uchun: {"A": "...", "B": "...", "C": "...", "D": "..."}
    # MATCHING uchun (faqat 33-savolda saqlanadi, 34/35 shu bilan bog'lanadi): {"A": "...", ..., "F": "..."}
    options: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # SINGLE_CHOICE / MATCHING uchun to'g'ri javob harfi, masalan "B"
    correct_option: Mapped[str | None] = mapped_column(String(2), nullable=True)

    # SHORT_ANSWER uchun qabul qilinadigan variantlar ro'yxati (avto-bosh-harf solishtiriladi)
    accepted_answers: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # TWO_PART_SHORT (40-44) uchun B-qism ma'lumotlari
    part_b_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    part_b_accepted_answers: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    part_b_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    test: Mapped[Test] = relationship(back_populates="questions")


class LearnerUser(Base):
    """Test ishlovchi (talabgor)."""
    __tablename__ = "learner_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    full_name: Mapped[str] = mapped_column(String(255))

    attempts: Mapped[list["Attempt"]] = relationship(back_populates="learner")


class Attempt(Base):
    """Bitta o'quvchining bitta testga bitta urinishi (1- yoki 2-urinish)."""
    __tablename__ = "attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    test_id: Mapped[int] = mapped_column(ForeignKey("tests.id"))
    learner_id: Mapped[int] = mapped_column(ForeignKey("learner_users.id"))
    category: Mapped[Category] = mapped_column(Enum(Category))

    attempt_number: Mapped[int] = mapped_column(Integer, default=1)  # 1 yoki 2
    # Faqat 1-urinish Rasch hisob-kitobiga kiradi (2-urinishda javoblar allaqachon ma'lum bo'ladi)
    counts_for_rasch: Mapped[bool] = mapped_column(Boolean, default=True)

    status: Mapped[AttemptStatus] = mapped_column(Enum(AttemptStatus), default=AttemptStatus.IN_PROGRESS)

    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=dt.datetime.utcnow)
    deadline_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Rash bo'yicha hisoblangan 44-test balli (0-75, ba'zan undan ham yuqori chiqishi mumkin)
    raw_correct_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rasch_score_75: Mapped[float | None] = mapped_column(nullable=True)

    # WITH_ESSAY uchun: AI hisoblagan ball. ONLY_44 uchun: admin/o'quvchi qo'lda kiritgan ball.
    essay_score_75: Mapped[float | None] = mapped_column(nullable=True)

    final_score: Mapped[float | None] = mapped_column(nullable=True)  # (test+esse)/2
    final_grade: Mapped[str | None] = mapped_column(String(4), nullable=True)  # A+, A, B+, B, C+, C, "-"

    # Admin "Natijalarni yangilash va yuborish"ni bosib, shu urinishga natija
    # E'LON QILGANIDA to'ldiriladi. Shundan keyin bu urinishning Rasch/yakuniy
    # bali "qulflanadi" — keyingi safar tugmani bosganda (yangi odamlar
    # qo'shilgan bo'lsa ham) bu urinish QAYTA hisoblanmaydi va qayta xabar
    # yuborilmaydi, faqat published_at hali bo'sh bo'lgan (yangi) urinishlar
    # hisoblanadi va e'lon qilinadi. (services/results.py -> recompute_test_results)
    published_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    test: Mapped[Test] = relationship(back_populates="attempts")
    learner: Mapped[LearnerUser] = relationship(back_populates="attempts")
    answers: Mapped[list["Answer"]] = relationship(back_populates="attempt", cascade="all, delete-orphan")
    essay: Mapped["EssayResponse | None"] = relationship(back_populates="attempt", cascade="all, delete-orphan")


class Answer(Base):
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("attempt_id", "question_id", "sub_part", name="uq_attempt_question_part"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))

    # TWO_PART_SHORT uchun "A" yoki "B"; boshqalarda None
    sub_part: Mapped[str | None] = mapped_column(String(1), nullable=True)

    given_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    attempt: Mapped[Attempt] = relationship(back_populates="answers")
    question: Mapped[Question] = relationship()


class EssayResponse(Base):
    """2-tur uchun: o'quvchi botda yozgan esse va uning (AI) bahosi."""
    __tablename__ = "essay_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("attempts.id"), unique=True)

    text: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer)

    # 12 bandning har biri uchun ball (0/0.5/1/1.5/2), masalan {"1": 2, "2": 1.5, ...}
    criteria_scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_score_24: Mapped[float | None] = mapped_column(nullable=True)
    converted_score_75: Mapped[float | None] = mapped_column(nullable=True)

    # Avtomatik rad etish sabablari: "mavzuga mos emas", "100 so'zdan kam", "ko'chirilgan", "yozilmagan"
    auto_reject_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    ai_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    scored_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attempt: Mapped[Attempt] = relationship(back_populates="essay")
