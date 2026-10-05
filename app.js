// @ts-nocheck

function qs(sel, root = document) { return root.querySelector(sel); }
function qsa(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

const I18N = {
  ru: {
    "nav.catalog": "Каталог моделей",
    "nav.prices": "Цены",
    "nav.lang": "RU / EN",
    "nav.login": "Войти",
    "nav.signup": "Регистрация",
    "nav.logout": "Выйти",
    "nav.theme": "Сменить тему",
    "nav.brand": "{AI}-шница",
    "hero.brand": "-шница",
    "hero.subtitle": "Маркетплейс генеративных моделей",
    "hero.placeholder": "Поиск или генерация",
    "catalog.title": "Каталог моделей",
    "catalog.heading": "Бесплатные генеративные модели на любой вкус",
    "catalog.lead": "Если можешь описать — можешь сгенерировать. Выбирай модель и создавай.",
    "catalog.filters": "Фильтры",
    "catalog.search": "Поиск",
    "catalog.empty": "Не удалось загрузить каталог.",
    "catalog.pager": "{page}/{pages} · {total} моделей",
    "footer.company": "Компания",
    "footer.product": "Продукт",
    "footer.resources": "Ресурсы",
    "footer.legal": "Правовая информация",
    "footer.community": "Сообщество",
    "footer.careers": "Карьера",
    "footer.press": "Пресса и медиа",
    "footer.enterprise": "Для бизнеса",
    "footer.security": "Безопасность",
    "footer.trust": "Центр доверия",
    "footer.partners": "Партнёрство",
    "footer.pricing": "Цены",
    "footer.students": "Скидка студентам",
    "footer.work": "Для работы",
    "footer.founders": "Основателям",
    "footer.pm": "Продакт-менеджерам",
    "footer.designers": "Дизайнерам",
    "footer.marketers": "Маркетологам",
    "footer.sales": "Продажам",
    "footer.ops": "Операциям",
    "footer.people": "HR",
    "footer.proto": "Прототипирование",
    "footer.tools": "Внутренние инструменты",
    "footer.apps": "Скачать приложения",
    "footer.connections": "Интеграции",
    "footer.changelog": "Список изменений",
    "footer.status": "Статус",
    "footer.learn": "Обучение",
    "footer.templates": "Шаблоны",
    "footer.guides": "Гайды",
    "footer.connectors": "Коннекторы",
    "footer.mcp": "MCP-сервер",
    "footer.videos": "Видео",
    "footer.blog": "Блог",
    "footer.support": "Поддержка",
    "footer.reviews": "Отзывы",
    "footer.sitemap": "Карта сайта",
    "footer.privacy": "Политика конфиденциальности",
    "footer.nosell": "Не продавать и не передавать мои данные",
    "footer.cookies": "Настройки cookie",
    "footer.entTerms": "Условия для бизнеса",
    "footer.terms": "Общие условия",
    "footer.desktop": "Условия десктоп-приложения",
    "footer.domain": "Условия регистрации доменов",
    "footer.dmca": "Политика DMCA",
    "footer.a11y": "Доступность",
    "footer.rules": "Правила платформы",
    "footer.abuse": "Сообщить о нарушении",
    "footer.secReport": "Сообщить об уязвимости",
    "footer.dpa": "DPA",
    "footer.becomePartner": "Стать партнёром",
    "footer.hire": "Нанять эксперта",
    "footer.affiliates": "Партнёрская программа",
    "footer.conduct": "Кодекс поведения",
    "prices.title": "Цены",
    "prices.free.name": "Старт",
    "prices.free.desc": "Попробуйте генерацию без оплаты",
    "prices.pro.name": "Про",
    "prices.pro.desc": "Для регулярной работы с моделями",
    "prices.studio.name": "Студия",
    "prices.studio.desc": "Для команд и большого объёма",
    "prices.cta": "Выбрать",
    "auth.loginTitle": "Войти",
    "auth.signupTitle": "Регистрация",
    "auth.email": "Email",
    "auth.password": "Пароль",
    "auth.submitLogin": "Войти",
    "auth.submitSignup": "Зарегистрироваться",
    "auth.toSignup": "Нет аккаунта? Создать",
    "auth.toLogin": "Уже есть аккаунт? Войти",
    "auth.errorEmail": "Введите корректный email",
    "auth.errorPassword": "Пароль должен быть не короче 6 символов",
    "auth.errorExists": "Такой email уже зарегистрирован",
    "auth.errorInvalid": "Неверный email или пароль",
    "auth.or": "или",
    "auth.google": "Продолжить с Google",
    "auth.github": "Продолжить с GitHub",
    "auth.yandex": "Продолжить с Яндекс",
    "auth.vk": "Продолжить с VK",
    "auth.oauthMissing": "Для этого входа нужны ключи OAuth в .env",
    "auth.oauthFailed": "Не удалось войти через этот сервис",
    "doc.title": "{AI}-шница — Маркетплейс нейросетей",
    "doc.titleCatalog": "Каталог моделей — {AI}-шница",
    "doc.titlePrices": "Цены — {AI}-шница",
    "hero.searchAria": "Поиск или генерация",
  },
  en: {
    "nav.catalog": "Model catalog",
    "nav.prices": "Pricing",
    "nav.lang": "RU / EN",
    "nav.login": "Log in",
    "nav.signup": "Sign up",
    "nav.logout": "Log out",
    "nav.theme": "Toggle theme",
    "nav.brand": "{AI}-shnitsa",
    "hero.brand": "-shnitsa",
    "hero.subtitle": "Marketplace of generative models",
    "hero.placeholder": "Search or generate",
    "catalog.title": "Model catalog",
    "catalog.heading": "Free generative models for every taste",
    "catalog.lead": "If you can describe it, you can generate it. Pick a model and create.",
    "catalog.filters": "Filters",
    "catalog.search": "Search",
    "catalog.empty": "Could not load the catalog.",
    "catalog.pager": "{page}/{pages} · {total} models",
    "footer.company": "Company",
    "footer.product": "Product",
    "footer.resources": "Resources",
    "footer.legal": "Legal",
    "footer.community": "Community",
    "footer.careers": "Careers",
    "footer.press": "Press & media",
    "footer.enterprise": "Enterprise",
    "footer.security": "Security",
    "footer.trust": "Trust center",
    "footer.partners": "Partnerships",
    "footer.pricing": "Pricing",
    "footer.students": "Student discount",
    "footer.work": "For Work",
    "footer.founders": "Founders",
    "footer.pm": "Product Managers",
    "footer.designers": "Designers",
    "footer.marketers": "Marketers",
    "footer.sales": "Sales",
    "footer.ops": "Ops",
    "footer.people": "People",
    "footer.proto": "Prototyping",
    "footer.tools": "Internal Tools",
    "footer.apps": "Download apps",
    "footer.connections": "Connections",
    "footer.changelog": "Changelog",
    "footer.status": "Status",
    "footer.learn": "Learn",
    "footer.templates": "Templates",
    "footer.guides": "Guides",
    "footer.connectors": "Connectors",
    "footer.mcp": "MCP server",
    "footer.videos": "Videos",
    "footer.blog": "Blog",
    "footer.support": "Support",
    "footer.reviews": "Reviews",
    "footer.sitemap": "Sitemap",
    "footer.privacy": "Privacy policy",
    "footer.nosell": "Do not sell or share my personal information",
    "footer.cookies": "Cookie settings",
    "footer.entTerms": "Enterprise terms",
    "footer.terms": "General terms",
    "footer.desktop": "Desktop app terms",
    "footer.domain": "Domain registration terms",
    "footer.dmca": "DMCA copyright policy",
    "footer.a11y": "Accessibility",
    "footer.rules": "Platform rules",
    "footer.abuse": "Report abuse",
    "footer.secReport": "Report security concerns",
    "footer.dpa": "DPA",
    "footer.becomePartner": "Become a partner",
    "footer.hire": "Hire an expert",
    "footer.affiliates": "Affiliates",
    "footer.conduct": "Code of conduct",
    "prices.title": "Pricing",
    "prices.free.name": "Starter",
    "prices.free.desc": "Try generation for free",
    "prices.pro.name": "Pro",
    "prices.pro.desc": "For regular work with models",
    "prices.studio.name": "Studio",
    "prices.studio.desc": "For teams and high volume",
    "prices.cta": "Choose",
    "auth.loginTitle": "Log in",
    "auth.signupTitle": "Create account",
    "auth.email": "Email",
    "auth.password": "Password",
    "auth.submitLogin": "Log in",
    "auth.submitSignup": "Sign up",
    "auth.toSignup": "No account? Create one",
    "auth.toLogin": "Already have an account? Log in",
    "auth.errorEmail": "Enter a valid email",
    "auth.errorPassword": "Password must be at least 6 characters",
    "auth.errorExists": "This email is already registered",
    "auth.errorInvalid": "Invalid email or password",
    "auth.or": "or",
    "auth.google": "Continue with Google",
    "auth.github": "Continue with GitHub",
    "auth.yandex": "Continue with Yandex",
    "auth.vk": "Continue with VK",
    "auth.oauthMissing": "Add OAuth keys for this provider in .env",
    "auth.oauthFailed": "Could not sign in with this provider",
    "doc.title": "{AI}-shnitsa — Marketplace of neural networks",
    "doc.titleCatalog": "Model catalog — {AI}-shnitsa",
    "doc.titlePrices": "Pricing — {AI}-shnitsa",
    "hero.searchAria": "Search or generate",
  },
};

let currentUser = null;

const SOCIAL_ICONS = {
  google: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="#EA4335" d="M12 10.2v3.6h5.1c-.2 1.2-1.5 3.6-5.1 3.6-3.1 0-5.6-2.5-5.6-5.6S8.9 6.2 12 6.2c1.7 0 2.9.7 3.5 1.3l2.4-2.3C16.6 3.9 14.5 3 12 3 6.9 3 2.8 7.1 2.8 12.2S6.9 21.4 12 21.4c5.8 0 8.1-4.1 8.1-6.2 0-.4 0-.7-.1-1H12z"/><path fill="#4285F4" d="M20.1 15.2c.6-1.6.8-3.2.8-4 0-.4 0-.7-.1-1H12v3.6h5.1c-.1.6-.5 1.6-1.1 2.2l.1.1 3 2.3c.1-.1.2-.1.2-.1"/><path fill="#FBBC05" d="M6.7 14.3l-.1.1-2.5 1.9C5.3 18.8 8.4 21.4 12 21.4c2.2 0 4.1-.7 5.5-2l-3-2.3c-.8.6-1.9.9-3.1.9-2.4 0-4.4-1.6-5.1-3.7"/><path fill="#34A853" d="M12 6.2c1.7 0 2.9.7 3.5 1.3l2.4-2.3C16.6 3.9 14.5 3 12 3 8.4 3 5.3 5.6 4.1 8.9l2.6 2c.7-2.1 2.7-3.7 5.3-3.7"/></svg>',
  github: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="#111" d="M12 2C6.5 2 2 6.6 2 12.2c0 4.5 2.9 8.3 6.9 9.6.5.1.7-.2.7-.5v-1.8c-2.8.6-3.4-1.4-3.4-1.4-.4-1.1-1.1-1.4-1.1-1.4-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.6 2.4 1.1 3 .8.1-.7.4-1.1.6-1.4-2.2-.3-4.6-1.2-4.6-5.1 0-1.1.4-2 1-2.8-.1-.3-.4-1.3.1-2.7 0 0 .8-.3 2.8 1.1a9.4 9.4 0 0 1 5.1 0c2-1.4 2.8-1.1 2.8-1.1.5 1.4.2 2.4.1 2.7.6.8 1 1.7 1 2.8 0 3.9-2.4 4.8-4.6 5.1.4.3.7 1 .7 2v3c0 .3.2.6.7.5 4-1.3 6.9-5.1 6.9-9.6C22 6.6 17.5 2 12 2z"/></svg>',
  yandex: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="#FC3F1D" d="M12.7 20.5h-3l4.4-11.3c.8-2 1.1-3.5 1.1-5 0-.6 0-1.1-.1-1.5h3c.1.5.1 1 .1 1.6 0 1.8-.4 3.7-1.5 6.3L12.7 20.5z"/><path fill="#FC3F1D" d="M8.4 3.7h3.2L7.2 20.5H4.3L8.4 3.7z"/></svg>',
  vk: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="#0077FF" d="M12.8 17.6c-5.4 0-8.5-3.7-8.6-9.9h2.7c.1 4.6 2.1 6.5 3.8 6.9V7.7h2.5v3.9c1.6-.2 3.3-2 3.9-3.9h2.5c-.7 2.2-2.6 4-3.5 4.6.9.5 3.1 2.1 3.8 5.3h-2.8c-.6-1.8-2.1-3.2-4-3.4v3.4h-.3z"/></svg>',
};

function currentLang() {
  return localStorage.getItem("lang") === "en" ? "en" : "ru";
}

function t(key) {
  const dict = I18N[currentLang()] || I18N.ru;
  return dict[key] || key;
}

function applyLang(lang) {
  const dict = I18N[lang] || I18N.ru;
  document.documentElement.lang = lang;
  localStorage.setItem("lang", lang);

  qsa("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    if (dict[key]) el.textContent = dict[key];
  });

  qsa("[data-i18n-placeholder]").forEach((el) => {
    const key = el.getAttribute("data-i18n-placeholder");
    if (dict[key]) {
      el.setAttribute("placeholder", dict[key]);
      el.setAttribute("aria-label", dict[key]);
    }
  });

  qsa("[data-i18n-aria]").forEach((el) => {
    const key = el.getAttribute("data-i18n-aria");
    if (dict[key]) el.setAttribute("aria-label", dict[key]);
  });

  const searchForm = qs(".search-bar");
  if (searchForm && dict["hero.searchAria"]) {
    searchForm.setAttribute("aria-label", dict["hero.searchAria"]);
  }
  if (document.body.classList.contains("page-catalog")) document.title = dict["doc.titleCatalog"];
  else if (document.body.classList.contains("page-prices")) document.title = dict["doc.titlePrices"];
  else document.title = dict["doc.title"];

  renderAuthActions();
  syncAuthModal();
  const footerLang = qs("[data-footer-lang-label]");
  if (footerLang) footerLang.textContent = lang === "en" ? "EN" : "RU";
  if (qs(".cards-grid") && catalogState.models.length) renderPager();
}

function langToggleHtml() {
  const lang = currentLang();
  const label = lang === "en" ? "EN" : "RU";
  return `
    <button class="btn-lang" type="button" data-lang-toggle aria-label="${label}">${label}</button>
  `;
}

function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

<<<<<<< HEAD
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

async function api(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (method !== "GET" && method !== "HEAD") {
    headers["X-CSRF-Token"] = await ensureCsrf();
  }
  const res = await fetch(path, {
    credentials: "same-origin",
    ...options,
    headers,
=======
async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
>>>>>>> 4404398504bd139f0127103f56fd9a4a82bda600
  });
  let data = {};
  try {
    data = await res.json();
  } catch (error) {
    data = {};
  }
  return { res, data };
}

async function loadCurrentUser() {
  try {
    const { data } = await api("/api/auth/me");
    currentUser = data.user || null;
  } catch (error) {
    currentUser = null;
  }
}

function showAuthErrorFromQuery() {
  const params = new URLSearchParams(window.location.search);
  const error = params.get("auth_error");
  if (!error) return;
  openAuthModal("login");
  const box = qs("[data-auth-error]");
  if (box) {
    box.textContent = error === "oauth_not_configured" ? t("auth.oauthMissing") : t("auth.oauthFailed");
  }
  window.history.replaceState({}, "", window.location.pathname);
}

function ensureAuthModal() {
  if (qs(".auth-modal")) return qs(".auth-modal");

  const modal = document.createElement("div");
  modal.className = "auth-modal";
  modal.innerHTML = `
    <div class="auth-dialog">
      <h2 data-auth-title></h2>
      <form data-auth-form>
        <div class="auth-field">
          <label for="auth-email">${t("auth.email")}</label>
          <input id="auth-email" type="email" name="email" autocomplete="email" required />
        </div>
        <div class="auth-field">
          <label for="auth-password">${t("auth.password")}</label>
          <input id="auth-password" type="password" name="password" autocomplete="current-password" required />
        </div>
        <div class="auth-error" data-auth-error></div>
        <button class="auth-submit" type="submit" data-auth-submit></button>
      </form>
      <div class="auth-divider"><span data-auth-or></span></div>
      <div class="social-auth">
        <button type="button" class="social-btn" data-social="google">${SOCIAL_ICONS.google}<span data-i18n-social="auth.google">Google</span></button>
        <button type="button" class="social-btn" data-social="github">${SOCIAL_ICONS.github}<span data-i18n-social="auth.github">GitHub</span></button>
        <button type="button" class="social-btn" data-social="yandex">${SOCIAL_ICONS.yandex}<span data-i18n-social="auth.yandex">Яндекс</span></button>
        <button type="button" class="social-btn" data-social="vk">${SOCIAL_ICONS.vk}<span data-i18n-social="auth.vk">VK</span></button>
      </div>
      <div class="auth-switch">
        <button type="button" data-auth-switch></button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);

  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeAuthModal();
  });
  modal.querySelector("[data-auth-form]").addEventListener("submit", handleAuthSubmit);
  modal.querySelector("[data-auth-switch]").addEventListener("click", () => {
    modal.dataset.mode = modal.dataset.mode === "signup" ? "login" : "signup";
    syncAuthModal();
  });
  qsa("[data-social]", modal).forEach((btn) => {
    btn.addEventListener("click", () => loginWithSocial(btn.getAttribute("data-social")));
  });
  return modal;
}

function syncAuthModal() {
  const modal = qs(".auth-modal");
  if (!modal) return;
  const mode = modal.dataset.mode || "login";
  const title = qs("[data-auth-title]", modal);
  const submit = qs("[data-auth-submit]", modal);
  const sw = qs("[data-auth-switch]", modal);
  const emailLabel = modal.querySelector("label[for='auth-email']");
  const passwordLabel = modal.querySelector("label[for='auth-password']");
  if (title) title.textContent = mode === "signup" ? t("auth.signupTitle") : t("auth.loginTitle");
  if (submit) submit.textContent = mode === "signup" ? t("auth.submitSignup") : t("auth.submitLogin");
  if (sw) sw.textContent = mode === "signup" ? t("auth.toLogin") : t("auth.toSignup");
  if (emailLabel) emailLabel.textContent = t("auth.email");
  if (passwordLabel) passwordLabel.textContent = t("auth.password");
  const or = qs("[data-auth-or]", modal);
  if (or) or.textContent = t("auth.or");
  qsa("[data-i18n-social]", modal).forEach((el) => {
    el.textContent = t(el.getAttribute("data-i18n-social"));
  });
}

function openAuthModal(mode) {
  location.href = "/auth?next=" + encodeURIComponent(location.pathname + location.search || "/app");
}

function closeAuthModal() {
  const modal = qs(".auth-modal");
  if (modal) modal.classList.remove("is-open");
}

function renderAuthActions() {
  const wrap = qs("[data-auth-actions]");
  if (!wrap) return;
  const user = currentUser;
  if (user) {
    const label = user.name || user.email;
    wrap.innerHTML = `
      ${langToggleHtml()}
      <span class="auth-user">${label}</span>
      <button class="btn-login" type="button" data-auth-logout>${t("nav.logout")}</button>
    `;
    qs("[data-auth-logout]", wrap).addEventListener("click", async () => {
      await api("/api/auth/logout", { method: "POST" });
      currentUser = null;
      renderAuthActions();
    });
    wireLangToggle();
    return;
  }

  wrap.innerHTML = `
    ${langToggleHtml()}
    <button class="btn-signup" type="button" data-auth-open="login">${t("nav.login")}</button>
  `;
  qsa("[data-auth-open]", wrap).forEach((btn) => {
    btn.addEventListener("click", () => openAuthModal(btn.getAttribute("data-auth-open")));
  });
  wireLangToggle();
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  const modal = qs(".auth-modal");
  const form = e.currentTarget;
  const email = String(new FormData(form).get("email") || "").trim().toLowerCase();
  const password = String(new FormData(form).get("password") || "");
  const error = qs("[data-auth-error]", modal);
  const mode = modal.dataset.mode || "login";

  if (!isValidEmail(email)) {
    error.textContent = t("auth.errorEmail");
    return;
  }
  if (password.length < 6) {
    error.textContent = t("auth.errorPassword");
    return;
  }

  const path = mode === "signup" ? "/api/auth/register" : "/api/auth/login";
  const { res, data } = await api(path, {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    if (data.error === "exists") error.textContent = t("auth.errorExists");
    else if (data.error === "weak_password") error.textContent = t("auth.errorPassword");
    else if (data.error === "invalid_email") error.textContent = t("auth.errorEmail");
    else error.textContent = t("auth.errorInvalid");
    return;
  }
  currentUser = data.user;
  closeAuthModal();
  renderAuthActions();
}

function loginWithSocial(provider) {
  window.location.href = `/api/auth/${provider}`;
}

function wireLangToggle() {
  qsa("[data-lang-toggle]").forEach((btn) => {
    if (btn.dataset.langWired) return;
    btn.dataset.langWired = "1";
    btn.addEventListener("click", () => {
      applyLang(currentLang() === "ru" ? "en" : "ru");
    });
  });
}

function currentTheme() {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

function applyTheme(theme) {
  const next = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
  try {
    localStorage.setItem("theme", next);
  } catch (_) {}
  qsa("[data-theme-toggle]").forEach((btn) => {
    btn.setAttribute("aria-label", t("nav.theme"));
    btn.setAttribute("title", t("nav.theme"));
  });
}

function wireThemeToggle() {
  qsa("[data-theme-toggle]").forEach((btn) => {
    if (btn.dataset.themeWired) return;
    btn.dataset.themeWired = "1";
    btn.addEventListener("click", () => {
      applyTheme(currentTheme() === "dark" ? "light" : "dark");
    });
  });
  applyTheme(currentTheme());
}

function goToGenerate(query) {
  const url = query
    ? `generate.html?q=${encodeURIComponent(query)}`
    : "generate.html";
  window.location.href = url;
}

function wireSearch() {
  const form = qs(".search-bar") || qs(".header-search");
  const input = qs(".search-input") || qs(".header-search-input");
  if (form && input) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      goToGenerate(input.value.trim());
    });
  }

  const catalogBtn = qs("[data-catalog-btn]");
  if (catalogBtn) {
    catalogBtn.addEventListener("click", () => {
      const catalog = qs("#catalog");
      if (catalog) catalog.scrollIntoView({ behavior: "smooth" });
      else window.location.href = "catalog.html";
    });
  }
}

function wireGenerateButton() {
  const generateBtn = qs(".generate-btn");
  if (!generateBtn) return;

  generateBtn.addEventListener("click", () => {
    const input = qs(".search-input") || qs(".header-search-input");
    const query = input ? input.value.trim() : "";
    const url = query
      ? `generate.html?q=${encodeURIComponent(query)}`
      : "generate.html";
    window.location.href = url;
  });
}

const catalogState = {
  models: [],
  tags: [],
  activeTags: new Set(),
  query: "",
  page: 1,
  perPage: 12,
  total: 0,
  pages: 0,
};

function getPlaceholder(model) {
  const tags = (model.tags || []).map((s) => String(s).toLowerCase());
  let label = "preview";
  if (tags.includes("video-generation") || tags.includes("text-to-video") || tags.includes("генерация-видео")) label = "video";
  else if (tags.includes("music-generation") || tags.includes("audio") || tags.includes("аудио")) label = "music";
  else if (tags.includes("image-generation") || tags.includes("text-to-image") || tags.includes("генерация-изображений")) label = "image";
  return `https://dummyimage.com/800x533/edf2f7/94a3b8&text=${encodeURIComponent(label)}`;
}

function createCard(model) {
  const article = document.createElement("article");
  article.className = "card";

  const displayName = model.name || model.title || model.id || "модель";
  const media = document.createElement("div");
  media.className = "card-media";
  const img = document.createElement("img");
  img.src = model.image_url || getPlaceholder(model);
  img.alt = displayName;
  img.loading = "lazy";
  img.decoding = "async";
  img.sizes = "(max-width:560px) 100vw, (max-width:1100px) 50vw, 33vw";
  img.referrerPolicy = "no-referrer";
  img.onerror = () => {
    const placeholder = getPlaceholder(model);
    if (img.src !== placeholder) img.src = placeholder;
  };
  media.appendChild(img);

  const body = document.createElement("div");
  body.className = "card-body";
  body.innerHTML = `
    <h3 class="card-title"><strong>${escapeHtmlCatalog(displayName)}</strong></h3>
  `;

  const generic = (model.description || "").trim().toLowerCase() === "model from replicate";
  if (!generic && model.description) {
    const p = document.createElement("p");
    p.className = "card-desc";
    p.textContent = model.description;
    body.appendChild(p);
  }

  if (model.price) {
    const price = document.createElement("p");
    price.className = "card-desc card-price";
    price.textContent = model.price;
    body.appendChild(price);
  }

  if (Array.isArray(model.tags) && model.tags.length) {
    const tags = document.createElement("div");
    tags.className = "card-tags";
    tags.innerHTML = model.tags.map((tag) => `<span class="hash">#${escapeHtmlCatalog(tag)}</span>`).join(" ");
    body.appendChild(tags);
  }

  article.appendChild(media);
  article.appendChild(body);
  article.addEventListener("click", () => {
    const id = model.id || "";
    if (id) {
      localStorage.setItem("selectedGenerateModelId", id);
      localStorage.setItem("selectedIntegrationId", id);
    }
    localStorage.setItem("selectedModel", JSON.stringify(model));
    window.location.href = "generate.html";
  });
  return article;
}

function escapeHtmlCatalog(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderTags() {
  const wrap = qs(".filters .tags");
  if (!wrap) return;
  wrap.innerHTML = "";
  catalogState.tags.forEach((tag) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tag" + (catalogState.activeTags.has(tag.name) ? " tag--active" : "");
    btn.textContent = tag.name;
    btn.addEventListener("click", () => {
      catalogState.page = 1;
      if (catalogState.activeTags.has(tag.name)) catalogState.activeTags.delete(tag.name);
      else catalogState.activeTags.add(tag.name);
      renderTags();
      renderCatalogPage();
    });
    wrap.appendChild(btn);
  });
}

function renderPager() {
  const container = qs(".catalog-content");
  if (!container) return;
  let pager = qs(".pager");
  if (!pager) {
    pager = document.createElement("div");
    pager.className = "pager";
    container.appendChild(pager);
  }
  pager.innerHTML = "";
  if (catalogState.pages <= 1) return;

  const info = document.createElement("div");
  info.className = "pager-info";
  info.textContent = t("catalog.pager")
    .replace("{page}", String(catalogState.page))
    .replace("{pages}", String(catalogState.pages))
    .replace("{total}", String(catalogState.total));

  const prev = document.createElement("button");
  prev.className = "pager-btn";
  prev.type = "button";
  prev.textContent = "‹";
  prev.disabled = catalogState.page <= 1;
  prev.addEventListener("click", () => {
    catalogState.page -= 1;
    renderCatalogPage();
  });

  const next = document.createElement("button");
  next.className = "pager-btn";
  next.type = "button";
  next.textContent = "›";
  next.disabled = catalogState.page >= catalogState.pages;
  next.addEventListener("click", () => {
    catalogState.page += 1;
    renderCatalogPage();
  });

  pager.appendChild(prev);
  pager.appendChild(info);
  pager.appendChild(next);
}

function renderCatalogPage() {
  const grid = qs(".cards-grid");
  if (!grid) return;

  let filtered = catalogState.models;
  if (catalogState.activeTags.size > 0) {
    filtered = filtered.filter((model) =>
      Array.isArray(model.tags) && model.tags.some((tag) => catalogState.activeTags.has(tag))
    );
  }
  if (catalogState.query) {
    const query = catalogState.query.toLowerCase();
    filtered = filtered.filter((model) =>
      (model.name && model.name.toLowerCase().includes(query)) ||
      (model.vendor && model.vendor.toLowerCase().includes(query)) ||
      (model.title && model.title.toLowerCase().includes(query)) ||
      (model.description && model.description.toLowerCase().includes(query)) ||
      (Array.isArray(model.tags) && model.tags.some((tag) => tag.toLowerCase().includes(query)))
    );
  }

  catalogState.total = filtered.length;
  catalogState.pages = Math.max(1, Math.ceil(filtered.length / catalogState.perPage));
  if (catalogState.page > catalogState.pages) catalogState.page = catalogState.pages;

  const start = (catalogState.page - 1) * catalogState.perPage;
  const pageModels = filtered.slice(start, start + catalogState.perPage);
  grid.innerHTML = "";
  pageModels.forEach((model) => grid.appendChild(createCard(model)));
  renderPager();
}

function wireCatalogSearch() {
  const input = qs(".filters-search-input");
  if (!input) return;
  const applyQuery = () => {
    catalogState.query = input.value.trim();
    catalogState.page = 1;
    renderCatalogPage();
  };
  input.addEventListener("input", applyQuery);
  input.addEventListener("search", applyQuery);
}

function wireFiltersToggle() {
  const toggle = qs(".filters-toggle");
  const content = qs(".filters-content");
  const arrow = qs(".filters-toggle-arrow");
  if (!toggle || !content) return;
  toggle.addEventListener("click", () => {
    content.classList.toggle("show");
    if (arrow) arrow.style.transform = content.classList.contains("show") ? "rotate(180deg)" : "rotate(0deg)";
  });
}

async function loadCatalog() {
  const grid = qs(".cards-grid");
  if (!grid) return;

  try {
    const modelsResponse = await fetch("/api/catalog", { credentials: "same-origin" });
    if (!modelsResponse.ok) throw new Error("Failed to load models");
    const data = await modelsResponse.json();
    catalogState.models = data.items || [];
    catalogState.tags = Array.isArray(data.tags) && data.tags.length
      ? data.tags
      : Array.from(
          new Set(catalogState.models.flatMap((m) => m.tags || []))
        ).map((name) => ({ name }));
    renderTags();
    renderCatalogPage();
  } catch (error) {
    grid.innerHTML = `<p class="card-desc">${t("catalog.empty")}</p>`;
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  applyLang(currentLang());
  wireLangToggle();
  wireThemeToggle();
  ensureAuthModal();
  await loadCurrentUser();
  renderAuthActions();
  showAuthErrorFromQuery();
  wireSearch();
  wireGenerateButton();
  wireFiltersToggle();
  wireCatalogSearch();
  wireLandingExtras();
  loadCatalog();
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAuthModal();
  });
});

function wireLandingExtras() {
  const composer = qs("[data-composer-form]");
  if (composer) {
    composer.addEventListener("submit", (e) => {
      e.preventDefault();
      const input = qs(".composer-input", composer);
      goToGenerate(input ? input.value.trim() : "");
    });
  }

  wireSeedanceDemo();
  wireShareRows();
  wireReveals();
}

function wireSeedanceDemo() {
  const root = qs("[data-seedance-demo]");
  if (!root) return;

  const examples = [
    {
      tag: "Референс",
      thumb: "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=480&q=80",
      prompt: "Оживи этот морской кадр. Оставь тех же людей и дай разговору развернуться.",
      caption: "Тихий момент — ожил.",
      result: "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1400&q=80",
      href: "generate.html?q=" + encodeURIComponent("Оживи сцену у моря на Seedance Lite"),
    },
    {
      tag: "Из фото",
      thumb: "https://images.unsplash.com/photo-1493809842364-78817add7ffb?auto=format&fit=crop&w=480&q=80",
      prompt: "Сделай кинематографичный пролёт по комнате, сохрани свет и композицию.",
      caption: "Комната в движении.",
      result: "https://images.unsplash.com/photo-1493809842364-78817add7ffb?auto=format&fit=crop&w=1400&q=80",
      href: "generate.html?q=" + encodeURIComponent("Сделай видео пролёта по комнате Seedance Lite"),
    },
    {
      tag: "По тексту",
      thumb: "https://images.unsplash.com/photo-1501785888041-af3ef285b470?auto=format&fit=crop&w=480&q=80",
      prompt: "Туманное утро в горах, камера медленно поднимается над озером.",
      caption: "Пейзаж ожил из текста.",
      result: "https://images.unsplash.com/photo-1501785888041-af3ef285b470?auto=format&fit=crop&w=1400&q=80",
      href: "generate.html?q=" + encodeURIComponent("Туманное утро в горах, камера над озером Seedance Lite"),
    },
  ];

  let idx = 0;
  const apply = (i) => {
    const ex = examples[i];
    if (!ex) return;
    qsa("[data-seed-ex]", root).forEach((b) =>
      b.classList.toggle("is-active", Number(b.getAttribute("data-seed-ex")) === i)
    );
    const panel = qs("[data-seed-panel]", root);
    if (panel) {
      panel.classList.remove("is-swap");
      void panel.offsetWidth;
      panel.classList.add("is-swap");
    }
    const tag = qs("[data-seed-tag]", root);
    const thumb = qs("[data-seed-thumb]", root);
    const prompt = qs("[data-seed-prompt]", root);
    const caption = qs("[data-seed-caption]", root);
    const result = qs("[data-seed-result]", root);
    const cta = qs("[data-seed-cta]", root);
    if (tag) tag.textContent = ex.tag;
    if (prompt) prompt.textContent = ex.prompt;
    if (caption) caption.textContent = ex.caption;
    if (cta) cta.setAttribute("href", ex.href);
    if (thumb) thumb.src = ex.thumb;
    if (result) result.src = ex.result;
  };

  qsa("[data-seed-ex]", root).forEach((btn) => {
    btn.addEventListener("click", () => {
      idx = Number(btn.getAttribute("data-seed-ex"));
      apply(idx);
    });
  });

  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    setInterval(() => {
      idx = (idx + 1) % examples.length;
      apply(idx);
    }, 5000);
  }
}

function wireShareRows() {
  const root = qs("[data-share-curve]");
  if (!root) return;
  const inner = qs("[data-share-inner]", root);
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  qsa("[data-share-row]", root).forEach((row) => {
    Array.from(row.children).forEach((node) => row.appendChild(node.cloneNode(true)));
  });

  const bend = () => {
    const rect = root.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    qsa(".share-tile", root).forEach((tile) => {
      const tr = tile.getBoundingClientRect();
      if (tr.right < rect.left - 40 || tr.left > rect.right + 40) return;
      const mid = tr.left + tr.width / 2;
      const n = Math.max(-1.2, Math.min(1.2, (mid - cx) / Math.max(rect.width * 0.5, 1)));
      tile.style.setProperty("--ry", (n * -36).toFixed(2) + "deg");
      tile.style.setProperty("--tz", ((1 - Math.abs(n)) * 48).toFixed(1) + "px");
    });
  };

  if (reduce) {
    bend();
    return;
  }

  let raf = 0;
  const loop = () => {
    bend();
    raf = requestAnimationFrame(loop);
  };

  const io = new IntersectionObserver(
    (entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        if (!raf) raf = requestAnimationFrame(loop);
      } else if (raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    },
    { threshold: 0.05 }
  );
  io.observe(root);

  if (inner) {
    window.addEventListener(
      "pointermove",
      (e) => {
        const y = (e.clientY / window.innerHeight - 0.5) * 5;
        inner.style.transform = "rotateX(" + (26 + y) + "deg)";
      },
      { passive: true }
    );
  }
}

function wireReveals() {
  const nodes = qsa(".reveal");
  if (!nodes.length) return;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    nodes.forEach((n) => n.classList.add("is-in"));
    return;
  }
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          e.target.classList.add("is-in");
          io.unobserve(e.target);
        }
      });
    },
    { threshold: 0.12 }
  );
  nodes.forEach((n) => io.observe(n));
}

