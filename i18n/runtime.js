/* {AI}-шница — общий i18n-рантайм (ru / en).
 *
 * Подключение (до остальных скриптов страницы):
 *   <script src="/i18n/dict-ru.js"></script>
 *   <script src="/i18n/dict-en.js"></script>
 *   <script src="/i18n/runtime.js"></script>
 *
 * API: window.AISH_I18N = { LANG, BRAND, BRAND_FORMS, t, applyI18n, setLang, money, num, ago }
 *
 * Язык: ?lang= → localStorage 'aish-lang' → localStorage 'lang' → navigator → 'ru'.
 * Словари берутся из window.AISH_DICT_RU / window.AISH_DICT_EN.
 *
 * t(key, params):
 *   - массив            → случайный вариант (подряд один и тот же не повторяется);
 *   - объект one/few/many/other → форма по Intl.PluralRules(LANG) для params.n;
 *   - {name}            → params.name;
 *   - {brand}           → бренд ('{AI}-шница' / '{AI}-shnitsa');
 *   - {brandGen} / {brandAcc} / {brandPrep} → падежные формы бренда в ru (в en = brand).
 *   Неизвестные {плейсхолдеры} остаются как есть. Фолбэк: ru-словарь → сам ключ (+ console.warn).
 *
 * Разметка:
 *   data-i18n="key"                       → textContent
 *   data-i18n-html="key"                  → innerHTML (только доверенные строки словаря!)
 *   data-i18n-attr="placeholder:key;aria-label:key2"
 *   data-i18n-params='{"n":2}'            → параметры для t() (опционально)
 *   [data-lang-toggle]                    → клик переключает язык и перезагружает страницу
 *   [data-footer-lang-label]              → код ПРОТИВОПОЛОЖНОГО языка (RU → «EN»)
 *   button.lang                           → код ТЕКУЩЕГО языка («RU»)
 */
(function () {
  'use strict';

  var SUPPORTED = ['ru', 'en'];
  var STORE_KEY = 'aish-lang';
  var LEGACY_KEY = 'lang';

  var BRANDS = {
    ru: { brand: '{AI}-шница', brandGen: '{AI}-шницы', brandAcc: '{AI}-шницу', brandPrep: '{AI}-шнице' },
    en: { brand: 'Sunny-side AI', brandGen: 'Sunny-side AI', brandAcc: 'Sunny-side AI', brandPrep: 'Sunny-side AI' }
  };

  /** Пути к логотипам: RU — assets/brand/svg, EN — assets/brand/en/svg (Sunny-side-{AI}). */
  function brandSrc(kind, theme) {
    var th = theme === 'dark' ? 'dark' : 'light';
    var base = LANG === 'en' ? '/assets/brand/en/svg/' : '/assets/brand/svg/';
    if (kind === 'icon') return base + 'icon-' + th + '.svg';
    if (kind === 'stacked') return base + 'logo-stacked-' + th + '.svg';
    if (kind === 'wordmark') return base + 'wordmark-' + th + '.svg';
    if (kind === 'lockup') return base + 'lockup-' + th + '.svg';
    // logo (полный логотип) — auth и крупные места
    return base + 'logo-' + th + '.svg';
  }

  function detectBrandKind(img) {
    var explicit = img.getAttribute('data-brand');
    if (explicit) return explicit;
    var src = img.getAttribute('src') || '';
    var cls = ' ' + (img.className || '') + ' ';
    // auth / полноразмерный logo-* (не logo-stacked)
    if (/assets\/auth\/logo/.test(src) || /\/logo-(light|dark)\.svg/.test(src)) return 'logo';
    if (/\/icon-|brand-mark|hdr-logo-icon|\bic-light\b|\bic-dark\b|\/icon-(light|dark)\.svg/.test(src + cls)) return 'icon';
    if (/logo-stacked|hero-brand/.test(src + cls)) return 'stacked';
    if (/lockup|wordmark|hdr-logo-lockup|ft-logo|brand-logo|logo-img/.test(src + cls)) return 'lockup';
    return 'logo';
  }

  function detectBrandTheme(img) {
    var t = img.getAttribute('data-brand-theme');
    if (t === 'light' || t === 'dark') return t;
    var src = img.getAttribute('src') || '';
    var cls = ' ' + (img.className || '') + ' ';
    if (/-dark\b|logo-dark|brand-logo-dark|brand-mark-dark|hero-brand-dark/.test(src + ' ' + cls)) return 'dark';
    return 'light';
  }

  function syncBrandAssets(root) {
    root = root || document;
    var imgs = root.querySelectorAll
      ? root.querySelectorAll('img[src*="assets/brand/"], img[src*="assets/auth/logo"], img[data-brand]')
      : [];
    for (var i = 0; i < imgs.length; i++) {
      var img = imgs[i];
      var kind = detectBrandKind(img);
      var theme = detectBrandTheme(img);
      var next = brandSrc(kind, theme);
      if (img.getAttribute('src') !== next) img.setAttribute('src', next);
    }
    if (typeof document !== 'undefined') {
      var favSvg = document.querySelector('link[rel="icon"][type="image/svg+xml"]');
      if (favSvg) favSvg.href = LANG === 'en' ? '/assets/brand/en/favicon.svg' : '/assets/brand/favicon.svg';
      var favIco = document.querySelector('link[rel="icon"][sizes="any"]');
      if (favIco) favIco.href = LANG === 'en' ? '/assets/brand/en/favicon.ico' : '/assets/brand/favicon.ico';
    }
  }

  function normLang(v) {
    var l = String(v == null ? '' : v).toLowerCase().slice(0, 2);
    return SUPPORTED.indexOf(l) >= 0 ? l : null;
  }
  function lsGet(k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* private mode */ } }

  function resolveLang() {
    var fromUrl = null;
    try { fromUrl = normLang(new URLSearchParams(window.location.search).get('lang')); } catch (e) { /* old browser */ }
    if (fromUrl) { lsSet(STORE_KEY, fromUrl); return fromUrl; }   // ?lang= запоминаем — выбор живёт между страницами
    return normLang(lsGet(STORE_KEY))
      || normLang(lsGet(LEGACY_KEY))
      || normLang(navigator.language || (navigator.languages && navigator.languages[0]))
      || 'ru';
  }

  var LANG = resolveLang();
  var PR = new Intl.PluralRules(LANG);
  var warned = {};
  var lastPick = {};

  function dict(l) {
    return (l === 'en' ? window.AISH_DICT_EN : window.AISH_DICT_RU) || {};
  }
  function warnOnce(msg) {
    if (warned[msg]) return;
    warned[msg] = 1;
    if (window.console && console.warn) console.warn('[i18n] ' + msg);
  }

  function t(key, params) {
    var p = params || {};
    var v = dict(LANG)[key];
    if (v === undefined) {
      v = dict('ru')[key];
      warnOnce(v === undefined ? 'missing key: ' + key : 'no "' + LANG + '" translation, fallback to ru: ' + key);
    }
    if (v === undefined) return String(key);

    if (Array.isArray(v)) {
      if (!v.length) return '';
      var i = Math.floor(Math.random() * v.length);
      if (v.length > 1 && lastPick[key] === i) i = (i + 1) % v.length;
      lastPick[key] = i;
      v = v[i];
    }
    if (v && typeof v === 'object') {
      var n = Number(p.n);
      var cat = PR.select(isNaN(n) ? 0 : n);
      v = v[cat] !== undefined ? v[cat] : v.other;
      if (v === undefined) return String(key);
    }
    v = String(v);

    var forms = BRANDS[LANG];
    return v.replace(/\{(\w+)\}/g, function (m, k) {
      if (Object.prototype.hasOwnProperty.call(p, k) && p[k] != null) return String(p[k]);
      if (Object.prototype.hasOwnProperty.call(forms, k)) return forms[k];
      return m;
    });
  }

  function parseParams(el) {
    var raw = el.getAttribute('data-i18n-params');
    if (!raw) return undefined;
    try { return JSON.parse(raw); } catch (e) { return undefined; }
  }

  function collect(root, sel) {
    var out = [];
    if (root.nodeType === 1 && root.matches && root.matches(sel)) out.push(root);
    if (root.querySelectorAll) {
      var list = root.querySelectorAll(sel);
      for (var i = 0; i < list.length; i++) out.push(list[i]);
    }
    return out;
  }

  function applyI18n(root) {
    root = root || document;
    document.documentElement.lang = LANG;

    collect(root, '[data-i18n]').forEach(function (el) {
      el.textContent = t(el.getAttribute('data-i18n'), parseParams(el));
    });
    collect(root, '[data-i18n-html]').forEach(function (el) {
      el.innerHTML = t(el.getAttribute('data-i18n-html'), parseParams(el));
    });
    collect(root, '[data-i18n-attr]').forEach(function (el) {
      var params = parseParams(el);
      el.getAttribute('data-i18n-attr').split(';').forEach(function (pair) {
        pair = pair.trim();
        if (!pair) return;
        var idx = pair.indexOf(':');
        if (idx < 1) return;
        el.setAttribute(pair.slice(0, idx).trim(), t(pair.slice(idx + 1).trim(), params));
      });
    });

    if (root === document || root === document.documentElement || root === document.body) {
      var holder = document.body && document.body.getAttribute('data-title-key')
        ? document.body
        : (document.documentElement.getAttribute('data-title-key') ? document.documentElement : null);
      if (holder) document.title = t(holder.getAttribute('data-title-key'));
    }
  }

  function updateLangLabels() {
    var cur = LANG.toUpperCase();
    var next = (LANG === 'ru' ? 'en' : 'ru').toUpperCase();
    var i;
    var foot = document.querySelectorAll('[data-footer-lang-label]');
    for (i = 0; i < foot.length; i++) foot[i].textContent = next;
    var btns = document.querySelectorAll('button.lang');
    for (i = 0; i < btns.length; i++) {
      btns[i].textContent = cur;
      btns[i].setAttribute('aria-label', t('common.lang.aria'));
    }
    var togglers = document.querySelectorAll('[data-lang-toggle]');
    for (i = 0; i < togglers.length; i++) {
      if (!togglers[i].hasAttribute('aria-label')) togglers[i].setAttribute('aria-label', t('common.lang.aria'));
    }
  }

  function setLang(l) {
    var n = normLang(l);
    if (!n) return LANG;
    LANG = n;
    PR = new Intl.PluralRules(LANG);
    lsSet(STORE_KEY, n);
    document.documentElement.lang = n;
    api.LANG = n;
    api.BRAND = BRANDS[n].brand;
    return n;
  }

  function locale() { return LANG === 'en' ? 'en-US' : 'ru-RU'; }

  function money(rub) {
    var v = Number(rub);
    if (!isFinite(v)) v = 0;
    var frac = Math.round(v * 100) % 100 !== 0;
    try {
      return new Intl.NumberFormat(locale(), {
        style: 'currency', currency: 'RUB', currencyDisplay: 'narrowSymbol',
        minimumFractionDigits: frac ? 2 : 0, maximumFractionDigits: frac ? 2 : 0
      }).format(v);
    } catch (e) {
      return LANG === 'en' ? '\u20BD' + v : v + '\u00A0\u20BD';
    }
  }

  function num(n) {
    var v = Number(n);
    if (!isFinite(v)) v = 0;
    try {
      return new Intl.NumberFormat(locale(), { notation: Math.abs(v) > 9999 ? 'compact' : 'standard' }).format(v);
    } catch (e) {
      return String(v);
    }
  }

  function ago(ts) {
    var ms = ts instanceof Date ? ts.getTime() : (typeof ts === 'string' ? Date.parse(ts) : Number(ts));
    if (!isFinite(ms)) return '';
    var m = Math.round((ms - Date.now()) / 60000);      // минуты: <0 — прошлое
    var abs = Math.abs(m);
    if (abs < 1) return t('common.time.now');
    var rtf;
    try { rtf = new Intl.RelativeTimeFormat(locale(), { numeric: 'auto' }); } catch (e) { return ''; }
    if (abs < 60) return rtf.format(m, 'minute');
    if (abs < 1440) return rtf.format(Math.round(m / 60), 'hour');
    var d = Math.round(m / 1440);
    if (Math.abs(d) < 7) return rtf.format(d, 'day');
    if (Math.abs(d) < 35) return rtf.format(Math.round(d / 7), 'week');
    if (Math.abs(d) < 365) return rtf.format(Math.round(d / 30), 'month');
    return rtf.format(Math.round(d / 365), 'year');
  }

  var api = {
    LANG: LANG,
    BRAND: BRANDS[LANG].brand,
    BRAND_FORMS: BRANDS,
    t: t,
    applyI18n: applyI18n,
    setLang: setLang,
    money: money,
    num: num,
    ago: ago,
    brandSrc: brandSrc,
    syncBrandAssets: syncBrandAssets
  };
  window.AISH_I18N = api;

  // переключатель языка: делегирование — работает и для кнопок, нарисованных из JS
  document.addEventListener('click', function (e) {
    var el = e.target && e.target.closest ? e.target.closest('[data-lang-toggle]') : null;
    if (!el) return;
    if (el.tagName === 'A') e.preventDefault();
    setLang(LANG === 'ru' ? 'en' : 'ru');
    window.location.reload();
  });

  function init() {
    applyI18n(document);
    syncBrandAssets(document);
    updateLangLabels();
  }
  document.documentElement.lang = LANG;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
