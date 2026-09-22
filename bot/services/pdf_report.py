"""Test natijalari bo'yicha PDF hisobot: 3 bo'lim —
  1) O'quvchilarning batafsil natijalari
  2) Savollar statistikasi (qiyinchilik darajasi bilan)
  3) Testning to'g'ri javoblari

reportlab (Platypus) yordamida quriladi. Dizayn o'zimizga xos rang palitrasi
bilan (har bo'lim o'z rangida), zebra-chiziqli jadvallar va sarlavha banneri.
"""
from __future__ import annotations

import datetime as dt
import io
from dataclasses import dataclass

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from bot.db.models import Attempt, Question, QuestionType, Test

# --------------------------------------------------------------------------- #
# Rang palitrasi — har bo'lim o'z ohangida, lekin bir-biriga mos uyg'un gamma
# --------------------------------------------------------------------------- #
NAVY = colors.HexColor("#1E3A5F")        # 1-bo'lim (natijalar) sarlavhasi
NAVY_SOFT = colors.HexColor("#E7EEF6")   # 1-bo'lim zebra-qator
TEAL = colors.HexColor("#0F766E")        # 2-bo'lim (statistika) sarlavhasi
TEAL_SOFT = colors.HexColor("#E3F3F1")   # 2-bo'lim zebra-qator
AMBER = colors.HexColor("#B45309")       # 3-bo'lim (to'g'ri javoblar) sarlavhasi
AMBER_SOFT = colors.HexColor("#FBEEE0")  # 3-bo'lim zebra-qator
INK = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#5B6B7A")
GRID = colors.HexColor("#C7D2DE")
BANNER_BG = colors.HexColor("#16294A")

DIFF_COLORS = {
    "Juda oson": colors.HexColor("#15803D"),
    "Oson": colors.HexColor("#4D7C0F"),
    "O'rtacha": colors.HexColor("#B45309"),
    "Qiyin": colors.HexColor("#C2410C"),
    "Juda qiyin": colors.HexColor("#B91C1C"),
}
DIFF_HEX = {
    "Juda oson": "#15803D",
    "Oson": "#4D7C0F",
    "O'rtacha": "#B45309",
    "Qiyin": "#C2410C",
    "Juda qiyin": "#B91C1C",
}

CATEGORY_LABELS = {
    "filolog": "Filolog o'qituvchisi",
    "boshlangich": "Boshlang'ich o'qituvchisi",
    "abituriyent_asosiy": "Abituriyent (asosiy blok)",
    "abituriyent_majburiy": "Abituriyent (majburiy blok)",
}


def _difficulty_label(percent: float) -> str:
    if percent >= 90:
        return "Juda oson"
    if percent >= 70:
        return "Oson"
    if percent >= 40:
        return "O'rtacha"
    if percent >= 20:
        return "Qiyin"
    return "Juda qiyin"


def _fmt_num(value: float) -> str:
    """0.0 -> '0', 24.5 -> '24.5', 24.0 -> '24' — ortiqcha .0 ko'rsatmaydi."""
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


def _grade_display(attempt: Attempt) -> str:
    if attempt.final_score is None:
        return "-"
    if attempt.final_grade and attempt.final_grade != "-":
        return attempt.final_grade
    return "Sertifikatsiz"


def _student_points(attempt: Attempt, total_questions: int) -> tuple[float, int]:
    """Talabgorning to'g'ri ballarini (ikki qismli savolda har bir qism 0.5
    ball) va nechta savolga javob belgilaganini hisoblaydi.

    Returns: (to'g'ri_ball, ishlagan_savollar_soni)
    """
    points_by_q: dict[int, float] = {}
    attempted_q: set[int] = set()
    for ans in attempt.answers:
        order_no = ans.question.order_no
        is_two_part = ans.question.question_type == QuestionType.TWO_PART_SHORT
        weight = 0.5 if is_two_part else 1.0
        if ans.given_answer:
            attempted_q.add(order_no)
        if ans.is_correct:
            points_by_q[order_no] = points_by_q.get(order_no, 0.0) + weight
    return sum(points_by_q.values()), len(attempted_q)


def _compute_question_stats(
    attempts: list[Attempt], questions: list[Question]
) -> list[tuple[Question, float, int, float, str]]:
    """Har bir savol bo'yicha: (savol, to'g'ri_ball, jami_talabgor, foiz, daraja)."""
    total_students = len(attempts)
    weights = {
        q.order_no: (0.5 if q.question_type == QuestionType.TWO_PART_SHORT else 1.0)
        for q in questions
    }
    correct_by_q: dict[int, float] = {q.order_no: 0.0 for q in questions}
    for a in attempts:
        for ans in a.answers:
            if ans.is_correct:
                order_no = ans.question.order_no
                correct_by_q[order_no] = correct_by_q.get(order_no, 0.0) + weights.get(order_no, 1.0)

    rows = []
    for q in sorted(questions, key=lambda x: x.order_no):
        correct = correct_by_q.get(q.order_no, 0.0)
        percent = (correct / total_students * 100) if total_students else 0.0
        rows.append((q, correct, total_students, percent, _difficulty_label(percent)))
    return rows


def _correct_answer_rows(questions: list[Question]) -> list[tuple[str, str]]:
    """Har bir savol (yoki ikki qismli savolning har bir qismi) uchun
    (savol_raqami_str, to'g'ri_javob_matni) juftliklarini qaytaradi."""
    rows: list[tuple[str, str]] = []
    for q in sorted(questions, key=lambda x: x.order_no):
        if q.question_type == QuestionType.TWO_PART_SHORT:
            part_a = " | ".join(q.accepted_answers or []) or "-"
            part_b = " | ".join(q.part_b_accepted_answers or []) or "-"
            rows.append((f"{q.order_no}.1", part_a))
            rows.append((f"{q.order_no}.2", part_b))
        elif q.question_type == QuestionType.SHORT_ANSWER:
            answer = " | ".join(q.accepted_answers or []) or "-"
            rows.append((str(q.order_no), answer))
        else:
            rows.append((str(q.order_no), q.correct_option or "-"))
    return rows


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title", parent=base["Title"], textColor=colors.white, fontSize=18,
            leading=22, alignment=TA_LEFT, spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=base["Normal"], textColor=colors.HexColor("#C9D6E8"),
            fontSize=10.5, leading=14, alignment=TA_LEFT,
        ),
        "section": ParagraphStyle(
            "Section", parent=base["Heading2"], textColor=colors.white, fontSize=13,
            leading=16, spaceBefore=0, spaceAfter=0, alignment=TA_LEFT,
        ),
        "cell": ParagraphStyle(
            "Cell", parent=base["Normal"], fontSize=8.3, leading=10.2, textColor=INK,
        ),
        "cell_center": ParagraphStyle(
            "CellCenter", parent=base["Normal"], fontSize=8.3, leading=10.2,
            textColor=INK, alignment=TA_CENTER,
        ),
        "head": ParagraphStyle(
            "Head", parent=base["Normal"], fontSize=8.6, leading=10.5,
            textColor=colors.white, alignment=TA_CENTER, fontName="Helvetica-Bold",
        ),
        "note": ParagraphStyle(
            "Note", parent=base["Normal"], fontSize=8.5, leading=11.5, textColor=MUTED,
        ),
    }


def _section_header(text: str, color: colors.Color, styles: dict) -> Table:
    t = Table([[Paragraph(text, styles["section"])]], colWidths=[None])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), color),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return t


def _zebra_table(
    header: list[str], rows: list[list], col_widths: list[float],
    header_color: colors.Color, zebra_color: colors.Color, styles: dict,
    align_cols: set[int] | None = None,
) -> Table:
    align_cols = align_cols or set()
    header_row = [Paragraph(h, styles["head"]) for h in header]
    data = [header_row] + rows

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), header_color),
        ("GRID", (0, 0), (-1, -1), 0.5, GRID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), zebra_color))
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(style_cmds))
    return table


def generate_results_pdf(
    test: Test,
    attempts: list[Attempt],
    questions: list[Question],
    admin_name: str | None = None,
) -> bytes:
    styles = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"{test.code} — natijalar",
    )

    story = []

    # ---- Banner sarlavha ---------------------------------------------- #
    now_str = dt.datetime.now().strftime("%d.%m.%Y %H:%M")
    subtitle_bits = [f"Fan: Ona tili va adabiyot", f"Test kodi: {test.code}"]
    if admin_name:
        subtitle_bits.append(f"Tuzuvchi: {admin_name}")
    subtitle_bits.append(f"Shakllantirildi: {now_str}")
    banner = Table(
        [
            [Paragraph(f"Milliy Sertifikat — Test natijalari", styles["title"])],
            [Paragraph(" &nbsp;•&nbsp; ".join(subtitle_bits), styles["subtitle"])],
        ],
        colWidths=[None],
    )
    banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BANNER_BG),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (0, 0), 10),
                ("BOTTOMPADDING", (0, 0), (0, 0), 2),
                ("TOPPADDING", (0, 1), (0, 1), 0),
                ("BOTTOMPADDING", (0, 1), (0, 1), 10),
            ]
        )
    )
    story.append(banner)
    story.append(Spacer(1, 10))

    total_questions = len(questions) or 44

    # ---- 1-bo'lim: batafsil natijalar ---------------------------------- #
    story.append(_section_header("1. O'quvchilarning batafsil natijalari", NAVY, styles))
    story.append(Spacer(1, 4))

    def sort_key(a: Attempt):
        primary = a.final_score if a.final_score is not None else -1
        secondary = a.raw_correct_count if a.raw_correct_count is not None else -1
        return (primary, secondary)

    sorted_attempts = sorted(attempts, key=sort_key, reverse=True)

    def _wrong_label(ans) -> str:
        if ans.sub_part == "A":
            return f"{ans.question.order_no}.1"
        if ans.sub_part == "B":
            return f"{ans.question.order_no}.2"
        return str(ans.question.order_no)

    def _wrong_sort_key(label: str) -> tuple[int, float]:
        base, _, frac = label.partition(".")
        return (int(base), float(f"0.{frac}") if frac else 0.0)

    rows1 = []
    for i, a in enumerate(sorted_attempts, start=1):
        points, attempted = _student_points(a, total_questions)
        wrong_numbers = sorted(
            (_wrong_label(ans) for ans in a.answers if ans.is_correct is False),
            key=_wrong_sort_key,
        )
        rows1.append(
            [
                Paragraph(str(i), styles["cell_center"]),
                Paragraph(_clean(a.learner.full_name), styles["cell"]),
                Paragraph(CATEGORY_LABELS.get(a.category.value, a.category.value), styles["cell"]),
                Paragraph(str(a.attempt_number), styles["cell_center"]),
                Paragraph(f"{attempted}/{total_questions}", styles["cell_center"]),
                Paragraph(f"{_fmt_num(points)}/{total_questions}", styles["cell_center"]),
                Paragraph(_fmt_num(a.rasch_score_75) if a.rasch_score_75 is not None else "-", styles["cell_center"]),
                Paragraph(_fmt_num(a.essay_score_75) if a.essay_score_75 is not None else "-", styles["cell_center"]),
                Paragraph(_fmt_num(a.final_score) if a.final_score is not None else "-", styles["cell_center"]),
                Paragraph(_grade_display(a), styles["cell_center"]),
                Paragraph(", ".join(wrong_numbers) if wrong_numbers else "-", styles["cell"]),
            ]
        )

    header1 = [
        "№", "Ism-familiya", "Toifa", "Urinish", "Ishlagan",
        "To'g'ri", "44-test (Rash)", "Esse/qo'sh.", "Umumiy", "Daraja", "Xato belgilagan savollar",
    ]
    col_widths1 = [
        9 * mm, 42 * mm, 32 * mm, 14 * mm, 15 * mm,
        15 * mm, 20 * mm, 20 * mm, 16 * mm, 18 * mm, None,
    ]
    if not rows1:
        story.append(Paragraph("Hali hech kim bu testni yakunlamagan.", styles["note"]))
    else:
        story.append(_zebra_table(header1, rows1, col_widths1, NAVY, NAVY_SOFT, styles))

    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            f"Jami: {len(sorted_attempts)} ta urinish. \"Ishlagan\" — {total_questions} tadan "
            "nechta savolga javob belgilagani; \"To'g'ri\" — to'g'ri javoblar balli "
            "(ikki qismli savollarda har bir qism 0.5 balldan hisoblanadi).",
            styles["note"],
        )
    )

    story.append(PageBreak())

    # ---- 2-bo'lim: savollar statistikasi -------------------------------- #
    story.append(_section_header(f"2. Savollar statistikasi (1–{total_questions})", TEAL, styles))
    story.append(Spacer(1, 4))

    stats = _compute_question_stats(attempts, questions)
    rows2 = []
    for q, correct, total_students, percent, label in stats:
        rows2.append(
            [
                Paragraph(str(q.order_no), styles["cell_center"]),
                Paragraph(f"{_fmt_num(correct)}/{total_students}", styles["cell_center"]),
                Paragraph(f"{percent:.1f}%", styles["cell_center"]),
                Paragraph(
                    f'<font color="{DIFF_HEX.get(label, "#1F2933")}"><b>{label}</b></font>',
                    styles["cell_center"],
                ),
            ]
        )
    header2 = ["Savol", "To'g'ri", "Foiz", "Qiyinchilik"]
    col_widths2 = [30 * mm, 30 * mm, 30 * mm, 40 * mm]
    if not rows2:
        story.append(Paragraph("Statistika uchun ma'lumot yo'q.", styles["note"]))
    else:
        story.append(_zebra_table(header2, rows2, col_widths2, TEAL, TEAL_SOFT, styles))

    story.append(PageBreak())

    # ---- 3-bo'lim: to'g'ri javoblar -------------------------------------- #
    story.append(_section_header("3. Testning to'g'ri javoblari", AMBER, styles))
    story.append(Spacer(1, 4))

    answer_rows = _correct_answer_rows(questions)
    rows3 = [
        [Paragraph(num, styles["cell_center"]), Paragraph(ans, styles["cell"])]
        for num, ans in answer_rows
    ]
    header3 = ["Savol", "To'g'ri javob"]
    col_widths3 = [30 * mm, None]
    if not rows3:
        story.append(Paragraph("Savollar topilmadi.", styles["note"]))
    else:
        story.append(_zebra_table(header3, rows3, col_widths3, AMBER, AMBER_SOFT, styles))

    doc.build(story)
    return buf.getvalue()


def _clean(name: str | None) -> str:
    import unicodedata

    if not name:
        return "Noma'lum"
    return unicodedata.normalize("NFKC", name)
