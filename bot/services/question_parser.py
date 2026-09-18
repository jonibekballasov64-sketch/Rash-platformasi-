"""Admin savol matnlarini siz ko'rsatgan formatdan parse qilish.

KIRITISH FORMATI (har biri botga ALOHIDA xabar sifatida yuboriladi):

1-17 va 18-32 (bir tanlovli, A-D):
    ⁉️1. Savol matni (___ bo'sh joy bo'lishi mumkin)
    🔷A) variant
    🔷B) variant
    🔷C) variant
    🔷D) variant
    ✅Javob: B
    ⚠️Izoh: izoh matni

Matn (ilmiy/badiiy/g'azal), 18, 23, 28-savoldan OLDIN alohida xabar bilan:
    ‼️
    matn birinchi qatori
    matn ikkinchi qatori
    ...
    ‼️

33-35 (moslashtirish), BITTA xabarda:
    ⁉️33. birinchi gap
    ⁉️34. ikkinchi gap
    ⁉️35. uchinchi gap
    🔷A) variant
    🔷B) variant
    🔷C) variant
    🔷D) variant
    🔷E) variant
    🔷F) variant
    ✅33A
    ✅34B
    ✅35E
    ⚠️Izoh: izoh matni

36-39 (qisqa yozma javob):
    ⁉️36. Savol matni (| so'z | ramka ichida so'z | kabi qismlar bo'lishi mumkin)
    ✅Javob: variant1 / variant2 / variant3
    ⚠️Izoh: izoh matni

40-44 (ikki qismli A/B):
    ⁉️40. Savol matni
    A) A-qism savoli
    ✅Javob: variant1 / variant2
    ⚠️Izoh: izoh matni
    B) B-qism savoli
    ✅Javob: variant1 / variant2
    ⚠️Izoh: izoh matni

Eslatma: emoji belgilar (⁉️🔷✅⚠️‼️) aniq shu ko'rinishda bo'lishi shart emas —
pastdagi regexlar ularning variantlarini (masalan faqat "✅" yoki "✅️") ham
qabul qiladi, lekin qator boshida turishi kerak.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


class ParseError(ValueError):
    pass


# --- umumiy yordamchi regexlar ---------------------------------------------- #
_QUESTION_HEAD = re.compile(r"^\s*⁉️?\s*(\d+)\s*[.)]\s*(.*)$")
_OPTION_LINE = re.compile(r"^\s*🔷?️?\s*([A-F])\s*[).]\s*(.*)$")
_ANSWER_LINE = re.compile(r"^\s*✅️?\s*(?:Javob\s*[:.]?\s*)?(.*)$", re.IGNORECASE)
_EXPLANATION_LINE = re.compile(r"^\s*⚠️?\s*(?:Izoh\s*[:.]?\s*)?(.*)$", re.IGNORECASE)
_MATCHING_ANSWER_LINE = re.compile(r"^\s*✅️?\s*(\d+)\s*([A-F])\s*$")
_SUBPART_LINE = re.compile(r"^\s*([AB])\s*[).]\s*(.*)$")


@dataclass
class ParsedSingleChoice:
    order_no: int
    text: str
    options: dict[str, str]
    correct_option: str
    explanation: str | None


@dataclass
class ParsedMatching:
    order_nos: tuple[int, int, int]
    texts: dict[int, str]
    options: dict[str, str]  # A-F
    correct: dict[int, str]  # order_no -> harf
    explanation: str | None


@dataclass
class ParsedShortAnswer:
    order_no: int
    text: str
    accepted_answers: list[str]
    explanation: str | None


@dataclass
class ParsedTwoPartShort:
    order_no: int
    text: str
    part_a_text: str
    part_a_answers: list[str]
    part_a_explanation: str | None
    part_b_text: str
    part_b_answers: list[str]
    part_b_explanation: str | None


def _split_lines(raw: str) -> list[str]:
    return [ln for ln in raw.replace("\r\n", "\n").split("\n")]


def parse_passage(raw: str) -> str:
    """‼️ ... ‼️ orasidagi matnni ajratib oladi. Agar belgilar topilmasa,
    butun matnni passage sifatida qaytaradi (moslashuvchanlik uchun)."""
    stripped = raw.strip()
    if stripped.startswith("‼️") and stripped.endswith("‼️") and len(stripped) > 4:
        return stripped[2:-2].strip()
    # ba'zan bitta ‼️ boshida, bittasi alohida qatorda bo'lishi mumkin
    lines = [ln for ln in _split_lines(raw) if ln.strip() != "‼️"]
    return "\n".join(lines).strip()


def parse_single_choice(raw: str) -> ParsedSingleChoice:
    lines = [ln for ln in _split_lines(raw) if ln.strip() != ""]
    if not lines:
        raise ParseError("Bo'sh xabar")

    head = _QUESTION_HEAD.match(lines[0])
    if not head:
        raise ParseError("Birinchi qator '⁉️N. savol matni' ko'rinishida bo'lishi kerak")
    order_no = int(head.group(1))
    text_parts = [head.group(2)] if head.group(2) else []

    options: dict[str, str] = {}
    answer_letter: str | None = None
    explanation: str | None = None

    i = 1
    # savol matni bir necha qatorga cho'zilishi mumkin (variant qatorlariga yetguncha)
    while i < len(lines) and not _OPTION_LINE.match(lines[i]):
        text_parts.append(lines[i])
        i += 1

    while i < len(lines):
        line = lines[i]
        opt_match = _OPTION_LINE.match(line)
        if opt_match:
            options[opt_match.group(1).upper()] = opt_match.group(2).strip()
            i += 1
            continue
        if line.strip().upper().startswith(("✅", "JAVOB")):
            m = _ANSWER_LINE.match(line)
            val = (m.group(1) if m else line).strip()
            # "B" yoki "Javob B" kabi holatlarni ham qo'llab-quvvatlash
            letter_match = re.search(r"\b([A-D])\b", val.upper())
            answer_letter = letter_match.group(1) if letter_match else val.upper()[:1]
            i += 1
            continue
        if line.strip().upper().startswith(("⚠", "IZOH")):
            m = _EXPLANATION_LINE.match(line)
            explanation = (m.group(1) if m else line).strip() or None
            i += 1
            # qolgan qatorlar ham izohga tegishli bo'lishi mumkin
            rest = lines[i:]
            if rest:
                explanation = ((explanation or "") + "\n" + "\n".join(rest)).strip()
            break
        i += 1

    if not options:
        raise ParseError(f"{order_no}-savolda variantlar (🔷A) ...) topilmadi")
    if not answer_letter or answer_letter not in options:
        raise ParseError(f"{order_no}-savolda to'g'ri javob (✅Javob: X) topilmadi yoki noto'g'ri")

    return ParsedSingleChoice(
        order_no=order_no,
        text="\n".join(t for t in text_parts if t.strip()).strip(),
        options=options,
        correct_option=answer_letter,
        explanation=explanation,
    )


def parse_matching(raw: str) -> ParsedMatching:
    lines = [ln for ln in _split_lines(raw) if ln.strip() != ""]
    texts: dict[int, str] = {}
    options: dict[str, str] = {}
    correct: dict[int, str] = {}
    explanation_parts: list[str] = []
    in_explanation = False

    for line in lines:
        if in_explanation:
            explanation_parts.append(line)
            continue
        head = _QUESTION_HEAD.match(line)
        if head:
            texts[int(head.group(1))] = head.group(2).strip()
            continue
        opt = _OPTION_LINE.match(line)
        if opt:
            options[opt.group(1).upper()] = opt.group(2).strip()
            continue
        m = _MATCHING_ANSWER_LINE.match(line)
        if m:
            correct[int(m.group(1))] = m.group(2).upper()
            continue
        if line.strip().upper().startswith(("⚠", "IZOH")):
            m2 = _EXPLANATION_LINE.match(line)
            if m2 and m2.group(1).strip():
                explanation_parts.append(m2.group(1).strip())
            in_explanation = True
            continue

    if len(texts) != 3 or len(correct) != 3:
        raise ParseError(
            "Moslashtirish savolida (33-35) aniq 3 ta savol matni va 3 ta javob "
            "(✅33A kabi) bo'lishi kerak"
        )
    order_nos = tuple(sorted(texts.keys()))  # type: ignore[assignment]
    if order_nos != (33, 34, 35):
        raise ParseError("Moslashtirish savollari aynan 33, 34, 35 raqamlari bilan bo'lishi kerak")
    if not options:
        raise ParseError("Moslashtirish savolida variantlar (A-F) topilmadi")
    for qn, letter in correct.items():
        if letter not in options:
            raise ParseError(f"{qn}-savol uchun javob harfi ({letter}) variantlar orasida yo'q")

    return ParsedMatching(
        order_nos=order_nos,  # type: ignore[arg-type]
        texts=texts,
        options=options,
        correct=correct,
        explanation="\n".join(explanation_parts).strip() or None,
    )


def parse_short_answer(raw: str) -> ParsedShortAnswer:
    lines = [ln for ln in _split_lines(raw) if ln.strip() != ""]
    if not lines:
        raise ParseError("Bo'sh xabar")
    head = _QUESTION_HEAD.match(lines[0])
    if not head:
        raise ParseError("Birinchi qator '⁉️N. savol matni' ko'rinishida bo'lishi kerak")
    order_no = int(head.group(1))
    text_parts = [head.group(2)] if head.group(2) else []

    answers: list[str] = []
    explanation_parts: list[str] = []
    mode = "text"

    for line in lines[1:]:
        if line.strip().upper().startswith(("✅", "JAVOB")):
            m = _ANSWER_LINE.match(line)
            val = (m.group(1) if m else line).strip()
            answers = [a.strip() for a in val.split("/") if a.strip()]
            mode = "answer_done"
            continue
        if line.strip().upper().startswith(("⚠", "IZOH")):
            m = _EXPLANATION_LINE.match(line)
            if m and m.group(1).strip():
                explanation_parts.append(m.group(1).strip())
            mode = "explanation"
            continue
        if mode == "text":
            text_parts.append(line)
        elif mode == "explanation":
            explanation_parts.append(line)
        # mode == "answer_done" bo'lsa va yana matn kelsa e'tiborsiz qoldiriladi

    if not answers:
        raise ParseError(f"{order_no}-savolda javob (✅Javob: variant1 / variant2) topilmadi")

    return ParsedShortAnswer(
        order_no=order_no,
        text="\n".join(t for t in text_parts if t.strip()).strip(),
        accepted_answers=answers,
        explanation="\n".join(explanation_parts).strip() or None,
    )


def parse_two_part_short(raw: str) -> ParsedTwoPartShort:
    lines = [ln for ln in _split_lines(raw) if ln.strip() != ""]
    if not lines:
        raise ParseError("Bo'sh xabar")
    head = _QUESTION_HEAD.match(lines[0])
    if not head:
        raise ParseError("Birinchi qator '⁉️N. savol matni' ko'rinishida bo'lishi kerak")
    order_no = int(head.group(1))
    main_text_parts = [head.group(2)] if head.group(2) else []

    i = 1
    while i < len(lines) and not _SUBPART_LINE.match(lines[i]):
        main_text_parts.append(lines[i])
        i += 1

    parts: dict[str, dict] = {"A": {"text": "", "answers": [], "explanation": []}, "B": {"text": "", "answers": [], "explanation": []}}
    current: str | None = None
    mode = "text"

    while i < len(lines):
        line = lines[i]
        sub = _SUBPART_LINE.match(line)
        if sub:
            current = sub.group(1).upper()
            parts[current]["text"] = sub.group(2).strip()
            mode = "text"
            i += 1
            continue
        if current is None:
            i += 1
            continue
        if line.strip().upper().startswith(("✅", "JAVOB")):
            m = _ANSWER_LINE.match(line)
            val = (m.group(1) if m else line).strip()
            parts[current]["answers"] = [a.strip() for a in val.split("/") if a.strip()]
            mode = "answer_done"
        elif line.strip().upper().startswith(("⚠", "IZOH")):
            m = _EXPLANATION_LINE.match(line)
            if m and m.group(1).strip():
                parts[current]["explanation"].append(m.group(1).strip())
            mode = "explanation"
        elif mode == "text":
            parts[current]["text"] += "\n" + line
        elif mode == "explanation":
            parts[current]["explanation"].append(line)
        i += 1

    for label in ("A", "B"):
        if not parts[label]["text"] or not parts[label]["answers"]:
            raise ParseError(f"{order_no}-savolning {label}-qismida matn yoki javob yetishmayapti")

    return ParsedTwoPartShort(
        order_no=order_no,
        text="\n".join(t for t in main_text_parts if t.strip()).strip(),
        part_a_text=parts["A"]["text"].strip(),
        part_a_answers=parts["A"]["answers"],
        part_a_explanation="\n".join(parts["A"]["explanation"]).strip() or None,
        part_b_text=parts["B"]["text"].strip(),
        part_b_answers=parts["B"]["answers"],
        part_b_explanation="\n".join(parts["B"]["explanation"]).strip() or None,
      )
