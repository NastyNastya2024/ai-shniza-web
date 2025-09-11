// @ts-nocheck
// Загружаем данные из JSON файлов
let models = [];
let tags = [];

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

// Функция для загрузки данных
async function loadData() {
  try {
    console.log('Начинаем загрузку models.json...');
    // Загружаем модели
    const modelsResponse = await fetch('models.json');
    console.log('Ответ models.json:', modelsResponse.status);
    if (!modelsResponse.ok) {
      throw new Error(`HTTP error! status: ${modelsResponse.status}`);
    }
    const modelsData = await modelsResponse.json();
    models = modelsData.items || modelsData; // Поддерживаем оба формата
    console.log('Модели загружены:', models.length);
    
    console.log('Начинаем загрузку tags_data.json...');
    // Загружаем теги
    const tagsResponse = await fetch('tags_data.json');
    console.log('Ответ tags_data.json:', tagsResponse.status);
    if (!tagsResponse.ok) {
      throw new Error(`HTTP error! status: ${tagsResponse.status}`);
    }
    tags = await tagsResponse.json();
    console.log('Теги загружены:', tags.length);
    
    console.log(`Загружено ${models.length} моделей и ${tags.length} тегов`);
    
    // Инициализируем приложение
    console.log('Инициализируем приложение...');
    initApp();
  } catch (error) {
    console.error('Ошибка загрузки данных:', error);
    // Показываем сообщение об ошибке
    const grid = document.querySelector('.cards-grid');
    if (grid) {
      grid.innerHTML = '<p style="text-align: center; padding: 2rem; color: #666;">Ошибка загрузки данных. Проверьте консоль для подробностей.</p>';
    }
  }
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
  article.style.cursor = "pointer";

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
  
  // Добавляем обработчик клика для перехода на страницу генерации
  article.addEventListener('click', () => {
    // Сохраняем данные модели в localStorage
    localStorage.setItem('selectedModel', JSON.stringify(model));
    // Переходим на страницу генерации
    window.location.href = 'generate.html';
  });
  
  return article;
}

function renderTags() {
  const wrap = qs(".filters .tags");
  if (!wrap) return;
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

function loadTags() {
  state.tags = tags;
  renderTags();
}

function loadModels() {
  let filteredModels = models;
  
  // Фильтрация по тегам
  if (state.activeTags.size > 0) {
    filteredModels = filteredModels.filter(model => 
      model.tags && model.tags.some(tag => state.activeTags.has(tag))
    );
  }
  
  // Фильтрация по поиску
  if (state.query) {
    const query = state.query.toLowerCase();
    filteredModels = filteredModels.filter(model => 
      (model.name && model.name.toLowerCase().includes(query)) ||
      (model.vendor && model.vendor.toLowerCase().includes(query)) ||
      (model.description && model.description.toLowerCase().includes(query)) ||
      (model.tags && model.tags.some(tag => tag.toLowerCase().includes(query)))
    );
  }
  
  // Сортировка: сначала image-generation, потом с Replicate изображениями
  filteredModels.sort((a, b) => {
    const aHasImageGen = a.tags && a.tags.includes('image-generation');
    const bHasImageGen = b.tags && b.tags.includes('image-generation');
    const aHasReplicate = a.image_url && a.image_url.includes('replicate');
    const bHasReplicate = b.image_url && b.image_url.includes('replicate');
    
    if (aHasImageGen && !bHasImageGen) return -1;
    if (!aHasImageGen && bHasImageGen) return 1;
    if (aHasReplicate && !bHasReplicate) return -1;
    if (!aHasReplicate && bHasReplicate) return 1;
    return 0;
  });
  
  state.total = filteredModels.length;
  state.pages = Math.ceil(filteredModels.length / state.per_page);
  
  // Пагинация
  const start = (state.page - 1) * state.per_page;
  const end = start + state.per_page;
  const pageModels = filteredModels.slice(start, end);
  
  const grid = qs(".cards-grid");
  if (grid) {
    grid.innerHTML = "";
    pageModels.forEach(m => grid.appendChild(createCard(m)));
  }
  renderPager();
}

function wireSearch() {
  const form = qs(".search-bar");
  const input = qs(".search-input");
  if (!form || !input) return;
  
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

function initApp() {
  loadTags();
  loadModels();
  wireSearch();
  wireFiltersToggle();
}

function wireFiltersToggle() {
  const toggle = document.querySelector('.filters-toggle');
  const content = document.querySelector('.filters-content');
  const arrow = document.querySelector('.filters-toggle-arrow');
  
  if (toggle && content && arrow) {
    toggle.addEventListener('click', () => {
      content.classList.toggle('show');
      // Поворачиваем стрелку при открытии/закрытии
      if (content.classList.contains('show')) {
        arrow.style.transform = 'rotate(180deg)';
      } else {
        arrow.style.transform = 'rotate(0deg)';
      }
    });
  }
}

// Запускаем загрузку данных при загрузке страницы
document.addEventListener('DOMContentLoaded', () => {
  console.log('DOM загружен, начинаем загрузку данных...');
  loadData();
});