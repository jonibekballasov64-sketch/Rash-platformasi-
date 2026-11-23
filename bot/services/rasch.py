"""Rasch (1PL IRT) modeli asosida 44 ta test balini hisoblash.

MUHIM ESLATMA (albatta o'qing):
Milliy sertifikat markazining rasmiy Rasch formulasi va aniq kalibrlash
konstantalari ochiq e'lon qilinmagan (bu proprietar/statistik tizim). Quyidagi
kod haqiqiy Rasch (1-parametrli logistik IRT) modelining standart Joint
Maximum Likelihood Estimation (JMLE) algoritmini amalga oshiradi va natijani
0-75 ball shkalasiga o'zingiz sozlashingiz mumkin bo'lgan ikkita konstanta
(CENTER_SCORE, SCALE) yordamida o'giradi. Bu **taxminiy** modeldir — agar
sizda rasmiy tizimning бир nechta o'tgan test natijalari (necha kishi,
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

# Kichik namunada (masalan bir nechta kishi bitta testni ishlagan holatda)
# JMLE ba'zi savol/kishilar uchun "separation" (hammaga to'g'ri yoki hammaga
# xato) holatiga juda yaqinlashib, iteratsiya davomida theta/b qiymatlarini
# CHEKSIZLIKKA intiltirib yuborishi mumkin — natijada 11111, 10045 kabi
# mantiqsiz ballar chiqadi. Buning oldini olish uchun:
#   1) Har bir Newton-Raphson qadamidagi o'zgarish (delta) MAX_DELTA bilan
#      cheklanadi (bitta iteratsiyada juda katta sakrash bo'lmasin).
#   2) theta/b qiymatlarining o'zi MAX_LOGIT oralig'idan chiqmaydi.
MAX_DELTA = 1.0
MAX_LOGIT = 6.0


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
    #
    # MUHIM (xato tuzatma): bunday savol/kishilar hisobdan TO'LIQ chiqariladi —
    # ya'ni boshqa tomonning hisobiga ham kirmaydi. Avval hamma xato javob bergan
    # savol "o'rtacha qiyinlikdagi (b=0) savol" sifatida har bir o'quvchining
    # qobiliyat hisobida qolib ketardi va butun guruhning balini sun'iy
    # pasaytirardi (masalan, 68 kishilik testda bitta shunday savol hammaning
    # test balini ~10 ballga tushirgan). Standart Rasch dasturlari (Winsteps va
    # h.k.) kabi chiqarib tashlash takrorlanadi: savol chiqarilgach, biror kishi
    # qolgan savollarning hammasiga to'g'ri/xato javob bergan bo'lib qolishi
    # mumkin (va aksincha).
    def has_variance(pairs: list[tuple[int, int]]) -> bool:
        vals = {x for _, x in pairs}
        return len(vals) > 1

    estimable_items = set(question_ids)
    estimable_persons = set(attempt_ids)
    while True:
        new_items = {
            qid for qid in estimable_items
            if has_variance([(aid, x) for aid, x in item_answers[qid] if aid in estimable_persons])
        }
        new_persons = {
            aid for aid in estimable_persons
            if has_variance([(qid, x) for qid, x in person_answers[aid] if qid in new_items])
        }
        if new_items == estimable_items and new_persons == estimable_persons:
            break
        estimable_items, estimable_persons = new_items, new_persons

    for _ in range(MAX_ITERATIONS):
        max_change = 0.0

        # Item qiyinligini yangilash (b oshsa savol qiyinlashadi)
        for qid in estimable_items:
            pairs = [(aid, x) for aid, x in item_answers[qid] if aid in estimable_persons]
            observed = sum(x for _, x in pairs)
            expected = 0.0
            info = 0.0
            for aid, _ in pairs:
                p = _sigmoid(theta[aid] - b[qid])
                expected += p
                info += p * (1 - p)
            if info > 1e-6:
                delta = (observed - expected) / info
                delta = max(-MAX_DELTA, min(MAX_DELTA, delta))
                # Rasch'da item logit person'ga teskari ishorada yangilanadi
                new_b = b[qid] - delta
                new_b = max(-MAX_LOGIT, min(MAX_LOGIT, new_b))
                max_change = max(max_change, abs(new_b - b[qid]))
                b[qid] = new_b

        # Person qobiliyatini yangilash
        for aid in estimable_persons:
            pairs = [(qid, x) for qid, x in person_answers[aid] if qid in estimable_items]
            observed = sum(x for _, x in pairs)
            expected = 0.0
            info = 0.0
            for qid, _ in pairs:
                p = _sigmoid(theta[aid] - b[qid])
                expected += p
                info += p * (1 - p)
            if info > 1e-6:
                delta = (observed - expected) / info
                delta = max(-MAX_DELTA, min(MAX_DELTA, delta))
                new_theta = theta[aid] + delta
                new_theta = max(-MAX_LOGIT, min(MAX_LOGIT, new_theta))
                max_change = max(max_change, abs(new_theta - theta[aid]))
                theta[aid] = new_theta

        # Markazlashtirish: item qiyinliklari o'rtachasi 0 bo'lsin (Rasch'da shkala
        # erkin siljiydi, shuning uchun har iteratsiyada anchor qilib turamiz)
        # MUHIM (xato tuzatma): qobiliyatlar ham xuddi shuncha siljitiladi —
        # aks holda har bir markazlashtirish theta-b farqlarini buzib, hisob
        # juda sekin yaqinlashardi (60 iteratsiyada ballar ~1.5 ballga kam
        # chiqib qolardi).
        if estimable_items:
            mean_b = sum(b[qid] for qid in estimable_items) / len(estimable_items)
            for qid in estimable_items:
                b[qid] -= mean_b
            for aid in estimable_persons:
                theta[aid] -= mean_b

        if max_change < CONVERGENCE_EPS:
            break

    # Extreme score (hammaga to'g'ri yoki hammaga xato javob bergan) kishilarga
    # taxminiy chegara qiymat beramiz (ular baholanmaydi, lekin ballsiz ham
    # qolmasin)
    for aid in attempt_ids:
        if aid not in estimable_persons:
            # Baholanadigan savollar bo'yicha qaraymiz (agar ular umuman bo'lmasa —
            # barcha javoblar bo'yicha)
            pairs = [(qid, x) for qid, x in person_answers[aid] if qid in estimable_items]
            if not pairs:
                pairs = person_answers[aid]
            total = sum(x for _, x in pairs)
            n = len(pairs)
            if n == 0:
                theta[aid] = 0.0
            elif total == n:  # hammasiga to'g'ri javob
                theta[aid] = 4.0  # yuqori chegara logit (juda yuqori ball)
            elif total == 0:  # hammasiga xato javob
                theta[aid] = -4.0
            else:
                # Faqat baholanadigan savol umuman qolmaganda (juda kichik guruh)
                # shu yerga keladi: to'g'ri javoblar ulushidan taxminiy logit
                theta[aid] = max(-4.0, min(4.0, math.log((total + 0.5) / (n - total + 0.5))))

    # Hamma to'g'ri / hamma xato javob bergan savollar: o'rtacha (0) emas, eng
    # oson / eng qiyin deb belgilanadi (hisobotda adashtirmasligi uchun)
    for qid in question_ids:
        if qid not in estimable_items:
            pairs = item_answers[qid]
            if pairs and all(x == 1 for _, x in pairs):
                b[qid] = -MAX_LOGIT
            elif pairs and all(x == 0 for _, x in pairs):
                b[qid] = MAX_LOGIT

    # DIQQAT: 75 — bu shkalaning "markazi atrofidagi" nazariy ko'rsatkichi,
    # QATTIQ YUQORI CHEGARA EMAS — haqiqiy tizimda ham juda yaxshi natija
    # ko'rsatgan talabgor 75 dan yuqori (masalan 83) ball olishi normal, shu
    # sabab bu yerda 75 ga qisqartirilmaydi. Faqat manfiy tomonga (ball 0 dan
    # past bo'lib qolmasligi uchun) va MAX_LOGIT bilan chegaralangan theta
    # tufayli yuqori tomondan ham mantiqsiz (masalan minglab) qiymat
    # chiqmasligi ta'minlanadi.
    scores_75 = {
        aid: round(max(0.0, CENTER_SCORE + theta[aid] * SCALE), 2)
        for aid in attempt_ids
    }

    return RaschResult(item_difficulties=b, person_abilities=theta, person_scores_75=scores_75)
