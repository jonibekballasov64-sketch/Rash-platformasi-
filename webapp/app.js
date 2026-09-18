// Milliy sertifikat test WebApp — asosiy mantiq.
// Backend: webapp_server/app.py

const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const params = new URLSearchParams(window.location.search);
const attemptId = params.get("attempt_id");

const state = {
  data: null,
  questions: [],
  currentIndex: 0,
  answers: {}, // key: `${question_id}:${sub_part||''}` -> given_answer
  essayText: "",
  deadline: null,
  timerInterval: null,
};

const els = {
  timer: document.getElementById("timer"),
  finishBtn: document.getElementById("finish-btn"),
  area: document.getElementById("question-area"),
  prevBtn: document.getElementById("prev-btn"),
  nextBtn: document.getElementById("next-btn"),
  progress: document.getElementById("progress"),
  modal: document.getElementById("confirm-modal"),
  confirmText: document.getElementById("confirm-text"),
  confirmOk: document.getElementById("confirm-ok"),
  confirmCancel: document.getElementById("confirm-cancel"),
};

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Xatolik: ${res.status}`);
  }
  return res.json();
}

// --- | so'z | ramkali qismlarni <span class="framed-word"> ga aylantiradi,
// va oddiy | ...| bo'lmagan matnni o'zgartirmaydi.
function renderFramedText(text) {
  const escaped = text.replace(/&/g, "&amp;").replace(/</g, "&lt;");
  return escaped.replace(/\|([^|]+)\|/g, (_, word) => `<span class="framed-word">${word.trim()}</span>`);
}

function answerKey(qid, subPart) {
  return `${qid}:${subPart || ""}`;
}

async function load() {
  if (!attemptId) {
    els.area.innerHTML = "<p>attempt_id topilmadi.</p>";
    return;
  }
  try {
    state.data = await api(`/api/attempt/${attemptId}`);
  } catch (e) {
    els.area.innerHTML = `<p>Xatolik: ${e.message}</p>`;
    return;
  }
  state.questions = state.data.questions;
  state.deadline = new Date(state.data.deadline_at);
  startTimer();
  render();
}

function startTimer() {
  const tick = () => {
    const remainMs = state.deadline - new Date();
    if (remainMs <= 0) {
      els.timer.textContent = "00:00:00";
      clearInterval(state.timerInterval);
      finishTest(true);
      return;
    }
    const totalSec = Math.floor(remainMs / 1000);
    const h = String(Math.floor(totalSec / 3600)).padStart(2, "0");
    const m = String(Math.floor((totalSec % 3600) / 60)).padStart(2, "0");
    const s = String(totalSec % 60).padStart(2, "0");
    els.timer.textContent = `${h}:${m}:${s}`;
  };
  tick();
  state.timerInterval = setInterval(tick, 1000);
}

function totalScreens() {
  // 44 savol + (agar with_essay bo'lsa) 1 ta esse ekrani
  return state.questions.length + (state.data.test_type === "with_essay" ? 1 : 0);
}

function isEssayScreen(index) {
  return state.data.test_type === "with_essay" && index === state.questions.length;
}

function render() {
  const idx = state.currentIndex;
  els.progress.textContent = `${idx + 1} / ${totalScreens()}`;
  els.prevBtn.disabled = idx === 0;
  els.nextBtn.textContent = idx === totalScreens() - 1 ? "Yakunlash" : "Keyingi →";

  if (isEssayScreen(idx)) {
    renderEssayScreen();
    return;
  }

  const q = state.questions[idx];
  let html = "";
  if (q.passage) {
    html += `<div class="passage-box">${q.passage.text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/\n/g, "<br>")}</div>`;
  }
  html += `<div class="question-text">${q.order_no}. ${renderFramedText(q.text)}</div>`;

  if (q.type === "single_choice") {
    html += renderSingleChoice(q);
  } else if (q.type === "matching") {
    html += renderMatching(q);
  } else if (q.type === "short_answer") {
    html += renderShortAnswer(q, null);
  } else if (q.type === "two_part_short") {
    html += `<p><strong>A)</strong></p>` + renderShortAnswer(q, "A");
    html += `<p style="margin-top:16px"><strong>B) ${renderFramedText(q.part_b_text || "")}</strong></p>` + renderShortAnswer(q, "B");
  }

  els.area.innerHTML = html;
  attachHandlers(q);
}

function renderSingleChoice(q) {
  const selected = state.answers[answerKey(q.id, null)];
  let html = '<div class="options">';
  for (const [letter, text] of Object.entries(q.options || {})) {
    const cls = selected === letter ? "option-btn selected" : "option-btn";
    html += `<button class="${cls}" data-letter="${letter}">${letter}) ${text}</button>`;
  }
  html += "</div>";
  return html;
}

function renderMatching(q) {
  // 33-35 uchun: bu funksiya faqat bitta savolni ko'rsatadi (navigatsiya
  // orqali), variantlar (A-F) select ko'rinishida.
  const selected = state.answers[answerKey(q.id, null)] || "";
  let html = `<div class="matching-gap" style="display:block;margin-bottom:10px;">${renderFramedText(q.text)}</div>`;
  html += `<select class="matching-select" id="matching-select">`;
  html += `<option value="">-- tanlang --</option>`;
  for (const [letter, text] of Object.entries(q.options || {})) {
    const sel = selected === letter ? "selected" : "";
    html += `<option value="${letter}" ${sel}>${letter}) ${text}</option>`;
  }
  html += "</select>";
  return html;
}

function renderShortAnswer(q, subPart) {
  const key = answerKey(q.id, subPart);
  const value = state.answers[key] || "";
  return `<input class="short-answer-input" data-qid="${q.id}" data-sub="${subPart || ""}" value="${value.replace(/"/g, "&quot;")}" placeholder="Javobingizni yozing" autocapitalize="sentences" />`;
}

function renderEssayScreen() {
  els.area.innerHTML = `
    <div class="question-text">45. Esse: ${state.data.essay_topic || ""}</div>
    <textarea class="essay-textarea" id="essay-input" placeholder="Essengizni shu yerga yozing...">${state.essayText}</textarea>
    <div class="word-count" id="word-count"></div>
  `;
  const textarea = document.getElementById("essay-input");
  const wordCountEl = document.getElementById("word-count");
  const updateCount = () => {
    const words = textarea.value.split(/\s+/).filter(Boolean).length;
    wordCountEl.textContent = `${words} so'z (kamida ${state.data.essay_min_words} so'z kerak)`;
  };
  updateCount();
  let saveTimeout;
  textarea.addEventListener("input", () => {
    state.essayText = textarea.value;
    updateCount();
    clearTimeout(saveTimeout);
    saveTimeout = setTimeout(() => {
      api(`/api/attempt/${attemptId}/essay`, {
        method: "POST",
        body: JSON.stringify({ text: state.essayText }),
      }).catch(() => {});
    }, 800);
  });
}

function attachHandlers(q) {
  if (q.type === "single_choice") {
    els.area.querySelectorAll(".option-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const letter = btn.dataset.letter;
        state.answers[answerKey(q.id, null)] = letter;
        saveAnswer(q.id, null, letter);
        render();
      });
    });
  } else if (q.type === "matching") {
    const select = document.getElementById("matching-select");
    select.addEventListener("change", () => {
      state.answers[answerKey(q.id, null)] = select.value;
      saveAnswer(q.id, null, select.value);
    });
  } else {
    els.area.querySelectorAll(".short-answer-input").forEach((input) => {
      input.addEventListener("blur", () => {
        const sub = input.dataset.sub || null;
        state.answers[answerKey(q.id, sub)] = input.value;
        saveAnswer(q.id, sub, input.value);
      });
    });
  }
}

async function saveAnswer(questionId, subPart, value) {
  if (!value) return;
  try {
    await api(`/api/attempt/${attemptId}/answer`, {
      method: "POST",
      body: JSON.stringify({ question_id: questionId, sub_part: subPart, given_answer: value }),
    });
  } catch (e) {
    console.error(e);
  }
}

function countUnanswered() {
  let count = 0;
  for (const q of state.questions) {
    if (q.type === "two_part_short") {
      if (!state.answers[answerKey(q.id, "A")]) count++;
      if (!state.answers[answerKey(q.id, "B")]) count++;
    } else {
      if (!state.answers[answerKey(q.id, null)]) count++;
    }
  }
  return count;
}

function showConfirm(text) {
  return new Promise((resolve) => {
    els.confirmText.textContent = text;
    els.modal.classList.remove("hidden");
    const cleanup = () => els.modal.classList.add("hidden");
    els.confirmOk.onclick = () => { cleanup(); resolve(true); };
    els.confirmCancel.onclick = () => { cleanup(); resolve(false); };
  });
}

els.prevBtn.addEventListener("click", () => {
  if (state.currentIndex > 0) {
    state.currentIndex -= 1;
    render();
  }
});

els.nextBtn.addEventListener("click", async () => {
  if (state.currentIndex < totalScreens() - 1) {
    state.currentIndex += 1;
    render();
  } else {
    await requestFinish();
  }
});

els.finishBtn.addEventListener("click", requestFinish);

async function requestFinish() {
  const unanswered = countUnanswered();
  const msg = unanswered > 0
    ? `${unanswered} ta savolga belgilamagansiz. Haqiqatdan yakunlaysizmi?`
    : "Haqiqatdan yakunlaysizmi?";
  const ok = await showConfirm(msg);
  if (ok) finishTest(false);
}

async function finishTest(auto) {
  clearInterval(state.timerInterval);
  try {
    const result = await api(`/api/attempt/${attemptId}/finish`, { method: "POST" });
    els.area.innerHTML = `
      <div class="question-text">✅ Test yakunlandi${auto ? " (vaqt tugadi)" : ""}.</div>
      <p>44 tadan: <strong>${result.raw_correct_count ?? "-"}/44</strong></p>
      ${state.data.test_type === "with_essay" ? `<p>Esse bali: <strong>${result.essay_score_75 ?? "hali kutilmoqda"}</strong></p>` : ""}
      <p style="color:#666;font-size:13px;margin-top:14px;">Daraja va umumiy natija test yakunlangach emas, admin natijalarni e'lon qilganda chiqadi. Xabar shaxsiy botga yuboriladi.</p>
    `;
    document.getElementById("nav-bar").style.display = "none";
    els.finishBtn.disabled = true;
  } catch (e) {
    els.area.innerHTML = `<p>Xatolik: ${e.message}</p>`;
  }
}

load();
