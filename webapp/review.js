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
    html += `<div class="${cls}"><strong>${letter})</strong> ${escapeHtml(text)}</div>`;
  }
  html += "</div>";
  return html;
}

function renderItem(item) {
  const cls = item.is_correct ? "review-item correct" : "review-item incorrect";
  const icon = item.is_correct ? "✅" : "❌";
  const label = item.sub_part ? `${item.order_no} (${item.sub_part})` : `${item.order_no}`;
  const hasOptions = (item.type === "single_choice" || item.type === "matching") && item.options;

  let html = `<div class="${cls}">`;
  html += `<div class="question-text">${icon} ${label}. ${escapeHtml(item.question_text)}</div>`;

  if (hasOptions) {
    html += renderOptions(item);
    html += `<div style="margin-top:6px;">${icon} Javob: <strong>${escapeHtml(item.given_answer || "-")}</strong></div>`;
  } else {
    html += `<div>Sizning javobingiz: <strong>${escapeHtml(item.given_answer || "-")}</strong></div>`;
    if (!item.is_correct && item.correct_option) {
      html += `<div>To'g'ri javob: <strong>${escapeHtml(item.correct_option)}</strong></div>`;
    }
  }

  if (item.explanation) {
    html += `<div class="review-explanation">⚠️ Izoh: ${escapeHtml(item.explanation)}</div>`;
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
    for (const item of data.items) {
      html += renderItem(item);
    }
    area.innerHTML = html;
  } catch (e) {
    area.innerHTML = `<p>Xatolik: ${e.message}</p>`;
  }
}

load();
