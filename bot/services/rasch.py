"""Rasch (1PL IRT) modeli asosida 44 ta test balini hisoblash.

MUHIM ESLATMA (albatta o'qing):
Milliy sertifikat markazining rasmiy Rasch formulasi va aniq kalibrlash
konstantalari ochiq e'lon qilinmagan (bu proprietar/statistik tizim). Quyidagi
kod haqiqiy Rasch (1-parametrli logistik IRT) modelining standart Joint
Maximum Likelihood Estimation (JMLE) algoritmini amalga oshiradi va natijani
0-75 ball shkalasiga o'zingiz sozlashingiz mumkin bo'lgan ikkita konstanta
(CENTER_SCORE, SCALE) yordamida o'giradi. Bu **taxminiy** modeldir — agar
sizda rasmiy tizimning bir nechta o'tgan test natijalari (necha kishi,
qaysi savolga qanday javob berganini bilsangiz) bo'lsa, CENTER_SCORE va
SCALE qiymatlarini shu real natijalarga moslab sozlash mumkin (masalan
regressiya orqali). Hozircha standart logistik shkala anchor qilingan.

Faqat `counts_for_rasch=True` bo'lgan urinishlar (ya'ni har bir o'quvchining
1-urinishi) hisobga olinadi — chunki 2-urinishda javoblar allaqachon ma'lum
bo'lgani uchun statistikani buzadi.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# --- Kalibrlash konstantalari (kerak bo'lsa shu yerda sozlang) -------------- #
CENTER_SCORE = 60.0   # theta=0 (o'rtacha qobiliyat) taxminan qaysi ballga to'g'ri kelishi
SCALE = 10.0          # 1 logit necha ballga teng (kattaroq SCALE -> balllar keskinroq farqlanadi)
MAX_ITERATIONS = 60
CONVERGENCE_EPS = 1e-4


@dataclass
class RaschResult:
    item_difficulties: dict[int, float]   # question_id -> b_i (logit)
    person_abilities: dict[int, float]    # attempt_id -> theta_p (logit)
    person_scores_75: dict[int, float]    # attempt_id -> 0-75 (yoki undan yuqori) ball


def _sigmoid(x: float) -> float:
    if x > 35:
        return 1.0
    if x < -35:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def estimate_rasch(
    responses: dict[int, dict[int, int]],
) -> RaschResult:
    """Rasch (1PL) modelini JMLE bilan baholaydi.

    Args:
        responses: {attempt_id: {question_id: 0 yoki 1}} — faqat
            counts_for_rasch=True urinishlar va faqat javob berilgan savollar
            (belgilanmagan savol umuman kiritilmasin, chunki u "0" emas,
            "javobsiz" degani).

    Returns:
        RaschResult — har bir savol qiyinligi, har bir urinish qobiliyati va
        0-75 shkalasidagi ball.
    """
    attempt_ids = list(responses.keys())
    question_ids = sorted({qid for ans in responses.values() for qid in ans})

    if not attempt_ids or not question_ids:
        return RaschResult({}, {}, {})

    # Boshlang'ich qiymatlar: hammasi 0
    b = {qid: 0.0 for qid in question_ids}
    theta = {aid: 0.0 for aid in attempt_ids}

    # Har bir savolga va urinishga tegishli javoblar ro'yxati (tez kirish uchun)
    item_answers: dict[int, list[tuple[int, int]]] = {qid: [] for qid in question_ids}  # qid -> [(attempt_id, x)]
    person_answers: dict[int, list[tuple[int, int]]] = {aid: [] for aid in attempt_ids}  # aid -> [(qid, x)]
    for aid, ans in responses.items():
        for qid, x in ans.items():
            item_answers[qid].append((aid, x))
            person_answers[aid].append((qid, x))

    # Agar biror savolga hamma to'g'ri yoki hamma xato javob bergan bo'lsa (yoki
    # biror kishi hammaga to'g'ri/xato javob bergan bo'lsa), Rasch baholanmaydi
    # (cheksizlikka intiladi) — bunday holatlarni chetlab o'tamiz (extreme score).
    def has_variance(pairs: list[tuple[int, int]]) -> bool:
        vals = {x for _, x in pairs}
        return len(vals) > 1

    estimable_items = {qid for qid, pairs in item_answers.items() if has_variance(pairs)}
    estimable_persons = {aid for aid, pairs in person_answers.items() if has_variance(pairs)}

    for _ in range(MAX_ITERATIONS):
        max_change = 0.0

        # Item qiyinligini yangilash (b oshsa savol qiyinlashadi)
        for qid in estimable_items:
            pairs = item_answers[qid]
            observed = sum(x for _, x in pairs)
            expected = 0.0
            info = 0.0
            for aid, _ in pairs:
                p = _sigmoid(theta[aid] - b[qid])
                expected += p
                info += p * (1 - p)
            if info > 1e-6:
                delta = (observed - expected) / info
                # Rasch'da item logit person'ga teskari ishorada yangilanadi
                new_b = b[qid] - delta
                max_change = max(max_change, abs(new_b - b[qid]))
                b[qid] = new_b

        # Person qobiliyatini yangilash
        for aid in estimable_persons:
            pairs = person_answers[aid]
            observed = sum(x for _, x in pairs)
            expected = 0.0
            info = 0.0
            for qid, _ in pairs:
                p = _sigmoid(theta[aid] - b[qid])
                expected += p
                info += p * (1 - p)
            if info > 1e-6:
                delta = (observed - expected) / info
                new_theta = theta[aid] + delta
                max_change = max(max_change, abs(new_theta - theta[aid]))
                theta[aid] = new_theta

        # Markazlashtirish: item qiyinliklari o'rtachasi 0 bo'lsin (Rasch'da shkala
        # erkin siljiydi, shuning uchun har iteratsiyada anchor qilib turamiz)
        if estimable_items:
            mean_b = sum(b[qid] for qid in estimable_items) / len(estimable_items)
            for qid in estimable_items:
                b[qid] -= mean_b

        if max_change < CONVERGENCE_EPS:
            break

    # Extreme score (hammaga to'g'ri yoki hammaga xato javob bergan) kishilarga
    # taxminiy chegara qiymat beramiz (ular baholanmaydi, lekin ballsiz ham
    # qolmasin)
    for aid in attempt_ids:
        if aid not in estimable_persons:
            pairs = person_answers[aid]
            total = sum(x for _, x in pairs)
            n = len(pairs)
            if n == 0:
                theta[aid] = 0.0
            elif total == n:  # hammasiga to'g'ri javob
                theta[aid] = 4.0  # yuqori chegara logit (juda yuqori ball)
            else:  # hammasiga xato javob
                theta[aid] = -4.0

    scores_75 = {aid: round(CENTER_SCORE + theta[aid] * SCALE, 2) for aid in attempt_ids}

    return RaschResult(item_difficulties=b, person_abilities=theta, person_scores_75=scores_75)
