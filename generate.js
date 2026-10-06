// @ts-nocheck

let selectedAssistantId = "assistant";
let selectedGenerateModelId = null;
let uploadedFile = null;
let uploadedDataUrl = null;
let uploadedMediaKind = null; // "image" | "audio" | "video"
let slotImageUrl = null;
let slotVideoUrl = null;
let slotVideoName = null;
let chatHistory = [];
let isSending = false;
let integratedModels = [];
let filterQuery = "";
let filterInput = "";
let filterOutput = "";

const GEN_ARCHIVE_KEY = "generateArchive_v1";
const GEN_ARCHIVE_MAX = 80;
const DEFAULT_ASSISTANT_ID = "assistant";

const MODALITY_LABELS = {
  text: "текст",
  image: "картинка",
  video: "видео",
  audio: "аудио",
  music: "музыка",
};

const GROUP_LABELS = {
  assistants: "Ассистенты",
  generative: "Генеративные",
  image: "Изображения",
  video: "Видео",
  audio: "Аудио",
};

const PROVIDER_LABELS = {
  replicate: "",
  fal: "",
  omniroute: "",
  groq: "",
};

function publicModelName(name) {
  return String(name || "")
    .replace(/^Ассистент\s*[·•\-—]\s*/i, "")
    .replace(/\bOmniRoute\b/gi, "")
    .replace(/\bReplicate\b/gi, "")
    .replace(/\bfal(?:\.ai)?\b/gi, "")
    .replace(/\s*[·•\-—]\s*$/g, "")
    .replace(/^\s*[·•\-—]\s*/g, "")
    .replace(/\s{2,}/g, " ")
    .trim() || "Ассистент";
}

async function ensureCsrf() {
  if (window.__csrfToken) return window.__csrfToken;
  const match = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
  if (match) {
    window.__csrfToken = decodeURIComponent(match[1]);
    return window.__csrfToken;
  }
  const res = await fetch("/api/csrf", { credentials: "same-origin" });
  const data = await res.json().catch(() => ({}));
  window.__csrfToken = data.csrf_token || "";
  return window.__csrfToken;
}

async function csrfHeaders(extra = {}) {
  return {
    "Content-Type": "application/json",
    "X-CSRF-Token": await ensureCsrf(),
    ...extra,
  };
}

document.addEventListener("DOMContentLoaded", () => {
  restorePanelState();
  loadIntegrations();
  renderGenerationsList();
  setInterval(() => {
    if (!isSending) loadIntegrations({ quiet: true });
  }, 30000);
  initializeEventListeners();
  fillPromptFromQuery();
});

function fillPromptFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const query = (params.get("q") || "").trim();
  if (!query) return;

  const bottomPromptInput = document.getElementById("bottom-prompt-input");
  if (bottomPromptInput) {
    bottomPromptInput.value = query;
    bottomPromptInput.style.height = "auto";
    bottomPromptInput.style.height = Math.min(bottomPromptInput.scrollHeight, 120) + "px";
  }

  setTimeout(() => {
    handleSendMessage();
  }, 250);
}

function isAssistantSpec(model) {
  if (!model) return false;
  return model.group === "assistants" || model.kind === "chat" || model.kind === "llm" || model.is_assistant;
}

function findModel(id) {
  return integratedModels.find((m) => m.id === id) || null;
}

function currentAssistant() {
  return (
    findModel(selectedAssistantId) ||
    findModel(DEFAULT_ASSISTANT_ID) || {
      id: "assistant",
      name: "Ассистент",
      provider: "omniroute",
      kind: "chat",
      group: "assistants",
    }
  );
}

function currentGenerateModel() {
  if (!selectedGenerateModelId) return null;
  const model = findModel(selectedGenerateModelId);
  if (!model) return null;
  return model;
}

/** @deprecated use currentGenerateModel / currentAssistant */
function currentModel() {
  return currentGenerateModel() || currentAssistant();
}

async function loadIntegrations(opts = {}) {
  const quiet = Boolean(opts.quiet);
  try {
    const response = await fetch("/api/integrations", { credentials: "same-origin" });
    const data = await response.json().catch(() => ({}));
    integratedModels = data.items || [];
  } catch (error) {
    if (!quiet) console.error("Ошибка загрузки интеграций:", error);
    if (!integratedModels.length) {
      integratedModels = [
        {
          id: "assistant",
          name: "Ассистент",
          provider: "omniroute",
          kind: "chat",
          group: "assistants",
          inputs: ["text"],
          outputs: ["text"],
          price: "Бесплатно",
        },
      ];
    }
  }

  integratedModels = integratedModels.map((m) => ({
    ...m,
    name: publicModelName(m.name || m.id),
    notes: /\b(omniroute|replicate|fal(?:\.ai)?)\b/i.test(String(m.notes || ""))
      ? ""
      : (m.notes || ""),
  }));

  // Keep default chat assistant unless user picks another LLM
  if (!selectedAssistantId || !findModel(selectedAssistantId)) {
    selectedAssistantId = DEFAULT_ASSISTANT_ID;
  }

  const savedGenerate = localStorage.getItem("selectedGenerateModelId");
  const legacy = localStorage.getItem("selectedIntegrationId");
  const savedAssistant = localStorage.getItem("selectedAssistantId");

  if (savedAssistant && findModel(savedAssistant)) {
    selectedAssistantId = savedAssistant;
  }

  if (savedGenerate && findModel(savedGenerate)) {
    selectedGenerateModelId = savedGenerate;
  } else if (legacy && findModel(legacy)) {
    selectedGenerateModelId = legacy;
  } else if (selectedGenerateModelId && !findModel(selectedGenerateModelId)) {
    selectedGenerateModelId = null;
  }

  if (selectedGenerateModelId) {
    localStorage.setItem("selectedGenerateModelId", selectedGenerateModelId);
  }

  renderModelsList();
  updateSelectedModelBar();
}

function modalityLabel(mod) {
  return MODALITY_LABELS[mod] || mod;
}

function filteredModels() {
  const q = filterQuery.trim().toLowerCase();
  return integratedModels.filter((model) => {
    const inputs = model.inputs || [];
    const outputs = model.outputs || [];
    if (filterInput && !inputs.includes(filterInput)) return false;
    if (filterOutput && !outputs.includes(filterOutput)) return false;
    if (!q) return true;
    const hay = [
      model.name,
      model.id,
      model.provider,
      model.kind,
      model.group,
      model.price,
      ...(inputs || []),
      ...(outputs || []),
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });
}

function renderModelsList() {
  const list = document.getElementById("models-list");
  if (!list) return;

  const models = filteredModels();
  if (!models.length) {
    list.innerHTML = `<div class="models-empty">Нет моделей по фильтру</div>`;
    return;
  }

  const order = ["assistants", "generative", "image", "video", "audio"];
  const byGroup = {};
  for (const model of models) {
    const g = model.group || model.kind || "other";
    if (!byGroup[g]) byGroup[g] = [];
    byGroup[g].push(model);
  }
  const groups = [...order.filter((g) => byGroup[g]), ...Object.keys(byGroup).filter((g) => !order.includes(g))];

  const parts = [];
  for (const g of groups) {
    parts.push(`<div class="models-group-label">${escapeHtml(GROUP_LABELS[g] || g)}</div>`);
    for (const model of byGroup[g]) {
      const notes = (model.notes || "").trim();
      const notesLine = notes
        ? `<p class="model-item-provider">${escapeHtml(notes)}</p>`
        : "";
      const outputs = model.outputs || [];
      const typeChips = outputs
        .map((o) => `<span class="model-chip model-chip--type">${escapeHtml(modalityLabel(o))}</span>`)
        .join("");
      const price = (model.price || "").trim();
      const priceChip = price
        ? `<span class="model-chip model-chip--price" title="${escapeHtml(model.price_full || price)}">${escapeHtml(price)}</span>`
        : `<span class="model-chip model-chip--price is-empty">цена н/д</span>`;
      const selected = model.id === selectedGenerateModelId ? " selected" : "";
      const ariaSelected = model.id === selectedGenerateModelId ? "true" : "false";
      parts.push(`
        <button type="button" class="model-item${selected}" role="option" aria-selected="${ariaSelected}" data-model-id="${escapeHtml(model.id)}">
          <div class="model-item-info">
            <h4>${escapeHtml(model.name)}</h4>
            ${notesLine}
            <div class="model-meta-row">${typeChips}${priceChip}</div>
          </div>
        </button>
      `);
    }
  }
  list.innerHTML = parts.join("");
}

function selectModel(modelId) {
  const model = findModel(modelId);
  if (!model) return;
  selectedGenerateModelId = modelId;
  if (isAssistantSpec(model)) {
    selectedAssistantId = modelId;
    localStorage.setItem("selectedAssistantId", selectedAssistantId);
  }
  localStorage.setItem("selectedGenerateModelId", selectedGenerateModelId);
  localStorage.setItem("selectedIntegrationId", selectedGenerateModelId);
  updateSelectedModelBar();
  renderModelsList();
  closeModelsDrawer();
}

function updateSelectedModelBar() {
  const assistantEl = document.getElementById("selected-assistant-name");
  const modelEl = document.getElementById("selected-model-name");
  const gen = currentGenerateModel();
  const asst = currentAssistant();
  if (assistantEl) {
    assistantEl.textContent = isAssistantSpec(gen)
      ? (gen.name || gen.id)
      : (asst ? (asst.name || asst.id) : "Ассистент");
  }
  if (modelEl) {
    modelEl.textContent = gen && !isAssistantSpec(gen) ? (gen.name || gen.id) : (gen && isAssistantSpec(gen) ? "текст" : "не выбрана");
  }
}

function setSideTab(tab) {
  const next = tab === "gens" ? "gens" : "models";
  const page = document.getElementById("chat-page");
  if (page) page.setAttribute("data-side-tab", next);

  document.querySelectorAll(".side-tab").forEach((btn) => {
    const active = btn.getAttribute("data-side-tab") === next;
    btn.classList.toggle("is-active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });

  const modelsPanel = document.getElementById("panel-models");
  const gensPanel = document.getElementById("panel-gens");
  if (modelsPanel) modelsPanel.hidden = next !== "models";
  if (gensPanel) gensPanel.hidden = next !== "gens";
  localStorage.setItem("sideTab", next);
}

function openSidePanel(tab) {
  const page = document.getElementById("chat-page");
  if (!page) return;
  if (tab) setSideTab(tab);
  if (window.matchMedia("(max-width: 768px)").matches) {
    page.classList.add("side-open");
    const backdrop = document.getElementById("side-backdrop");
    if (backdrop) backdrop.hidden = false;
  } else {
    page.classList.remove("side-collapsed");
    localStorage.setItem("sideCollapsed", "0");
  }
}

function closeSidePanel() {
  const page = document.getElementById("chat-page");
  if (!page) return;
  page.classList.remove("side-open");
  const backdrop = document.getElementById("side-backdrop");
  if (backdrop) backdrop.hidden = true;
}

function openModelsDrawer() {
  openSidePanel("models");
}

function closeModelsDrawer() {
  if (window.matchMedia("(max-width: 768px)").matches) closeSidePanel();
}

function openHistoryDrawer() {
  openSidePanel("gens");
}

function closeHistoryDrawer() {
  if (window.matchMedia("(max-width: 768px)").matches) closeSidePanel();
}

function restorePanelState() {
  const page = document.getElementById("chat-page");
  if (!page) return;
  const savedTab = localStorage.getItem("sideTab");
  setSideTab(savedTab === "gens" ? "gens" : "models");
  if (window.matchMedia("(max-width: 768px)").matches) return;
  if (localStorage.getItem("sideCollapsed") === "1") page.classList.add("side-collapsed");
}

function collapseSidePanel() {
  const page = document.getElementById("chat-page");
  if (!page) return;
  if (window.matchMedia("(max-width: 768px)").matches) {
    closeSidePanel();
    return;
  }
  page.classList.add("side-collapsed");
  localStorage.setItem("sideCollapsed", "1");
}

function collapseHistory() {
  collapseSidePanel();
}

function collapseModels() {
  collapseSidePanel();
}

function isHttpUrl(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url);
}

function loadGenerations() {
  try {
    const raw = localStorage.getItem(GEN_ARCHIVE_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.filter((g) => g && isHttpUrl(g.url)) : [];
  } catch {
    return [];
  }
}

function saveGenerations(list) {
  try {
    localStorage.setItem(GEN_ARCHIVE_KEY, JSON.stringify(list.slice(0, GEN_ARCHIVE_MAX)));
  } catch (err) {
    console.warn("generate archive save failed", err);
  }
}

function archiveGeneration({ kind, url, modelId, modelName, prompt }) {
  if (!isHttpUrl(url)) return;
  const item = {
    id: `g_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    kind,
    url,
    modelId: modelId || "",
    modelName: modelName || modelId || "модель",
    prompt: String(prompt || "").slice(0, 160),
    createdAt: Date.now(),
  };
  const next = [item, ...loadGenerations().filter((g) => g.url !== url)].slice(0, GEN_ARCHIVE_MAX);
  saveGenerations(next);
  renderGenerationsList();
}

function formatGenTime(ts) {
  try {
    return new Date(ts).toLocaleString("ru-RU", {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

function renderGenerationsList() {
  const list = document.getElementById("history-list");
  if (!list) return;
  const items = loadGenerations();
  if (!items.length) {
    list.innerHTML = `<div class="history-empty">Пока нет сохранённых генераций.<br/>Результаты image/video/audio появятся здесь.</div>`;
    return;
  }
  list.innerHTML = items
    .map((g) => {
      const kindLabel = modalityLabel(g.kind === "audio" ? "audio" : g.kind) || g.kind;
      const thumb =
        g.kind === "image"
          ? `<span class="gen-thumb"><img src="${escapeHtml(g.url)}" alt="" loading="lazy"></span>`
          : `<span class="gen-thumb">${escapeHtml((kindLabel || "?").slice(0, 3))}</span>`;
      return `
        <button type="button" class="gen-item" data-gen-id="${escapeHtml(g.id)}" role="listitem">
          ${thumb}
          <span class="gen-meta">
            <strong>${escapeHtml(g.modelName)}</strong>
            <span>${escapeHtml(kindLabel)} · ${escapeHtml(formatGenTime(g.createdAt))}</span>
          </span>
        </button>`;
    })
    .join("");
}

function showGenerationInChat(genId) {
  const item = loadGenerations().find((g) => g.id === genId);
  if (!item) return;
  addMessage(
    "assistant",
    `Сохранённая генерация · ${item.modelName}${item.prompt ? `\n${item.prompt}` : ""}`,
    { kind: item.kind, url: item.url }
  );
  closeHistoryDrawer();
}

function startNewChat() {
  chatHistory = [];
  clearUploadedMedia();
  const chatMessages = document.getElementById("chat-messages");
  if (chatMessages) {
    chatMessages.innerHTML = `
      <div class="welcome-message">
        <h2>Добро пожаловать в {AI}-шницу! 🫶</h2>
        <p>Новый чат в этой вкладке. История диалога не сохраняется — только генерации слева.</p>
      </div>`;
  }
  closeHistoryDrawer();
}

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Insert structure into wall-of-text replies (models often omit newlines). */
function normalizeAssistantText(src) {
  let t = String(src || "").replace(/\r\n/g, "\n").trim();
  if (!t) return "";

  // Numbered model blocks: "1) Name" / "1. Name"
  t = t.replace(/(?:^|[ \t]+)(\d{1,2})\s*[.)]\s+(?=\S)/g, "\n\n### $1. ");

  // Markdown headings jammed mid-line
  t = t.replace(/\s+(#{1,3}\s+)/g, "\n\n$1");

  // Field labels with optional markdown bold
  t = t.replace(
    /\s*\*{0,2}(Исходники|Цена|Качество|Канал|Провайдер)\*{0,2}\s*:\s*/gi,
    "\n- **$1:** "
  );

  // Common section titles
  t = t.replace(
    /\s*(?:🏆\s*|✍️\s*|⚙️\s*|➡️\s*)?(Мой вердикт|Вердикт|Готовый промпт|Параметры запуска|Следующий шаг)\s*:?\s*/gi,
    "\n\n## $1\n\n"
  );

  // Bullet markers jammed mid-line
  t = t.replace(/\s+[•·]\s+/g, "\n- ");
  t = t.replace(/\s+-\s+\*\*/g, "\n- **");

  // Soft paragraph breaks before recommendation closers
  t = t.replace(/\.\s+(Если |Для |Рекомендую |Выбирайте |Отлично[,!]|Давайте )/g, ".\n\n$1");

  return t.replace(/\n{3,}/g, "\n\n").trim();
}

/** Safe subset markdown → HTML (headers, lists, bold, paragraphs, hr, code). */
function renderMarkdownSafe(src) {
  const text = normalizeAssistantText(src);
  if (!text) return "";

  const escapeInline = (s) =>
    escapeHtml(s)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*]+)\*(?!\*)/g, "$1<em>$2</em>");

  const lines = text.split("\n");
  const html = [];
  let i = 0;
  let para = [];
  let listType = null; // "ul" | "ol"
  let listItems = [];

  const flushPara = () => {
    if (!para.length) return;
    html.push(`<p>${escapeInline(para.join(" ").trim())}</p>`);
    para = [];
  };

  const flushList = () => {
    if (!listType || !listItems.length) {
      listType = null;
      listItems = [];
      return;
    }
    const tag = listType;
    html.push(`<${tag}>${listItems.map((li) => `<li>${escapeInline(li)}</li>`).join("")}</${tag}>`);
    listType = null;
    listItems = [];
  };

  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.trimEnd();
    const trimmed = line.trim();

    if (!trimmed) {
      flushPara();
      flushList();
      i += 1;
      continue;
    }

    if (/^---+$/.test(trimmed) || /^\*\*\*+$/.test(trimmed)) {
      flushPara();
      flushList();
      html.push("<hr>");
      i += 1;
      continue;
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushPara();
      flushList();
      const level = heading[1].length;
      html.push(`<h${level}>${escapeInline(heading[2])}</h${level}>`);
      i += 1;
      continue;
    }

    // "### 1. Seedance..." already handled; also plain "### title"
    const ul = trimmed.match(/^[-*•]\s+(.+)$/);
    if (ul) {
      flushPara();
      if (listType && listType !== "ul") flushList();
      listType = "ul";
      listItems.push(ul[1]);
      i += 1;
      continue;
    }

    const ol = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (ol) {
      flushPara();
      if (listType && listType !== "ol") flushList();
      listType = "ol";
      listItems.push(ol[1]);
      i += 1;
      continue;
    }

    flushList();
    para.push(trimmed);
    i += 1;
  }

  flushPara();
  flushList();
  return html.join("");
}

function formatMessageHtml(sender, content) {
  if (sender === "assistant") {
    return renderMarkdownSafe(content) || `<p>${escapeHtml(content)}</p>`;
  }
  return escapeHtml(content).replace(/\n/g, "<br>");
}

function addMessage(sender, content, media = null) {
  const chatMessages = document.getElementById("chat-messages");
  if (!chatMessages) return;

  const welcomeMessage = chatMessages.querySelector(".welcome-message");
  if (welcomeMessage) welcomeMessage.remove();

  const messageDiv = document.createElement("div");
  messageDiv.className = `message ${sender}`;

  const avatar = sender === "user" ? "U" : "AI";
  let mediaHtml = "";
  if (media?.kind === "image" && media.url) {
    mediaHtml = `
      <div class="message-image">
        <img src="${escapeHtml(media.url)}" alt="Сгенерированное изображение">
      </div>
    `;
  } else if (media?.kind === "video" && media.url) {
    mediaHtml = `
      <div class="message-image">
        <video src="${escapeHtml(media.url)}" controls playsinline style="max-width:100%;border-radius:12px;"></video>
      </div>
    `;
  } else if (media?.kind === "audio" && media.url) {
    mediaHtml = `
      <div class="message-image">
        <audio src="${escapeHtml(media.url)}" controls style="width:100%;max-width:420px;"></audio>
      </div>
    `;
  }

  messageDiv.innerHTML = `
    <div class="message-avatar">${avatar}</div>
    <div class="message-content">
      <div class="message-text">${formatMessageHtml(sender, content)}</div>
      ${mediaHtml}
    </div>
  `;

  chatMessages.appendChild(messageDiv);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function initializeEventListeners() {
  const fileInput = document.getElementById("image-upload");
  const attachBtn = document.getElementById("attach-btn");
  const removeImage = document.getElementById("remove-image");
  const bottomPromptInput = document.getElementById("bottom-prompt-input");
  const sendBtn = document.getElementById("send-btn");
  const search = document.getElementById("model-search");
  const filterIn = document.getElementById("filter-input");
  const filterOut = document.getElementById("filter-output");
  const list = document.getElementById("models-list");
  const toggleBtn = document.getElementById("models-toggle-btn");
  const closeBtn = document.getElementById("side-close-btn");
  const backdrop = document.getElementById("side-backdrop");
  const sideCollapse = document.getElementById("side-collapse-btn");
  const sideReopen = document.getElementById("side-reopen-btn");
  const historyList = document.getElementById("history-list");
  const tabModels = document.getElementById("tab-models");
  const tabGens = document.getElementById("tab-gens");

  if (attachBtn && fileInput) {
    attachBtn.addEventListener("click", () => fileInput.click());
  }

  if (fileInput) {
    fileInput.addEventListener("change", (e) => {
      if (e.target.files.length > 0) handleFileUpload(e.target.files[0]);
    });
  }

  if (removeImage) {
    removeImage.addEventListener("click", () => {
      clearUploadedMedia();
    });
  }

  if (bottomPromptInput) {
    bottomPromptInput.addEventListener("input", (e) => {
      e.target.style.height = "auto";
      e.target.style.height = Math.min(e.target.scrollHeight, 120) + "px";
    });

    bottomPromptInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSendMessage();
      }
    });
  }

  if (sendBtn) sendBtn.addEventListener("click", handleSendMessage);

  if (search) {
    search.addEventListener("input", () => {
      filterQuery = search.value || "";
      renderModelsList();
    });
  }
  if (filterIn) {
    filterIn.addEventListener("change", () => {
      filterInput = filterIn.value || "";
      renderModelsList();
    });
  }
  if (filterOut) {
    filterOut.addEventListener("change", () => {
      filterOutput = filterOut.value || "";
      renderModelsList();
    });
  }
  if (list) {
    list.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-model-id]");
      if (!btn) return;
      selectModel(btn.getAttribute("data-model-id"));
    });
  }
  if (toggleBtn) toggleBtn.addEventListener("click", () => openSidePanel("models"));
  if (closeBtn) closeBtn.addEventListener("click", closeSidePanel);
  if (backdrop) {
    backdrop.addEventListener("click", closeSidePanel);
  }
  if (sideCollapse) sideCollapse.addEventListener("click", collapseSidePanel);
  if (sideReopen) sideReopen.addEventListener("click", () => openSidePanel());
  if (tabModels) tabModels.addEventListener("click", () => openSidePanel("models"));
  if (tabGens) tabGens.addEventListener("click", () => openSidePanel("gens"));
  if (historyList) {
    historyList.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-gen-id]");
      if (!btn) return;
      showGenerationInChat(btn.getAttribute("data-gen-id"));
    });
  }
}

function clearUploadedMedia() {
  uploadedFile = null;
  uploadedDataUrl = null;
  uploadedMediaKind = null;
  slotImageUrl = null;
  slotVideoUrl = null;
  slotVideoName = null;
  const fileInput = document.getElementById("image-upload");
  const uploadedImage = document.getElementById("uploaded-image");
  const previewImage = document.getElementById("preview-image");
  const previewLabel = document.getElementById("preview-label");
  if (fileInput) fileInput.value = "";
  if (previewImage) {
    previewImage.src = "";
    previewImage.style.display = "none";
  }
  if (previewLabel) {
    previewLabel.textContent = "";
    previewLabel.style.display = "none";
  }
  if (uploadedImage) uploadedImage.style.display = "none";
}

function updateMediaPreview() {
  const previewImage = document.getElementById("preview-image");
  const previewLabel = document.getElementById("preview-label");
  const uploadedImage = document.getElementById("uploaded-image");
  const hasAny = !!(slotImageUrl || slotVideoUrl || uploadedDataUrl);
  if (!hasAny) {
    if (uploadedImage) uploadedImage.style.display = "none";
    return;
  }
  if (slotImageUrl && previewImage) {
    previewImage.src = slotImageUrl;
    previewImage.style.display = "block";
  } else if (uploadedMediaKind === "image" && uploadedDataUrl && previewImage) {
    previewImage.src = uploadedDataUrl;
    previewImage.style.display = "block";
  } else if (previewImage) {
    previewImage.src = "";
    previewImage.style.display = "none";
  }
  const labels = [];
  if (slotImageUrl) labels.push("картинка");
  if (slotVideoUrl) labels.push(slotVideoName ? `видео: ${slotVideoName}` : "видео");
  if (!slotImageUrl && !slotVideoUrl && uploadedFile) labels.push(uploadedFile.name);
  if (previewLabel) {
    if (labels.length) {
      previewLabel.textContent = labels.join(" + ");
      previewLabel.style.display = "block";
    } else {
      previewLabel.textContent = "";
      previewLabel.style.display = "none";
    }
  }
  if (uploadedImage) uploadedImage.style.display = "block";
}

function handleFileUpload(file) {
  const type = file.type || "";
  const isImage = type.startsWith("image/");
  const isAudio = type.startsWith("audio/");
  const isVideo = type.startsWith("video/");
  if (!isImage && !isAudio && !isVideo) {
    addMessage("assistant", "Прикрепите изображение, аудио или видео");
    return;
  }

  uploadedFile = file;
  uploadedMediaKind = isImage ? "image" : isAudio ? "audio" : "video";
  const reader = new FileReader();
  reader.onload = (e) => {
    uploadedDataUrl = e.target.result;
    if (isImage) slotImageUrl = uploadedDataUrl;
    if (isVideo) {
      slotVideoUrl = uploadedDataUrl;
      slotVideoName = file.name;
    }
    if (isAudio) {
      slotImageUrl = null;
      slotVideoUrl = null;
      slotVideoName = null;
    }
    updateMediaPreview();
  };
  reader.readAsDataURL(file);
}

function looksLikeAdviceOnly(text) {
  const t = String(text || "").trim();
  if (!t) return false;
  return /помоги выбрать|посовет|сравни модели|какую модель|какой модель|что лучше|recommend|help me choose|подскажи модель/i.test(
    t
  );
}

function mediaFlags(model) {
  const imageRequired = Boolean(model && (model.notes || "").includes("image required"));
  const audioRequired = Boolean(model && (model.notes || "").includes("audio required"));
  const imageVideoRequired = Boolean(model && (model.notes || "").includes("image+video required"));
  const hasImage = !!(slotImageUrl || (uploadedMediaKind === "image" && uploadedDataUrl));
  const hasAudio =
    (uploadedMediaKind === "audio" || uploadedMediaKind === "video") && !!uploadedDataUrl;
  const hasDrivingVideo = !!slotVideoUrl;
  const imageOnlyOk =
    Boolean(model) &&
    (model.id === "pasd-magnify" || model.id === "wan-3-0-i2v-fal") &&
    hasImage;
  const imageVideoOk = imageVideoRequired && hasImage && hasDrivingVideo;
  const sttWithAudio = Boolean(model && model.kind === "stt" && uploadedDataUrl);
  return {
    imageRequired,
    audioRequired,
    imageVideoRequired,
    hasImage,
    hasAudio,
    hasDrivingVideo,
    imageOnlyOk,
    imageVideoOk,
    sttWithAudio,
  };
}

function loadingTextForModel(model) {
  if (!model) return "Думаю над ответом...";
  if (model.kind === "image") {
    return model.id === "pasd-magnify" ? "Увеличиваю изображение..." : "Генерирую изображение...";
  }
  if (model.kind === "video") return "Генерирую видео (может занять минуту)...";
  if (model.kind === "audio") {
    if (
      model.id === "elevenlabs-music" ||
      model.id === "lyria-2" ||
      model.id === "minimax-music-01" ||
      model.id === "ace-step" ||
      model.id === "flux-music" ||
      model.id === "minimax-music-2-5"
    ) {
      return "Генерирую музыку...";
    }
    return "Синтезирую речь...";
  }
  if (model.kind === "stt") return "Транскрибирую аудио...";
  return "Думаю над ответом...";
}

async function handleSendMessage() {
  const bottomPromptInput = document.getElementById("bottom-prompt-input");
  const prompt = bottomPromptInput?.value.trim();
  const genModel = currentGenerateModel();
  const media = mediaFlags(genModel);
  const a2vOk = media.audioRequired && media.hasAudio && (!!prompt || media.hasImage);

  if (isSending) return;

  if (genModel && !looksLikeAdviceOnly(prompt || "")) {
    if (genModel.kind === "stt" && !uploadedDataUrl) {
      addMessage("assistant", "Для транскрипции прикрепите аудио или видеофайл.");
      return;
    }
    if (media.imageVideoRequired) {
      if (!media.hasImage) {
        addMessage("assistant", "Для DreamActor прикрепите изображение персонажа.");
        return;
      }
      if (!media.hasDrivingVideo) {
        addMessage("assistant", "Для DreamActor прикрепите driving-видео (движение).");
        return;
      }
    }
    if (genModel.id === "minimax-music-01" && uploadedDataUrl && uploadedMediaKind !== "audio") {
      addMessage("assistant", "Для Music-01 нужен именно аудиофайл (.mp3/.wav), не видео.");
      return;
    }
  }

  if (!prompt && !media.sttWithAudio && !media.imageOnlyOk && !a2vOk && !media.imageVideoOk) return;
  isSending = true;

  const userText =
    prompt ||
    (media.imageVideoOk
      ? "[картинка+видео]"
      : uploadedFile
        ? `[файл] ${uploadedFile.name}`
        : "[аудио]");
  addMessage("user", userText);
  chatHistory.push({ role: "user", content: userText });

  if (bottomPromptInput) {
    bottomPromptInput.value = "";
    bottomPromptInput.style.height = "auto";
  }

  addMessage("assistant", "Думаю над ответом...");

  try {
    const chatResult = await sendChat();
    if (!chatResult) return;

    let generatePrompt = chatResult.generate_prompt || null;
    if (!generatePrompt && genModel && !looksLikeAdviceOnly(userText)) {
      if (/^(сгенерируй|генерируй|сделай|нарисуй|создай|запусти|generate|make|create)\b/i.test(userText)) {
        generatePrompt = userText;
      }
    }

    if (genModel && generatePrompt) {
      if (media.imageRequired && !media.imageVideoRequired && !media.hasImage) {
        addMessage("assistant", "Для запуска этой модели прикрепите изображение.");
        return;
      }
      if (media.audioRequired && !media.hasAudio) {
        addMessage(
          "assistant",
          genModel.id === "minimax-music-01"
            ? "Для Music-01 прикрепите референс-трек (.mp3/.wav, дольше 15с)."
            : "Для запуска этой модели прикрепите аудиофайл."
        );
        return;
      }

      addMessage("assistant", loadingTextForModel(genModel));
      const genOk = await sendReplicateGenerate(genModel, generatePrompt);
      if (genOk) {
        addMessage("assistant", "Думаю над ответом...");
        await sendChat({
          messages: [
            ...chatHistory,
            {
              role: "user",
              content:
                "Результат генерации уже показан в чате. Кратко (2–3 предложения) подтверди успех, " +
                `напомни модель «${genModel.name}», и предложи один следующий шаг. Без GENERATE_NOW.`,
            },
          ],
        });
      }
    }
  } catch (error) {
    console.error("Ошибка при отправке запроса:", error);
    removeLoadingMessage();
    addMessage("assistant", "Произошла ошибка при обработке запроса. Попробуйте ещё раз.");
  } finally {
    isSending = false;
  }
}

async function sendChat(opts = {}) {
  const messages = opts.messages || chatHistory;
  const gen = currentGenerateModel();
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: await csrfHeaders(),
    credentials: "same-origin",
    body: JSON.stringify({
      messages,
      assistant_id: selectedAssistantId,
      selected_model_id: gen?.id || null,
      selected_model_name: gen?.name || null,
    }),
  });

  const data = await response.json().catch(() => ({}));
  removeLoadingMessage();

  if (!response.ok) {
    let hint = "Не удалось получить ответ. Попробуйте ещё раз.";
    if (data.error === "not_configured") {
      hint = "Чат временно недоступен. Попробуйте позже.";
    } else if (data.status === 401 || data.status === 403) {
      hint = "Чат временно недоступен. Попробуйте позже.";
    } else if (data.detail) {
      hint = "Не удалось получить ответ. Попробуйте ещё раз.";
    }
    addMessage("assistant", hint);
    return null;
  }

  const reply = (data.reply || "").trim() || "Пустой ответ от модели.";
  addMessage("assistant", reply);
  chatHistory.push({ role: "assistant", content: reply });
  return data;
}

async function sendReplicateGenerate(model, overridePrompt) {
  const lastUser = chatHistory.filter((m) => m.role === "user").slice(-1)[0]?.content || "";
  const promptForApi =
    overridePrompt != null && String(overridePrompt).trim()
      ? String(overridePrompt).trim()
      : (model.kind === "stt" ||
            model.id === "pasd-magnify" ||
            model.id === "wan-3-0-i2v-fal" ||
            model.id === "ltx-2-3-a2v-fal" ||
            model.id === "dreamactor-m2") &&
          (lastUser.startsWith("[файл]") || lastUser.startsWith("[картинка"))
        ? ""
        : lastUser.startsWith("[аудио]")
          ? ""
          : lastUser;

  const response = await fetch("/api/generate", {
    method: "POST",
    headers: await csrfHeaders(),
    credentials: "same-origin",
    body: JSON.stringify({
      model: model.id,
      prompt: promptForApi,
      image:
        slotImageUrl ||
        (uploadedMediaKind === "image" ? uploadedDataUrl : null),
      video: slotVideoUrl || null,
      audio:
        uploadedMediaKind === "audio" ||
        (uploadedMediaKind === "video" && model.id !== "dreamactor-m2")
          ? uploadedDataUrl
          : null,
    }),
  });

  const data = await response.json().catch(() => ({}));
  removeLoadingMessage();

  if (!response.ok) {
    let hint = "Не удалось выполнить генерацию.";
    if (data.error === "not_configured") {
      hint = "Генерация временно недоступна. Попробуйте позже.";
    } else if (data.error === "channel_unavailable") {
      hint = "Модель сейчас недоступна. Выберите другую или попробуйте позже.";
    } else if (data.error === "queue_unavailable") {
      hint = "Очередь генерации недоступна. Попробуйте позже.";
    } else if (data.detail) {
      hint = "Не удалось выполнить генерацию. Попробуйте ещё раз.";
    }
    addMessage("assistant", hint);
    return false;
  }

  if (data.kind === "text") {
    const reply = (data.reply || "").trim() || "Пустой ответ.";
    addMessage("assistant", reply);
    chatHistory.push({ role: "assistant", content: reply });
    return true;
  }

  const url = (data.urls && data.urls[0]) || null;
  const reply = (data.reply || "").trim() || "Готово.";
  if (data.kind === "image") {
    addMessage("assistant", reply, url ? { kind: "image", url } : null);
    chatHistory.push({ role: "assistant", content: `${reply}${url ? ` ${url}` : ""}` });
    if (url) {
      archiveGeneration({
        kind: "image",
        url,
        modelId: model.id,
        modelName: model.name,
        prompt: promptForApi,
      });
    }
    return true;
  }
  if (data.kind === "video") {
    addMessage("assistant", reply, url ? { kind: "video", url } : null);
    chatHistory.push({ role: "assistant", content: `${reply}${url ? ` ${url}` : ""}` });
    if (url) {
      archiveGeneration({
        kind: "video",
        url,
        modelId: model.id,
        modelName: model.name,
        prompt: promptForApi,
      });
    }
    return true;
  }
  if (data.kind === "audio") {
    addMessage("assistant", reply, url ? { kind: "audio", url } : null);
    chatHistory.push({ role: "assistant", content: `${reply}${url ? ` ${url}` : ""}` });
    if (url) {
      archiveGeneration({
        kind: "audio",
        url,
        modelId: model.id,
        modelName: model.name,
        prompt: promptForApi,
      });
    }
    return true;
  }

  addMessage("assistant", reply);
  chatHistory.push({ role: "assistant", content: reply });
  return true;
}

function removeLoadingMessage() {
  const chatMessages = document.getElementById("chat-messages");
  const lastMessage = chatMessages?.lastElementChild;
  const text = lastMessage?.querySelector(".message-text")?.textContent || "";
  if (
    lastMessage &&
    (text === "Думаю над ответом..." ||
      text === "Генерирую изображение..." ||
      text === "Увеличиваю изображение..." ||
      text === "Синтезирую речь..." ||
      text === "Генерирую музыку..." ||
      text === "Транскрибирую аудио..." ||
      text.startsWith("Генерирую видео"))
  ) {
    lastMessage.remove();
  }
}
