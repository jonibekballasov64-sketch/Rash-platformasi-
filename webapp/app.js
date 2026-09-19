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
  screens: [],
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

function escapeHtml(text) {
  return (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;");
}

// --- **qalin matn** -> <strong>, __qiya matn__ -> <em>. Matn avval escape
// qilingan bo'lishi kerak (xom, admin kiritgan matnga qo'llanadi).
function applyInlineFormatting(escaped) {
  let out = escaped.replace(/\*\*([^*]+)\*\*/g, (_, t) => `<strong>${t}</strong>`);
  out = out.replace(/__([^_]+)__/g, (_, t) => `<em>${t}</em>`);
  return out;
}

// --- | so'z | ramkali qismlarni <span class="framed-word"> ga aylantiradi,
// **qalin** va __qiya__ belgilarni ham qo'llaydi, va oddiy shu belgilar
// bo'lmagan matnni o'zgartirmaydi.
function renderFramedText(text) {
  const formatted = applyInlineFormatting(escapeHtml(text));
  return formatted.replace(/\|([^|]+)\|/g, (_, word) => `<span class="framed-word">${word.trim()}</span>`);
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
  state.screens = buildScreens(state.questions);
  state.deadline = new Date(state.data.deadline_at);
  startTimer();
  render();
}

// --- 33-35 kabi ketma-ket "matching" savollarni bitta ekranda (jadval
// ko'rinishida) ko'rsatish uchun ularni bitta guruhga birlashtiradi.
function buildScreens(questions) {
  const screens = [];
  let i = 0;
  while (i < questions.length) {
    const q = questions[i];
    if (q.type === "matching") {
      const group = [];
      while (i < questions.length && questions[i].type === "matching") {
        group.push(questions[i]);
        i++;
      }
      screens.push({ kind: "matching_group", questions: group });
    } else {
      screens.push({ kind: "single", question: q });
      i++;
    }
  }
  return screens;
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
  // screens.length (33-35 bitta ekranga birlashtirilgan) + (with_essay bo'lsa) 1 ta esse ekrani
  return state.screens.length + (state.data.test_type === "with_essay" ? 1 : 0);
}

function isEssayScreen(index) {
  return state.data.test_type === "with_essay" && index === state.screens.length;
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

  const screen = state.screens[idx];

  if (screen.kind === "matching_group") {
    els.area.innerHTML = renderMatchingGroup(screen);
    attachMatchingGroupHandlers(screen);
    return;
  }

  const q = screen.question;
  let html = "";
  if (q.passage) {
    html += `<div class="passage-box">${applyInlineFormatting(escapeHtml(q.passage.text)).replace(/\n/g, "<br>")}</div>`;
  }
  html += `<div class="question-text">${q.order_no}. ${renderFramedText(q.text)}</div>`;

  if (q.type === "single_choice") {
    html += renderSingleChoice(q);
  } else if (q.type === "short_answer") {
    html += renderShortAnswer(q, null);
  } else if (q.type === "two_part_short") {
    html += `<p><strong>A)</strong></p>` + renderShortAnswer(q, "A");
    html += `<p style="margin-top:16px"><strong>B) ${renderFramedText(q.part_b_text || "")}</strong></p>` + renderShortAnswer(q, "B");
  }

  els.area.innerHTML = html;
  attachHandlers(q);
}

// --- 33-35: PDF'dagi kabi bitta jadval — chapda gap, o'ngda A-F tugmalari.
function renderMatchingGroup(screen) {
  const qs = screen.questions;
  const optionEntries = Object.entries(qs[0].options || {});

  let html = '<div class="question-text">Quyidagi gaplarni to\'g\'ri javoblar bilan moslashtiring:</div>';
  html += '<table class="matching-table"><thead><tr><th>Gap</th>';
  for (const [letter] of optionEntries) {
    html += `<th>${letter}</th>`;
  }
  html += "</tr></thead><tbody>";
  for (const q of qs) {
    const selected = state.answers[answerKey(q.id, null)] || "";
    html += `<tr><td>${q.order_no}. ${renderFramedText(q.text)}</td>`;
    for (const [letter] of optionEntries) {
      const cls = selected === letter ? "letter-btn selected" : "letter-btn";
      html += `<td><button type="button" class="${cls}" data-qid="${q.id}" data-letter="${letter}">${letter}</button></td>`;
    }
    html += "</tr>";
  }
  html += "</tbody></table>";

  html += '<div class="matching-legend">';
  for (const [letter, text] of optionEntries) {
    html += `<div><strong>${letter})</strong> ${escapeHtml(text)}</div>`;
  }
  html += "</div>";
  return html;
}

function attachMatchingGroupHandlers(screen) {
  els.area.querySelectorAll(".letter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const qid = Number(btn.dataset.qid);
      const letter = btn.dataset.letter;
      state.answers[answerKey(qid, null)] = letter;
      saveAnswer(qid, null, letter);
      render();
    });
  });
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

// --- Yozma javob boshini avtomatik bosh harfga aylantiradi (ba'zi
// telefon/keyboardlarda HTML autocapitalize ishlamasligi mumkin, shu sabab
// buni qo'lda JS orqali ham ta'minlaymiz).
function autoCapitalizeFirst(input) {
  const value = input.value;
  if (value.length === 0) return;
  const capitalized = value.charAt(0).toUpperCase() + value.slice(1);
  if (capitalized !== value) {
    const pos = input.selectionStart;
    input.value = capitalized;
    if (pos !== null) input.setSelectionRange(pos, pos);
  }
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
  } else {
    els.area.querySelectorAll(".short-answer-input").forEach((input) => {
      input.addEventListener("input", () => autoCapitalizeFirst(input));
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

function getUnansweredNumbers() {
  const missing = [];
  for (const q of state.questions) {
    if (q.type === "two_part_short") {
      const missingParts = [];
      if (!state.answers[answerKey(q.id, "A")]) missingParts.push("A");
      if (!state.answers[answerKey(q.id, "B")]) missingParts.push("B");
      if (missingParts.length) missing.push(`${q.order_no} (${missingParts.join(", ")})`);
    } else {
      if (!state.answers[answerKey(q.id, null)]) missing.push(String(q.order_no));
    }
  }
  return missing;
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
  const missing = getUnansweredNumbers();
  const msg = missing.length > 0
    ? `Quyidagi savollarga javob belgilamagansiz: ${missing.join(", ")}.\n\nHaqiqatdan yakunlaysizmi?`
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
