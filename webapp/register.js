// Ro'yxatdan o'tish ekrani: Ism-familya / Test kodi / Toifa — hammasi shu WebApp
// ichida, Telegram chatda hech narsa so'ralmaydi.
// Backend: webapp_server/app.py -> POST /api/register

const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const els = {
  form: document.getElementById("reg-form"),
  fullName: document.getElementById("full-name"),
  testCode: document.getElementById("test-code"),
  categoryOptions: document.getElementById("category-options"),
  error: document.getElementById("reg-error"),
  submit: document.getElementById("reg-submit"),
  confirm: document.getElementById("reg-confirm"),
  confirmWarning: document.getElementById("confirm-warning"),
  startBtn: document.getElementById("reg-start-btn"),
};

let selectedCategory = null;
let createdAttemptId = null;
let resumeMode = new URLSearchParams(location.search).get("resume") === "1";

const modeNew = document.getElementById("mode-new");
const modeResume = document.getElementById("mode-resume");
function applyMode() {
  modeNew.classList.toggle("active", !resumeMode);
  modeResume.classList.toggle("active", resumeMode);
  document.getElementById("name-block").classList.toggle("hidden", resumeMode);
  document.getElementById("category-block").classList.toggle("hidden", resumeMode);
  document.getElementById("resume-hint").classList.toggle("hidden", !resumeMode);
  els.submit.textContent = resumeMode ? "🔄 Davom ettirish" : "Davom etish";
  showError("");
}
modeNew.addEventListener("click", () => { resumeMode = false; applyMode(); });
modeResume.addEventListener("click", () => { resumeMode = true; applyMode(); });

// Telegram profilidan ism-familiyani oldindan to'ldirib qo'yamiz (o'zgartirish mumkin).
(function prefillName() {
  const user = tg?.initDataUnsafe?.user;
  if (user) {
    const name = [user.first_name, user.last_name].filter(Boolean).join(" ");
    if (name) els.fullName.value = name;
  }
})();

els.categoryOptions.querySelectorAll(".option-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    selectedCategory = btn.dataset.category;
    els.categoryOptions.querySelectorAll(".option-btn").forEach((b) => b.classList.remove("selected"));
    btn.classList.add("selected");
  });
});

function showError(text) {
  els.error.textContent = text;
}
applyMode();

els.submit.addEventListener("click", async () => {
  showError("");

  const fullName = els.fullName.value.trim();
  const testCode = els.testCode.value.trim().toUpperCase();

  if (!resumeMode && fullName.length < 3) {
    showError("Iltimos, to'liq ism-familiyangizni kiriting.");
    return;
  }
  if (!testCode) {
    showError("Iltimos, test kodini kiriting.");
    return;
  }
  if (!resumeMode && !selectedCategory) {
    showError("Iltimos, toifangizni belgilang.");
    return;
  }
  if (!tg?.initData) {
    showError("Bu oyna faqat Telegram ilovasi ichida ishlaydi. Iltimos, botga qaytib qaytadan urinib ko'ring.");
    return;
  }

  els.submit.disabled = true;
  els.submit.textContent = "Yuborilmoqda...";
  try {
    const res = await fetch("/api/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        init_data: tg.initData,
        full_name: resumeMode ? "" : fullName,
        test_code: testCode,
        category: resumeMode ? "" : selectedCategory,
        resume: resumeMode,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      showError(body.detail || `Xatolik: ${res.status}`);
      return;
    }

    createdAttemptId = body.attempt_id;

    let warning;
    if (body.resumed) {
      const rem = Math.floor((body.remaining_seconds || 0) / 60);
      warning = `🔄 Testingiz uzilgan joyidan davom ettiriladi.\n⏳ Qolgan vaqt: taxminan ${rem} daqiqa.\nOldin yozgan javoblaringiz saqlangan.`;
      els.startBtn.textContent = "▶️ Davom ettirish";
    } else {
      warning = `⏰ Sizga ${Math.floor(body.duration_minutes / 60)} soat vaqt beriladi, vaqtni to'xtatib bo'lmaydi.\n\n⚠️ Test faqat BIR MARTA topshiriladi. Agar internet uzilsa yoki Telegram yopilib qolsa — botda «Davom ettirish» tugmasi va test kodi orqali qolgan joyingizdan davom eting.`;
    }
    els.confirmWarning.textContent = warning;

    els.form.classList.add("hidden");
    els.confirm.classList.remove("hidden");
  } catch (e) {
    showError(`Xatolik: ${e.message}`);
  } finally {
    els.submit.disabled = false;
    els.submit.textContent = "Davom etish";
  }
});

els.startBtn.addEventListener("click", () => {
  if (createdAttemptId) {
    window.location.href = `/test?attempt_id=${createdAttemptId}`;
  }
});
