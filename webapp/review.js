// Test yakunlangach "Javoblar va tahlilni ko'rish" ekrani.
// Backend: webapp_server/app.py -> GET /api/attempt/{attempt_id}/review

const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const params = new URLSearchParams(window.location.search);
const attemptId = params.get("attempt_id");
const area = document.getElementById("question-area");

function escapeHtml(text) {
  return (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;");
}

// --- Test ishlash ekranidagi kabi **qalin**, __qiya__ va |ramkali| so'zlarni
// o'sha holatida (formatlangan holda) ko'rsatish uchun — savol matni,
// javoblar va izohlar xom matn sifatida emas, xuddi testda ko'ringandek chiqsin.
function applyInlineFormatting(escaped) {
  let out = escaped.replace(/\*\*([^*]+)\*\*/g, (_, t) => `<strong>${t}</strong>`);
  out = out.replace(/__([^_]+)__/g, (_, t) => `<em>${t}</em>`);
  return out;
}

function renderFramedText(text) {
  const formatted = applyInlineFormatting(escapeHtml(text));
  return formatted.replace(/\|([^|]+)\|/g, (_, word) => `<span class="framed-word">${word.trim()}</span>`).replace(/\n/g, "<br>");
}

function renderSummary(data) {
  const parts = [];
  if (data.rasch_score_75 !== null && data.rasch_score_75 !== undefined) {
    parts.push(`<div>44 ta test bali: <strong>${data.rasch_score_75}</strong></div>`);
  }
  if (data.essay_score_75 !== null && data.essay_score_75 !== undefined) {
    const essayLabel =
      data.essay_score_24 !== null && data.essay_score_24 !== undefined
        ? `${data.essay_score_24}/24 (${data.essay_score_75}/75)`
        : `${data.essay_score_75}/75`;
    parts.push(`<div>Esse/qo'shimcha bali: <strong>${essayLabel}</strong></div>`);
  }
  if (data.final_score !== null && data.final_score !== undefined) {
    parts.push(`<div>Yakuniy ball: <strong>${data.final_score}</strong> (${data.final_grade || "-"})</div>`);
  } else {
    parts.push(`<div style="color:#666;">Yakuniy ball hali e'lon qilinmagan.</div>`);
  }
  return `<div class="passage-box">${parts.join("")}</div>`;
}

// 4 (yoki 6) ta variantni ko'rsatadi: to'g'ri javob har doim yashil,
// talabgor xato tanlagan bo'lsa o'zi bosgani qizil bo'lib chiqadi.
function renderOptions(item) {
  const entries = Object.entries(item.options || {});
  if (entries.length === 0) return "";
  let html = '<div class="review-options">';
  for (const [letter, text] of entries) {
    let cls = "review-option";
    if (letter === item.correct_option) {
      cls += " correct-answer";
    } else if (letter === item.given_answer && item.given_answer !== item.correct_option) {
      cls += " wrong-selected";
    }
    html += `<div class="${cls}"><strong>${letter})</strong> ${renderFramedText(text)}</div>`;
  }
  html += "</div>";
  return html;
}

// 18-22 (ilmiy), 23-27 (badiiy), 28-32 (g'azal) savollari bir xil matnga
// (passage) tegishli bo'ladi — shu matn har bir savolda emas, balki o'sha
// guruhning FAQAT birinchi savolidan oldin bir marta ko'rsatiladi (aks holda
// bir xil matn 5 marta takrorlanib ketardi). Buni aniqlash uchun ketma-ket
// savollarning passage matnini solishtirib boramiz.
let _lastPassageText = null;

function renderItem(item) {
  const answered = item.given_answer !== null && item.given_answer !== undefined && item.given_answer !== "";
  const label = item.sub_part ? `${item.order_no} (${item.sub_part})` : `${item.order_no}`;
  const hasOptions = (item.type === "single_choice" || item.type === "matching") && item.options;

  let html = "";
  if (item.passage && item.passage.text !== _lastPassageText) {
    html += `<div class="passage-box">${renderFramedText(item.passage.text)}</div>`;
    _lastPassageText = item.passage.text;
  } else if (!item.passage) {
    _lastPassageText = null;
  }

  // Att.Diagnostika botidagi ko'rinishga moslab: karta chetida qizil/yashil
  // chiziq yo'q, sarlavhada ✅/❌ belgisi yo'q — faqat variantlar ichida
  // ranglar (yashil = to'g'ri, qizil = xato belgilangan) va pastda doim
  // "✅ Javob: <to'g'ri harf>" qatori (talabgor to'g'ri/xato javob
  // berganidan qat'i nazar — bu shunchaki to'g'ri javobni ko'rsatadi).
  html += `<div class="review-item">`;
  html += `<div class="question-text">${label}. ${renderFramedText(item.question_text)}</div>`;

  if (hasOptions) {
    html += renderOptions(item);
    if (item.correct_option) {
      html += `<div class="review-answer-line">✅ Javob: <strong>${item.correct_option}</strong></div>`;
    }
    if (!answered) {
      html += `<div class="review-unanswered">Siz bu savolga javob belgilamagansiz.</div>`;
    }
  } else {
    html += `<div>Sizning javobingiz: <strong>${answered ? renderFramedText(item.given_answer) : "-"}</strong></div>`;
    if (item.correct_answer_display) {
      html += `<div class="review-answer-line">✅ Javob: <strong>${renderFramedText(item.correct_answer_display)}</strong></div>`;
    }
  }

  if (item.explanation) {
    html += `<div class="review-explanation">⚠️ Izoh: ${renderFramedText(item.explanation)}</div>`;
  }
  html += `</div>`;
  return html;
}

async function load() {
  if (!attemptId) {
    area.innerHTML = "<p>attempt_id topilmadi.</p>";
    return;
  }
  try {
    const res = await fetch(`/api/attempt/${attemptId}/review`);
    const data = await res.json();
    if (!res.ok) {
      area.innerHTML = `<p>Xatolik: ${data.detail || res.status}</p>`;
      return;
    }
    let html = renderSummary(data);
    _lastPassageText = null;
    for (const item of data.items) {
      html += renderItem(item);
    }
    area.innerHTML = html;
  } catch (e) {
    area.innerHTML = `<p>Xatolik: ${e.message}</p>`;
  }
}

load();
