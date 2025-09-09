const API_BASE = "http://localhost:5000/api";

const state = {
  tags: [],
  activeTags: new Set(),
  query: "",
  page: 1,
  per_page: 12,
  total: 0,
  pages: 0,
};

function qs(sel, root = document) { return root.querySelector(sel); }
function qsa(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function getPlaceholder(model) {
  const t = (model.tags || []).map(s => s.toLowerCase());
  let label = "preview";
  if (t.includes("video-generation") || t.includes("text-to-video")) label = "video";
  else if (t.includes("music-generation") || t.includes("audio")) label = "music";
  else if (t.includes("image-generation") || t.includes("text-to-image")) label = "image";
  // dummy placeholder 800x533 (≈3:2)
  return `https://dummyimage.com/800x533/edf2f7/94a3b8&text=${encodeURIComponent(label)}`;
}

function createCard(model) {
  const article = document.createElement("article");
  article.className = "card";

  const media = document.createElement("div");
  media.className = "card-media";

  const img = document.createElement("img");
  img.src = model.image_url;
  img.alt = `${model.vendor}/${model.name}`;
  img.loading = "lazy";
  img.decoding = "async";
  img.sizes = "(max-width:560px) 100vw, (max-width:1100px) 50vw, 33vw";
  img.referrerPolicy = "no-referrer";
  img.onerror = () => {
    const ph = getPlaceholder(model);
    if (img.src !== ph) img.src = ph;
  };
  media.appendChild(img);

  const body = document.createElement("div");
  body.className = "card-body";

  body.innerHTML = `
    <h3 class="card-title"><span class="muted">${model.vendor}/</span><strong>${model.name}</strong></h3>
  `;

  const generic = (model.description || "").trim().toLowerCase() === "model from replicate";
  if (!generic && model.description) {
    const p = document.createElement("p");
    p.className = "card-desc";
    p.textContent = model.description;
    body.appendChild(p);
  }
  if (Array.isArray(model.tags) && model.tags.length) {
    const t = document.createElement("div");
    t.className = "card-tags";
    t.innerHTML = model.tags.map(tag => `<span class="hash">#${tag}</span>`).join(" ");
    body.appendChild(t);
  }

  article.appendChild(media);
  article.appendChild(body);
  return article;
}

function renderTags() {
  const wrap = qs(".filters .tags");
  wrap.innerHTML = "";
  state.tags.forEach(tag => {
    const btn = document.createElement("button");
    btn.className = "tag" + (state.activeTags.has(tag.name) ? " tag--active" : "");
    btn.textContent = tag.name;
    btn.addEventListener("click", () => {
      state.page = 1;
      if (state.activeTags.has(tag.name)) state.activeTags.delete(tag.name); else state.activeTags.add(tag.name);
      renderTags();
      loadModels();
    });
    wrap.appendChild(btn);
  });
}

function renderPager() {
  const container = qs(".catalog-content");
  let pager = qs(".pager");
  if (!pager) {
    pager = document.createElement("div");
    pager.className = "pager";
    container.appendChild(pager);
  }
  pager.innerHTML = "";
  const info = document.createElement("div");
  info.className = "pager-info";
  info.textContent = `${state.page}/${state.pages} · ${state.total} моделей`;
  const prev = document.createElement("button");
  prev.className = "pager-btn";
  prev.textContent = "‹ Пред";
  prev.disabled = state.page <= 1;
  prev.onclick = () => { state.page--; loadModels(); };
  const next = document.createElement("button");
  next.className = "pager-btn";
  next.textContent = "След ›";
  next.disabled = state.page >= state.pages;
  next.onclick = () => { state.page++; loadModels(); };
  pager.appendChild(prev);
  pager.appendChild(info);
  pager.appendChild(next);
}

async function loadTags() {
  state.tags = await fetchJSON(`${API_BASE}/tags`);
  renderTags();
}

async function loadModels() {
  const params = new URLSearchParams();
  if (state.query) params.set("q", state.query);
  if (state.activeTags.size) params.set("tags", Array.from(state.activeTags).join(","));
  params.set("page", String(state.page));
  params.set("per_page", String(state.per_page));
  const data = await fetchJSON(`${API_BASE}/models?${params.toString()}`);
  state.total = data.total; state.pages = data.pages; state.page = data.page;
  const grid = qs(".cards-grid");
  grid.innerHTML = "";
  data.items.forEach(m => grid.appendChild(createCard(m)));
  renderPager();
}

function wireSearch() {
  const form = qs(".search-bar");
  const input = qs(".search-input");
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    state.query = input.value.trim();
    state.page = 1;
    loadModels();
  });
  input.addEventListener("input", () => {
    state.query = input.value.trim();
  });
}

async function init() {
  wireSearch();
  await loadTags();
  await loadModels();
}

document.addEventListener("DOMContentLoaded", init);