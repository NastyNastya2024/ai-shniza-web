#!/usr/bin/env node

// Скрипт для генерации статической версии app.js с реальными данными

const fs = require('fs');

// Получаем данные с сервера
async function fetchData() {
  try {
    const modelsResponse = await fetch('http://127.0.0.1:5000/api/models?per_page=312');
    const modelsData = await modelsResponse.json();
    
    const tagsResponse = await fetch('http://127.0.0.1:5000/api/tags');
    const tagsData = await tagsResponse.json();
    
    return { models: modelsData.items, tags: tagsData };
  } catch (error) {
    console.error('Ошибка загрузки данных:', error);
    return { models: [], tags: [] };
  }
}

// Генерируем статический app.js
function generateStaticApp(models, tags) {
  const modelsJson = JSON.stringify(models, null, 2);
  const tagsJson = JSON.stringify(tags, null, 2);
  
  return `// Статическая версия для GitHub Pages
const state = {
  tags: ${tagsJson},
  activeTags: new Set(),
  query: "",
  page: 1,
  per_page: 12,
  total: 0,
  pages: 0,
  allModels: []
};

function qs(sel, root = document) { return root.querySelector(sel); }
function qsa(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

function getPlaceholder(model) {
  const t = (model.tags || []).map(s => s.toLowerCase());
  let label = "preview";
  if (t.includes("video-generation") || t.includes("text-to-video")) label = "video";
  else if (t.includes("music-generation") || t.includes("audio")) label = "music";
  else if (t.includes("image-generation") || t.includes("text-to-image")) label = "image";
  return "https://dummyimage.com/800x533/edf2f7/94a3b8&text=" + encodeURIComponent(label);
}

function createCard(model) {
  const article = document.createElement("article");
  article.className = "card";

  const media = document.createElement("div");
  media.className = "card-media";

  const img = document.createElement("img");
  img.src = model.image_url;
  img.alt = model.vendor + "/" + model.name;
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

  body.innerHTML = "<h3 class=\"card-title\"><span class=\"muted\">" + model.vendor + "/</span><strong>" + model.name + "</strong></h3>";

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
    t.innerHTML = model.tags.map(tag => "<span class=\"hash\">#" + tag + "</span>").join(" ");
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
  info.textContent = state.page + "/" + state.pages + " · " + state.total + " моделей";
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

function loadModels() {
  // Фильтрация по тегам
  let filteredModels = state.allModels;
  if (state.activeTags.size > 0) {
    filteredModels = state.allModels.filter(model => 
      model.tags.some(tag => state.activeTags.has(tag))
    );
  }
  
  // Фильтрация по поиску
  if (state.query) {
    const query = state.query.toLowerCase();
    filteredModels = filteredModels.filter(model => 
      model.title.toLowerCase().includes(query) ||
      model.description.toLowerCase().includes(query) ||
      model.tags.some(tag => tag.toLowerCase().includes(query))
    );
  }
  
  // Сортировка: image-generation первыми, затем replicate изображения
  filteredModels.sort((a, b) => {
    const aHasImageGen = a.tags.includes("image-generation");
    const bHasImageGen = b.tags.includes("image-generation");
    const aHasReplicate = a.image_url.includes("replicate");
    const bHasReplicate = b.image_url.includes("replicate");
    
    if (aHasImageGen && !bHasImageGen) return -1;
    if (!aHasImageGen && bHasImageGen) return 1;
    if (aHasReplicate && !bHasReplicate) return -1;
    if (!aHasReplicate && bHasReplicate) return 1;
    return 0;
  });
  
  state.total = filteredModels.length;
  state.pages = Math.ceil(state.total / state.per_page);
  
  // Пагинация
  const start = (state.page - 1) * state.per_page;
  const pageModels = filteredModels.slice(start, start + state.per_page);
  
  const grid = qs(".cards-grid");
  grid.innerHTML = "";
  pageModels.forEach(m => grid.appendChild(createCard(m)));
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
    state.page = 1;
    loadModels();
  });
}

function init() {
  state.allModels = ${modelsJson};
  wireSearch();
  renderTags();
  loadModels();
}

document.addEventListener("DOMContentLoaded", init);`;
}

// Основная функция
async function main() {
  console.log('Загружаем данные с сервера...');
  const { models, tags } = await fetchData();
  
  console.log("Загружено " + models.length + " моделей и " + tags.length + " тегов");
  
  console.log('Генерируем статический app.js...');
  const staticApp = generateStaticApp(models, tags);
  
  console.log('Сохраняем файл...');
  fs.writeFileSync('app_static_full.js', staticApp);
  
  console.log('Готово! Файл app_static_full.js создан');
}

main().catch(console.error);
