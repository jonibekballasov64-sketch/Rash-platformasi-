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

els.submit.addEventListener("click", async () => {
  showError("");

  const fullName = els.fullName.value.trim();
  const testCode = els.testCode.value.trim().toUpperCase();

  if (fullName.length < 3) {
    showError("Iltimos, to'liq ism-familiyangizni kiriting.");
    return;
  }
  if (!testCode) {
    showError("Iltimos, test kodini kiriting.");
    return;
  }
  if (!selectedCategory) {
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
        full_name: fullName,
        test_code: testCode,
        category: selectedCategory,
      }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      showError(body.detail || `Xatolik: ${res.status}`);
      return;
    }

    createdAttemptId = body.attempt_id;

    let warning = `⏰ Sizga ${Math.floor(body.duration_minutes / 60)} soat vaqt beriladi, vaqtni to'xtatib bo'lmaydi.\nBu sizning ${body.attempt_number}-urinishingiz (jami 2 marta urinish mumkin).`;
    if (body.attempt_number === 1) {
      warning += "\n\n⚠️ 1-urinish ustozga ko'rinadi va sizning rasmiy natijangiz hisoblanadi.";
    } else {
      warning += "\n\n⚠️ Bu 2-urinish — faqat o'zingiz uchun, rasmiy natijaga ta'sir qilmaydi.";
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
