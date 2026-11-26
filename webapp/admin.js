// Admin paneli: testlar ro'yxati -> test sahifasi (tahrirlash / to'xtatish / natija / qayta ochish)
const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const main = document.getElementById("admin-main");
const backBtn = document.getElementById("back-btn");
const titleEl = document.getElementById("admin-title");
const toastEl = document.getElementById("toast");
let backStack = [];

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function toast(msg) {
  toastEl.textContent = msg;
  toastEl.classList.remove("hidden");
  setTimeout(() => toastEl.classList.add("hidden"), 2200);
}
async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", "X-Init-Data": tg?.initData || "", ...(opts.headers || {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Xatolik: ${res.status}`);
  return body;
}
function show(view, title, back) {
  titleEl.textContent = title;
  main.innerHTML = view;
  backBtn.classList.toggle("hidden", !back);
  backBtn.onclick = back || null;
  window.scrollTo(0, 0);
}
function fail(e) {
  main.innerHTML = `<div class="card flat"><p style="color:var(--red)">${esc(e.message)}</p></div>`;
}

// ---------- 1) Yaratilgan testlar ----------
async function listView() {
  try {
    const { tests } = await api("/api/admin/tests");
    let html = `<div class="section-title">📚 Yaratilgan testlar</div>`;
    if (!tests.length) html += `<div class="card flat">Hali test yo'q.</div>`;
    html += tests
      .map(
        (t) => `<div class="test-row" data-id="${t.id}">
        <div class="num">${t.n}</div>
        <div class="info"><div class="t-title">${esc(t.title || "(nomsiz)")}</div>
        <div class="t-meta">Kod: <b>${esc(t.code)}</b> · ${t.finished} yakunladi${t.in_progress ? ` · ${t.in_progress} ishlayapti` : ""}</div></div>
        <span class="badge ${t.status}">${esc(t.status_label)}</span></div>`
      )
      .join("");
    show(html, "🛠 Admin panel", null);
    main.querySelectorAll(".test-row").forEach((el) => el.addEventListener("click", () => testView(el.dataset.id)));
  } catch (e) { fail(e); }
}

// ---------- 2) Bitta test ----------
async function testView(id) {
  try {
    const t = await api(`/api/admin/tests/${id}`);
    const closed = t.status === "closed";
    const html = `<div class="card flat">
        <div class="t-title big">${esc(t.title || "(nomsiz)")}</div>
        <div class="t-meta">Kod: <b>${esc(t.code)}</b> · ${t.questions.length} savol · ${t.duration_minutes} daqiqa</div>
        <div class="t-meta">Holat: <span class="badge ${t.status}">${esc(t.status_label)}</span></div>
      </div>
      <button class="act" id="a-edit">✏️ Testni tahrirlash</button>
      <button class="act" id="a-res">📊 Natijani olish</button>
      ${closed
        ? `<button class="act green" id="a-reopen">🔓 Qayta ochish</button>`
        : `<button class="act red" id="a-stop">⏸ To'xtatish</button>`}
      <p class="hint">To'xtatilgan testga yangi o'quvchi kira olmaydi. Ishlayotganlar tugatishi mumkin.</p>`;
    show(html, "Test", listView);
    document.getElementById("a-edit").onclick = () => editView(id);
    document.getElementById("a-res").onclick = () => resultsView(id);
    const stop = document.getElementById("a-stop"), reopen = document.getElementById("a-reopen");
    if (stop) stop.onclick = () => setStatus(id, "close", "Testni to'xtatamizmi? Yangi o'quvchilar kira olmaydi.");
    if (reopen) reopen.onclick = () => setStatus(id, "reopen", "Testni qayta ochamizmi?");
  } catch (e) { fail(e); }
}
async function setStatus(id, action, q) {
  if (!confirm(q)) return;
  try {
    const r = await api(`/api/admin/tests/${id}/status`, { method: "POST", body: JSON.stringify({ action }) });
    toast(r.status === "closed" ? "⏸ Test to'xtatildi" : "🔓 Test qayta ochildi");
    testView(id);
  } catch (e) { toast(e.message); }
}

// ---------- 3) Natijalar ----------
async function resultsView(id) {
  show(`<p>Natijalar hisoblanmoqda...</p>`, "📊 Natijalar", () => testView(id));
  try {
    const { rows } = await api(`/api/admin/tests/${id}/results`);
    let html = `<div class="section-title">📊 Natijalar (${rows.length})</div>`;
    if (!rows.length) html += `<div class="card flat">Hali hech kim ishlamagan.</div>`;
    else {
      html += `<div class="table-wrap"><table class="rt"><thead><tr><th>№</th><th>Ism</th><th>To'g'ri</th><th>Ball</th><th>Daraja</th></tr></thead><tbody>`;
      rows.forEach((r, i) => {
        html += `<tr><td>${i + 1}</td><td>${esc(r.name)}<div class="t-meta">${esc(r.category)} · ${esc(r.status)}</div></td>
          <td>${r.correct ?? "-"}</td><td>${r.final ?? (r.rasch != null ? r.rasch + "*" : "-")}</td><td>${esc(r.grade || "-")}</td></tr>`;
      });
      html += `</tbody></table></div><p class="hint">* — faqat 44-test (Rasch) bali; qo'shimcha ball kiritilmagan.</p>
        <button class="act" id="a-pdf">📄 PDF faylni botga yuborish</button>`;
    }
    show(html, "📊 Natijalar", () => testView(id));
    const b = document.getElementById("a-pdf");
    if (b) b.onclick = async () => {
      b.disabled = true; b.textContent = "Tayyorlanmoqda...";
      try { const r = await api(`/api/admin/tests/${id}/send-pdf`, { method: "POST" }); toast(`✅ PDF botga yuborildi (${r.count} kishi)`); }
      catch (e) { toast(e.message); }
      b.disabled = false; b.textContent = "📄 PDF faylni botga yuborish";
    };
  } catch (e) { fail(e); }
}

// ---------- 4) Tahrirlash ----------
async function editView(id) {
  try {
    const t = await api(`/api/admin/tests/${id}`);
    let html = `<div class="card flat">
      <label class="field-label">Test nomi</label><input id="e-title" class="short-answer-input" value="${esc(t.title)}" />
      <label class="field-label">Davomiyligi (daqiqa)</label><input id="e-dur" type="number" class="short-answer-input" value="${t.duration_minutes}" />
      <button class="gold-btn" id="e-save">💾 Saqlash</button></div>`;
    if (t.passages.length) {
      html += `<div class="section-title">📖 Matnlar</div>`;
      html += t.passages.map((p) => `<div class="q-row" data-p="${p.id}"><b>${esc(p.type.toUpperCase())}</b> matni<span>›</span></div>`).join("");
    }
    html += `<div class="section-title">❓ Savollar</div>`;
    html += t.questions
      .map((q) => `<div class="q-row" data-q="${q.id}"><b>${q.order_no}.</b> ${esc(q.text.replace(/[*_|]/g, "").slice(0, 70))}<span>›</span></div>`)
      .join("");
    show(html, "✏️ Tahrirlash", () => testView(id));
    document.getElementById("e-save").onclick = async () => {
      try {
        await api(`/api/admin/tests/${id}`, { method: "PUT", body: JSON.stringify({
          title: document.getElementById("e-title").value, duration_minutes: Number(document.getElementById("e-dur").value) }) });
        toast("✅ Saqlandi");
      } catch (e) { toast(e.message); }
    };
    main.querySelectorAll("[data-q]").forEach((el) => el.onclick = () => questionView(id, t.questions.find((q) => q.id == el.dataset.q)));
    main.querySelectorAll("[data-p]").forEach((el) => el.onclick = () => passageView(id, t.passages.find((p) => p.id == el.dataset.p)));
  } catch (e) { fail(e); }
}

function passageView(testId, p) {
  show(`<div class="card flat"><label class="field-label">${esc(p.type.toUpperCase())} matni</label>
    <textarea id="p-text" rows="14" class="short-answer-input">${esc(p.text)}</textarea>
    <p class="hint">**qalin**, __qiya__, |ramkali| belgilar ishlaydi.</p>
    <button class="gold-btn" id="p-save">💾 Saqlash</button></div>`, "Matnni tahrirlash", () => editView(testId));
  document.getElementById("p-save").onclick = async () => {
    try { await api(`/api/admin/passages/${p.id}`, { method: "PUT", body: JSON.stringify({ text: document.getElementById("p-text").value }) }); toast("✅ Saqlandi"); }
    catch (e) { toast(e.message); }
  };
}

function questionView(testId, q) {
  const lines = (a) => (a || []).join("\n");
  const ta = (id, label, val, rows = 4) => `<label class="field-label">${label}</label><textarea id="${id}" rows="${rows}" class="short-answer-input">${esc(val)}</textarea>`;
  let html = `<div class="card flat"><div class="t-title big">${q.order_no}-savol</div>`;
  html += ta("f-text", "Savol matni", q.text, 5);
  if (q.type === "single_choice" || (q.type === "matching" && q.options)) {
    Object.keys(q.options || {}).forEach((k) => {
      html += `<label class="field-label">${k}) variant</label><input class="short-answer-input f-opt" data-k="${k}" value="${esc(q.options[k])}" />`;
    });
  }
  if (q.type === "single_choice" || q.type === "matching") {
    html += `<label class="field-label">To'g'ri javob harfi</label><input id="f-correct" class="short-answer-input" value="${esc(q.correct_option || "")}" />`;
  }
  if (q.type === "short_answer") html += ta("f-acc", "Qabul qilinadigan javoblar (har biri yangi qatorda)", lines(q.accepted_answers), 3);
  if (q.type === "two_part_short") {
    html += ta("f-pa", "A) qism savoli", q.part_a_text, 3);
    html += ta("f-acc", "A) javoblari (har biri yangi qatorda)", lines(q.accepted_answers), 3);
    html += ta("f-pb", "B) qism savoli", q.part_b_text, 3);
    html += ta("f-bacc", "B) javoblari (har biri yangi qatorda)", lines(q.part_b_accepted_answers), 3);
    html += ta("f-bexp", "B) izohi", q.part_b_explanation, 3);
  }
  html += ta("f-exp", "Izoh", q.explanation, 4);
  html += `<p class="hint">**qalin**, __qiya__, |ramkali| belgilar ishlaydi.</p><button class="gold-btn" id="q-save">💾 Saqlash</button></div>`;
  show(html, `${q.order_no}-savol`, () => editView(testId));
  document.getElementById("q-save").onclick = async () => {
    const v = (id) => document.getElementById(id)?.value;
    const split = (id) => (v(id) || "").split("\n").map((x) => x.trim()).filter(Boolean);
    const body = { text: v("f-text"), explanation: v("f-exp") };
    if (document.querySelector(".f-opt")) {
      body.options = {};
      document.querySelectorAll(".f-opt").forEach((i) => (body.options[i.dataset.k] = i.value));
    }
    if (document.getElementById("f-correct")) body.correct_option = v("f-correct");
    if (q.type === "short_answer") body.accepted_answers = split("f-acc");
    if (q.type === "two_part_short") {
      body.part_a_text = v("f-pa"); body.accepted_answers = split("f-acc");
      body.part_b_text = v("f-pb"); body.part_b_accepted_answers = split("f-bacc"); body.part_b_explanation = v("f-bexp");
    }
    try { await api(`/api/admin/questions/${q.id}`, { method: "PUT", body: JSON.stringify(body) }); toast("✅ Saqlandi"); }
    catch (e) { toast(e.message); }
  };
}

listView();
