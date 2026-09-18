"""Umumiy ball va daraja hisob-kitoblari: sertifikat darajasi (A+..C) va
esse 24 ballik natijasini 75 ballik shkalaga o'tkazish jadvali (rasmiy
mezon hujjatidagi jadval asosida).
"""
from __future__ import annotations

# Rasmiy jadval: 24 ballikdan 75 ballikka (0.5 ball qadam bilan)
ESSAY_24_TO_75: dict[float, int] = {
    24: 75, 23.5: 74, 23: 73, 22.5: 72, 22: 71, 21.5: 70, 21: 69, 20.5: 68,
    20: 67, 19.5: 66, 19: 65, 18.5: 64, 18: 63, 17.5: 62, 17: 61, 16.5: 60,
    16: 59, 15.5: 58, 15: 57, 14.5: 56, 14: 55, 13.5: 54, 13: 53, 12.5: 52,
    12: 51, 11.5: 50, 11: 49, 10.5: 48, 10: 47, 9.5: 46, 9: 45, 8.5: 44,
    8: 43, 7.5: 42, 7: 41, 6.5: 40, 6: 39, 5.5: 38, 5: 37, 4.5: 36,
    4: 35, 3.5: 34, 3: 33, 2.5: 32, 2: 31, 1.5: 30, 1: 29, 0.5: 28,
    0: 0,
}

# Avtomatik-rad holatlari uchun mezon hujjatidagi qattiq qoidalar:
#   - mavzuga mos emas / 100 so'zdan kam / ko'chirilgan -> jami 2 ball (24 ballik emas!)
#   - yozilmagan / faqat kirish yozilgan / bo'sh qoldirilgan -> 0 ball
AUTO_REJECT_SCORE_24 = 2.0
AUTO_ZERO_SCORE_24 = 0.0

MIN_ESSAY_WORDS = 100


def convert_essay_24_to_75(score_24: float) -> int:
    """24 ballik xom ballni rasmiy jadval bo'yicha 75 ballikka o'tkazadi.
    Jadvalda yo'q oraliq qiymat kelib qolsa, eng yaqin pastki qadamga
    tushiriladi (xatoga yo'l qo'ymaslik uchun)."""
    score_24 = max(0.0, min(24.0, score_24))
    # 0.5 qadamga yaxlitlash
    rounded = round(score_24 * 2) / 2
    if rounded in ESSAY_24_TO_75:
        return ESSAY_24_TO_75[rounded]
    # ehtiyot chorasi: eng yaqin pastki kalitni topish
    keys = sorted(ESSAY_24_TO_75.keys())
    lower = max((k for k in keys if k <= rounded), default=0)
    return ESSAY_24_TO_75[lower]


def grade_for_score(final_score: float) -> str:
    """Yakuniy (test+esse)/2 ball asosida sertifikat darajasini qaytaradi."""
    if final_score >= 70:
        return "A+"
    if final_score >= 65:
        return "A"
    if final_score >= 60:
        return "B+"
    if final_score >= 55:
        return "B"
    if final_score >= 50:
        return "C+"
    if final_score >= 46:
        return "C"
    return "-"  # sertifikat berilmaydi


def compute_final(test_score_75: float, essay_score_75: float) -> tuple[float, str]:
    final = round((test_score_75 + essay_score_75) / 2, 2)
    return final, grade_for_score(final)
