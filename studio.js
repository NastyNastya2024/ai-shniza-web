// @ts-nocheck
const qs = (s, r = document) => r.querySelector(s);
const qsa = (s, r = document) => Array.from(r.querySelectorAll(s));

let currentUser = null;
let models = [];
let selectedModel = null;
let filterCat = "all";
let filterAudio = false;
let sortMode = "price";
let attachFile = null;
let chatHistory = [];

async function ensureCsrf() {
  if (window.__csrfToken) return window.__csrfToken;
  const m = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
  if (m) {
    window.__csrfToken = decodeURIComponent(m[1]);
    return window.__csrfToken;
  }
  const res = await fetch("/api/csrf", { credentials: "same-origin" });
  const data = await res.json().catch(() => ({}));
  window.__csrfToken = data.csrf_token || "";
  return window.__csrfToken;
}

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (method !== "GET" && method !== "HEAD") headers["X-CSRF-Token"] = await ensureCsrf();
  const res = await fetch(path, { credentials: "same-origin", ...options, headers });
  let data = {};
  try {
    data = await res.json();
  } catch (_) {}
  return { res, data };
}

function formatBalance(kop) {
  const rub = (Number(kop) || 0) / 100;
  return `${rub.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
}

async function loadUser() {
  const { data } = await api("/api/auth/me");
  currentUser = data.user || null;
  window.__freeLeft = data.free_left != null ? data.free_left : 1;
  const letter = qs("[data-avatar-letter]");
  const loginBtn = qs("[data-login]");
  const logoutBtn = qs("[data-logout]");
  if (currentUser) {
    letter.textContent = (currentUser.name || currentUser.email || "?").slice(0, 1).toUpperCase();
    loginBtn.hidden = true;
    logoutBtn.hidden = false;
  } else {
    letter.textContent = "?";
    loginBtn.hidden = false;
    logoutBtn.hidden = true;
  }
  const bal = data.available_kop != null ? data.available_kop : data.balance_kop != null ? data.balance_kop : 0;
  qs("[data-balance]").textContent = formatBalance(bal);
}

async function loadModels() {
  const { data } = await api("/api/pricing");
  models = data.items || [];
  renderModels();
}

function modelMatches(m, q) {
  if (filterCat !== "all") {
    const map = { video: "video", image: "image", music: "music", voice: "voice", text: "text" };
    if (m.category !== map[filterCat] && !(filterCat === "image" && m.category === "tool")) return false;
  }
  if (filterAudio && !m.has_audio) return false;
  if (!q) return true;
  const hay = `${m.model_key} ${m.description_ru} ${m.version_label || ""}`.toLowerCase();
  return hay.includes(q);
}

function groupedModels(list) {
  const seedance = list.filter((m) => m.family === "seedance");
  const rest = list.filter((m) => m.family !== "seedance");
  const out = [];
  if (seedance.length) {
    const preferred =
      seedance.find((m) => m.version_label === "2.0 Mini") ||
      seedance.find((m) => m.model_key.includes("2.0")) ||
      seedance[0];
    out.push({ kind: "seedance", versions: seedance, current: preferred });
  }
  rest.forEach((m) => out.push({ kind: "single", model: m }));
  return out;
}

function renderModels() {
  const q = (qs("[data-models-search]").value || "").trim().toLowerCase();
  let list = models.filter((m) => modelMatches(m, q));
  list = list.slice().sort((a, b) => {
    if (sortMode === "quality") return (b.quality_score || 0) - (a.quality_score || 0);
    return (a.price_rub || 0) - (b.price_rub || 0);
  });
  const root = qs("[data-models-list]");
  root.innerHTML = "";
  const groups = groupedModels(list);
  groups.forEach((g) => {
    if (g.kind === "seedance") {
      const m = g.current;
      const card = document.createElement("button");
      card.type = "button";
      card.className = "model-card" + (selectedModel?.model_key === m.model_key ? " is-selected" : "");
      card.innerHTML = `
        <h3>Seedance</h3>
        <p>${m.description_ru || "Видео ByteDance"}</p>
        <div class="price">${m.price_label || ""}</div>
        <div class="badges">
          ${m.is_free ? '<span class="badge badge--free">Бесплатно</span>' : ""}
          ${m.has_audio ? '<span class="badge">Со звуком</span>' : ""}
          <span class="badge">Новинка</span>
        </div>
        <select class="seedance-select" data-seedance-select>
          ${g.versions
            .map(
              (v) =>
                `<option value="${v.model_key}" ${v.model_key === m.model_key ? "selected" : ""}>${v.version_label || v.model_key} — ${v.price_label}</option>`
            )
            .join("")}
        </select>`;
      const select = card.querySelector("[data-seedance-select]");
      select.addEventListener("click", (e) => e.stopPropagation());
      select.addEventListener("change", () => {
        const next = g.versions.find((v) => v.model_key === select.value);
        if (next) selectModel(next);
      });
      card.addEventListener("click", () => {
        const next = g.versions.find((v) => v.model_key === select.value) || m;
        selectModel(next);
      });
      root.appendChild(card);
    } else {
      const m = g.model;
      const card = document.createElement("button");
      card.type = "button";
      card.className = "model-card" + (selectedModel?.model_key === m.model_key ? " is-selected" : "");
      card.innerHTML = `
        <h3>${displayName(m)}</h3>
        <p>${m.description_ru || ""}</p>
        <div class="price">${m.price_label || ""}</div>
        <div class="badges">
          ${m.is_free ? '<span class="badge badge--free">Бесплатно</span>' : ""}
          ${m.has_audio ? '<span class="badge">Со звуком</span>' : ""}
        </div>`;
      card.addEventListener("click", () => selectModel(m));
      root.appendChild(card);
    }
  });
}

function displayName(m) {
  if (m.family === "seedance") return `Seedance ${m.version_label || ""}`.trim();
  const key = m.model_key || "";
  const tail = key.split("/").pop();
  return tail || key;
}

function selectModel(m) {
  selectedModel = m;
  const chip = qs("[data-selected-chip]");
  chip.hidden = false;
  chip.innerHTML = `<span class="sel-chip">${displayName(m)} · ${m.price_label || ""} <button type="button" aria-label="Сбросить">×</button></span>`;
  chip.querySelector("button").addEventListener("click", () => {
    selectedModel = null;
    chip.hidden = true;
    renderModels();
  });
  renderModels();
  closeModels();
}

function showThread() {
  qs("[data-chat-empty]").hidden = true;
  qs("[data-chat-thread]").hidden = false;
}

async function onCreateOption(opt) {
  if (!currentUser) {
    openAuth();
    return;
  }
  const model_key = opt.model_key;
  if (!model_key) {
    appendBubble("assistant", "Не выбрана модель.");
    return;
  }
  const prompt =
    opt.prompt ||
    (chatHistory.filter((m) => m.role === "user").slice(-1)[0] || {}).content ||
    "";
  if (!prompt) {
    appendBubble("assistant", "Нужен текст задачи для генерации.");
    return;
  }
  await startGeneration({ model_key, prompt, params: opt.params || { duration_sec: 5 }, title: opt.title });
}

async function startGeneration({ model_key, prompt, params, title }) {
  const est = await api("/api/jobs/estimate", {
    method: "POST",
    body: JSON.stringify({ model_key, params }),
  });
  if (!est.res.ok) {
    appendBubble("assistant", "Не удалось оценить цену.");
    return;
  }
  const priceKop = est.data.price_kop || 0;
  if (priceKop > 10000) {
    const ok = window.confirm(`Списать ${(priceKop / 100).toFixed(0)} ₽?`);
    if (!ok) return;
  }
  if (est.data.enough === false && priceKop > 0) {
    const need = priceKop - (est.data.available_kop || 0);
    appendBubble(
      "assistant",
      `Не хватает ${(need / 100).toFixed(0)} ₽. Пополните баланс или выберите бесплатный вариант.`,
      [
        { title: "Пополнить", cta: "К балансу", action: "topup" },
      ]
    );
    return;
  }

  const card = appendJobCard({
    title: title || model_key,
    status: "Запуск…",
    priceKop,
  });

  const start = await api("/api/jobs/start", {
    method: "POST",
    body: JSON.stringify({
      model_key,
      prompt,
      params,
      confirm: priceKop > 10000,
    }),
  });
  if (!start.res.ok) {
    const err = start.data.error || "error";
    if (err === "insufficient_funds") {
      updateJobCard(card, { status: "Недостаточно средств", failed: true });
      openTopup();
      return;
    }
    if (err === "free_limit") {
      updateJobCard(card, { status: "Лимит бесплатных на сегодня", failed: true });
      return;
    }
    if (err === "free_queue_full") {
      updateJobCard(card, { status: "Очередь бесплатных переполнена", failed: true });
      return;
    }
    updateJobCard(card, { status: "Не получилось, деньги вернулись на баланс", failed: true, retry: { model_key, prompt, params, title } });
    await loadUser();
    return;
  }

  const jobId = start.data.job_id;
  const workId = start.data.work_id;
  card.dataset.jobId = jobId;
  card.dataset.workId = workId;
  updateJobCard(card, {
    status: start.data.status === "queued_free" ? "В бесплатной очереди…" : start.data.status === "succeeded" ? "Готово" : "В очереди…",
  });
  await loadUser();

  if (start.data.status === "succeeded") {
    await finishJobCard(card, jobId, workId);
    return;
  }
  if (start.data.status === "queued_free") {
    pollFreeQueue(card, jobId);
  }
  watchJob(card, jobId, workId);
}

function appendJobCard(info) {
  showThread();
  const thread = qs("[data-chat-thread]");
  const el = document.createElement("div");
  el.className = "job-card";
  el.innerHTML = `
    <div class="job-card__head"><strong class="job-title"></strong><span class="job-price"></span></div>
    <div class="job-status"></div>
    <div class="job-media" hidden></div>
    <div class="job-actions"></div>`;
  thread.appendChild(el);
  updateJobCard(el, info);
  qs("[data-chat-scroll]").scrollTop = qs("[data-chat-scroll]").scrollHeight;
  return el;
}

function updateJobCard(card, info) {
  if (info.title) card.querySelector(".job-title").textContent = info.title;
  if (info.priceKop != null) {
    card.querySelector(".job-price").textContent =
      info.priceKop === 0 ? "Бесплатно" : `${(info.priceKop / 100).toFixed(0)} ₽`;
  }
  if (info.status) card.querySelector(".job-status").textContent = info.status;
  const actions = card.querySelector(".job-actions");
  if (info.failed && info.retry) {
    actions.innerHTML = "";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Повторить";
    btn.addEventListener("click", () => startGeneration(info.retry));
    actions.appendChild(btn);
  }
  if (info.paidAlt) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = `Сделать сразу — ${info.paidAlt.label}`;
    btn.addEventListener("click", () =>
      startGeneration({
        model_key: info.paidAlt.model_key,
        prompt: info.prompt,
        params: { duration_sec: 5 },
        title: info.paidAlt.label,
      })
    );
    actions.appendChild(btn);
  }
}

async function pollFreeQueue(card, jobId) {
  for (let i = 0; i < 120; i++) {
    const { data } = await api(`/api/jobs/${jobId}/queue`);
    if (data.position > 0) {
      updateJobCard(card, {
        status: `Место в очереди: ${data.position} · ~${data.eta_min || data.position * 10} мин`,
        paidAlt: data.paid_alt,
        prompt: card.dataset.prompt,
      });
    }
    await new Promise((r) => setTimeout(r, 15000));
    const st = await api(`/api/jobs/${jobId}`);
    const status = st.data.job?.status;
    if (status === "succeeded" || status === "failed") break;
  }
}

function watchJob(card, jobId, workId) {
  let done = false;
  const finish = async (payload) => {
    if (done) return;
    done = true;
    const st = payload?.job?.status;
    if (st === "failed" || st === "error") {
      updateJobCard(card, { status: "Не получилось, деньги вернулись на баланс", failed: true });
      await loadUser();
      return;
    }
    await finishJobCard(card, jobId, workId, payload);
  };

  try {
    const es = new EventSource(`/api/jobs/stream?id=${encodeURIComponent(jobId)}`, { withCredentials: true });
    es.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data);
        const st = payload.job?.status;
        if (st === "queued" || st === "queued_free") updateJobCard(card, { status: "В очереди…" });
        if (st === "running") updateJobCard(card, { status: "Генерируется…" });
        if (st === "succeeded" || st === "failed" || st === "error") {
          es.close();
          finish(payload);
        }
      } catch (_) {}
    };
    es.onerror = () => {
      es.close();
      pollJob(card, jobId, workId, finish);
    };
  } catch (_) {
    pollJob(card, jobId, workId, finish);
  }
}

async function pollJob(card, jobId, workId, finish) {
  for (let i = 0; i < 40; i++) {
    const { data } = await api(`/api/jobs/${jobId}`);
    const st = data.job?.status;
    if (st === "running") updateJobCard(card, { status: "Генерируется…" });
    if (st === "succeeded" || st === "failed" || st === "error" || data.work?.original_url || data.work?.media_url) {
      await finish(data);
      return;
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
  updateJobCard(card, { status: "Ещё генерируется — результат будет в «Мои работы»" });
}

async function finishJobCard(card, jobId, workId, payload) {
  let work = payload?.work;
  if (!work) {
    const { data } = await api(`/api/jobs/${jobId}`);
    work = data.work;
  }
  const url = work?.media_url || work?.thumb_url || payload?.job?.output;
  updateJobCard(card, { status: "Готово" });
  const media = card.querySelector(".job-media");
  media.hidden = false;
  if (url) {
    if ((work?.kind || "image") === "video") {
      media.innerHTML = `<video src="${url}" controls playsinline style="max-width:100%;border-radius:12px"></video>`;
    } else if (work?.kind === "audio") {
      media.innerHTML = `<audio src="${url}" controls style="width:100%"></audio>`;
    } else {
      media.innerHTML = `<img src="${url}" alt="" style="max-width:100%;border-radius:12px" />`;
    }
  }
  const actions = card.querySelector(".job-actions");
  actions.innerHTML = "";
  const mk = (label, fn) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.addEventListener("click", fn);
    actions.appendChild(b);
  };
  if (url) mk("Скачать", () => window.open(url, "_blank"));
  if (workId) {
    mk("Сохранить в мои работы", async () => {
      await api(`/api/works/${workId}/save`, { method: "POST", body: "{}" });
      updateJobCard(card, { status: "Сохранено" });
    });
    mk("Опубликовать", () => openPublish(workId, card));
  }
  mk("Ещё вариант", () => {
    const model = selectedModel?.model_key || work?.model_key;
    const prompt = (chatHistory.filter((m) => m.role === "user").slice(-1)[0] || {}).content;
    if (model && prompt) startGeneration({ model_key: model, prompt, params: { duration_sec: 5 } });
  });
  await loadUser();
}

function openPublish(workId, card) {
  const dlg = qs("[data-publish-dialog]");
  if (!dlg) return;
  dlg.showModal();
  const form = qs("[data-publish-form]");
  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const title = String(fd.get("title") || "");
    const tags = String(fd.get("tags") || "")
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean)
      .slice(0, 5);
    const agree = Boolean(fd.get("agree"));
    const { res, data } = await api(`/api/works/${workId}/publish`, {
      method: "POST",
      body: JSON.stringify({ title, tags, agree_rules: agree }),
    });
    if (!res.ok) {
      const err = qs("[data-publish-error]");
      err.hidden = false;
      err.textContent =
        data.error === "handle_required"
          ? "Сначала выберите ник в настройках"
          : data.error === "agree_required"
            ? "Нужно согласие с правилами"
            : "Не удалось опубликовать";
      if (data.error === "handle_required") location.href = "/settings";
      return;
    }
    dlg.close();
    updateJobCard(card, { status: "Опубликовано" });
  };
}

function openTopup() {
  location.href = "/balance";
}

function appendBubble(role, text, options) {
  showThread();
  const thread = qs("[data-chat-thread]");
  const el = document.createElement("div");
  el.className = `bubble bubble--${role}`;
  el.textContent = text;
  if (options?.length) {
    const wrap = document.createElement("div");
    wrap.className = "option-cards";
    options.forEach((opt) => {
      if (opt.action === "topup") {
        const card = document.createElement("div");
        card.className = "option-card";
        card.innerHTML = `<strong>${opt.title}</strong>`;
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = opt.cta || "Открыть";
        btn.addEventListener("click", openTopup);
        card.appendChild(btn);
        wrap.appendChild(card);
        return;
      }
      const card = document.createElement("div");
      card.className = "option-card";
      card.innerHTML = `<strong>${opt.title}</strong><div class="meta">${opt.meta || ""}</div>`;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = opt.cta || "Создать";
      btn.addEventListener("click", () => onCreateOption(opt));
      card.appendChild(btn);
      wrap.appendChild(card);
    });
    el.appendChild(wrap);
  }
  thread.appendChild(el);
  qs("[data-chat-scroll]").scrollTop = qs("[data-chat-scroll]").scrollHeight;
}

async function sendMessage() {
  const input = qs("[data-input]");
  const text = (input.value || "").trim();
  if (!text && !attachFile) return;
  input.value = "";
  autoSize(input);
  appendBubble("user", text || "[картинка]");
  chatHistory.push({ role: "user", content: text });
  const payloadMessages = chatHistory.slice(-6);
  const freeLeft = currentUser ? (window.__freeLeft ?? 1) : 0;
  const { res, data } = await api("/api/assistant", {
    method: "POST",
    body: JSON.stringify({
      messages: payloadMessages,
      has_image: Boolean(attachFile),
      free_left: freeLeft,
    }),
  });
  if (!res.ok) {
    const options = suggestLocal(text);
    appendBubble("assistant", "Не удалось связаться с ассистентом — вот локальные варианты.", options);
    return;
  }
  const options = (data.options || []).map((o) => ({
    title: o.title || o.model_key,
    meta: o.meta || o.why || "",
    cta: o.cta || (o.price_rub != null ? (o.price_rub === 0 ? "Бесплатно" : `Создать за ${o.price_rub} ₽`) : "Создать"),
    model_key: o.model_key,
    price_rub: o.price_rub || 0,
    params: o.params || { duration_sec: 5 },
    prompt: text,
  }));
  appendBubble("assistant", data.reply || "Варианты ниже.", options);
  if (data.clarify) appendBubble("assistant", data.clarify);
}

function suggestLocal(text) {
  const t = text.toLowerCase();
  const wantFree = /бесплат|даром|очеред/.test(t);
  const wantVideo = /видео|ролик|клип|сек|секунд|кот|космонавт/.test(t) || true;
  const pool = models.filter((m) => (wantVideo ? m.category === "video" : true));
  const picks = [];
  const free = pool.find((m) => m.is_free);
  if (free && (wantFree || true)) {
    picks.push({
      title: displayName(free),
      meta: "Бесплатно · очередь ~40 мин · лимит сегодня",
      cta: "Бесплатно",
      model_key: free.model_key,
      price_rub: 0,
      prompt: text,
      params: { duration_sec: 5 },
    });
  }
  const cheap = pool.filter((m) => !m.is_free).sort((a, b) => (a.example_rub_5s || a.price_rub) - (b.example_rub_5s || b.price_rub))[0];
  if (cheap) {
    picks.push({
      title: displayName(cheap),
      meta: `${cheap.price_label} · быстрее очереди`,
      cta: `Создать за ${cheap.example_rub_5s || cheap.price_rub} ₽`,
      model_key: cheap.model_key,
      price_rub: cheap.example_rub_5s || cheap.price_rub,
      prompt: text,
      params: { duration_sec: 5 },
    });
  }
  const best = pool.filter((m) => !m.is_free).sort((a, b) => (b.quality_score || 0) - (a.quality_score || 0))[0];
  if (best && best.model_key !== cheap?.model_key) {
    picks.push({
      title: displayName(best),
      meta: `${best.price_label} · выше качество`,
      cta: `Создать за ${best.example_rub_5s || best.price_rub} ₽`,
      model_key: best.model_key,
      price_rub: best.example_rub_5s || best.price_rub,
      prompt: text,
      params: { duration_sec: 5 },
    });
  }
  return picks.slice(0, 3);
}

function autoSize(el) {
  el.style.height = "auto";
  el.style.height = Math.min(160, el.scrollHeight) + "px";
}

function openRail() {
  qs("[data-rail]").classList.add("is-open");
  qs("[data-backdrop]").hidden = false;
}
function closeRail() {
  qs("[data-rail]").classList.remove("is-open");
  if (!qs("[data-models-panel]").classList.contains("is-open")) qs("[data-backdrop]").hidden = true;
}
function openModels() {
  qs("[data-models-panel]").classList.add("is-open");
  qs("[data-backdrop]").hidden = false;
}
function closeModels() {
  qs("[data-models-panel]").classList.remove("is-open");
  if (!qs("[data-rail]").classList.contains("is-open")) qs("[data-backdrop]").hidden = true;
}
function openAuth() {
  location.href = "/auth?next=" + encodeURIComponent(location.pathname + location.search);
}

function wire() {
  qs("[data-new-chat]").addEventListener("click", () => {
    chatHistory = [];
    qs("[data-chat-thread]").innerHTML = "";
    qs("[data-chat-thread]").hidden = true;
    qs("[data-chat-empty]").hidden = false;
    closeRail();
  });
  qs("[data-open-rail]").addEventListener("click", openRail);
  qs("[data-open-models]").addEventListener("click", openModels);
  qs("[data-close-models]").addEventListener("click", closeModels);
  qs("[data-backdrop]").addEventListener("click", () => {
    closeRail();
    closeModels();
  });
  qs("[data-avatar-btn]").addEventListener("click", () => {
    const pop = qs("[data-user-pop]");
    pop.hidden = !pop.hidden;
  });
  qs("[data-login]").addEventListener("click", openAuth);
  qs("[data-logout]").addEventListener("click", async () => {
    await api("/api/auth/logout", { method: "POST" });
    await loadUser();
  });
  qs("[data-topup]").addEventListener("click", () => {
    if (!currentUser) return openAuth();
    openTopup();
  });
  qs("[data-nav-works]")?.addEventListener("click", async (e) => {
    e.preventDefault();
    await showMyWorks();
  });
  qs("[data-send]").addEventListener("click", sendMessage);
  qs("[data-input]").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  qs("[data-input]").addEventListener("input", (e) => autoSize(e.target));
  qs("[data-attach]").addEventListener("click", () => qs("[data-file]").click());
  qs("[data-file]").addEventListener("change", (e) => {
    attachFile = e.target.files?.[0] || null;
    const prev = qs("[data-attach-preview]");
    if (attachFile) {
      prev.hidden = false;
      prev.textContent = `Файл: ${attachFile.name}`;
    } else {
      prev.hidden = true;
    }
  });
  qsa("[data-hint]").forEach((btn) =>
    btn.addEventListener("click", () => {
      qs("[data-input]").value = btn.textContent;
      sendMessage();
    })
  );
  qsa("[data-cat]").forEach((chip) =>
    chip.addEventListener("click", () => {
      qsa("[data-cat]").forEach((c) => c.classList.toggle("is-on", c === chip));
      filterCat = chip.getAttribute("data-cat");
      renderModels();
    })
  );
  const audioChip = qs('[data-audio="1"]');
  audioChip.addEventListener("click", () => {
    filterAudio = !filterAudio;
    audioChip.classList.toggle("is-on", filterAudio);
    renderModels();
  });
  qs("[data-models-search]").addEventListener("input", renderModels);
  qs("[data-models-sort]").addEventListener("change", (e) => {
    sortMode = e.target.value;
    renderModels();
  });
  const form = qs("[data-auth-form]");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const email = String(fd.get("email") || "");
    const password = String(fd.get("password") || "");
    const code = String(fd.get("code") || "");
    const consent = Boolean(fd.get("consent"));
    const err = qs("[data-auth-error]");
    err.hidden = true;
    if (code) {
      const { res, data } = await api("/api/auth/email-code/verify", {
        method: "POST",
        body: JSON.stringify({ email, code }),
      });
      if (!res.ok) {
        err.hidden = false;
        err.textContent = "Неверный или просроченный код";
        return;
      }
      qs("[data-auth-dialog]").close();
      await loadUser();
      return;
    }
    if (!password) {
      const { res, data } = await api("/api/auth/email-code/request", {
        method: "POST",
        body: JSON.stringify({ email, consent_152: consent }),
      });
      if (!res.ok) {
        err.hidden = false;
        err.textContent = data.error === "consent_required" ? "Нужно согласие" : "Не удалось отправить код";
        return;
      }
      qs("[data-auth-code-wrap]").hidden = false;
      if (data.dev_code) {
        err.hidden = false;
        err.textContent = `Код (dev): ${data.dev_code}`;
      } else {
        err.hidden = false;
        err.textContent = "Код отправлен на email";
      }
      return;
    }
    const { res, data } = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      err.hidden = false;
      err.textContent = data.error === "invalid" ? "Неверный email или пароль" : "Не удалось войти";
      return;
    }
    qs("[data-auth-dialog]").close();
    await loadUser();
  });
  qs("[data-auth-cancel]").addEventListener("click", () => qs("[data-auth-dialog]").close());
}

async function showMyWorks() {
  if (!currentUser) return openAuth();
  showThread();
  appendBubble("assistant", "Загружаю ваши работы…");
  const { data } = await api("/api/works/mine");
  const items = data.items || [];
  if (!items.length) {
    appendBubble("assistant", "Пока нет работ. Создайте что-нибудь в чате.");
    return;
  }
  items.slice(0, 12).forEach((w) => {
    const card = appendJobCard({
      title: w.title || w.model_key,
      status: w.status,
      priceKop: null,
    });
    card.dataset.workId = w.id;
    if (w.media_url || w.thumb_url) {
      finishJobCard(card, w.job_id || "", w.id, { work: w, job: { status: "succeeded", output: w.media_url } });
    }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  await ensureCsrf();
  wire();
  await loadUser();
  await loadModels();
  const params = new URLSearchParams(location.search);
  if (params.get("prompt")) {
    qs("[data-input]").value = params.get("prompt");
    autoSize(qs("[data-input]"));
  }
  if (params.get("model")) {
    const m = models.find((x) => x.model_key === params.get("model"));
    if (m) selectModel(m);
  }
  if (params.get("models") === "1") openModels();
  if (params.get("prompt") && !params.get("models")) {
    // auto-ask assistant with landing prompt
    setTimeout(() => sendMessage(), 200);
  }
});
