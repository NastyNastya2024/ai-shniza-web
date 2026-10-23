/* Темы {AI}-шница UI: Белый / Чёрный (новые) + Светлый / Фиолетовый (нынешние) — общие для всех страниц.
 *
 * Подключается в <head> БЕЗ defer, до стилей страницы: сразу ставит <html data-style="…">, чтобы не было вспышки.
 *
 * Выбор хранится в localStorage['aish-style']. Старые ключи (aish-vitrina-theme, theme, aish-theme = light|dark)
 * пишутся тоже: страницы, которые знают только светлую/тёмную, работают как раньше.
 *   white, light → light;  black, violet → dark   (light и violet — нынешние светлая и тёмная темы, без изменений)
 * Старый сохранённый выбор сохраняется: light → light, dark → violet. Новым посетителям — white.
 * ?style=white|black|light|violet в адресе перекрывает выбор; старый ?theme=dark|light тоже понимается.
 *
 * Переключатель — ОДИН плавающий кружок поверх страницы: нажатие открывает меню тем, кружок можно перетащить
 * мышкой или пальцем, место запоминается (localStorage['aish-style-pos']). Создаётся сам на каждой странице.
 *
 * API: AishStyle.get() · mode() · isDark() · ground() · set(style) · onChange(fn) · mount(el) — прячет старую кнопку темы
 */
(function () {
  'use strict';
  var STYLES = ['white', 'black', 'light', 'violet'];
  var LABEL = {
    ru: { white: 'Белый', black: 'Чёрный', light: 'Светлый', violet: 'Фиолетовый', aria: 'Тема оформления', hint: 'Тема · можно перетащить' },
    en: { white: 'White', black: 'Black', light: 'Light', violet: 'Violet', aria: 'Color theme', hint: 'Theme · drag to move' }
  };
  var GROUND = { white: '#ECECF3', black: '#131415', light: '#EEEAF8', violet: '#15122A' };
  var ORB_SUFFIX = { black: '-lime' };   // Чёрный: оранжевый желток с салатовым бликом
  var KEY = 'aish-style', POS = 'aish-style-pos';
  var root = document.documentElement;
  var subs = [];

  function ls(k, v) {
    try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; }
    return null;
  }
  function valid(s) { return STYLES.indexOf(s) >= 0; }
  function modeOf(s) { return s === 'white' || s === 'light' ? 'light' : 'dark'; }
  function lang() {
    var l = String((window.AISH_I18N && window.AISH_I18N.LANG) || root.lang || 'ru').slice(0, 2).toLowerCase();
    return l === 'en' ? 'en' : 'ru';
  }

  function initial() {
    var q = null, qt = null;
    try { var p = new URLSearchParams(location.search); q = p.get('style'); qt = p.get('theme'); } catch (e) {}
    if (valid(q)) return q;
    if (qt === 'dark') return 'violet';
    if (qt === 'light') return 'light';
    var saved = ls(KEY);
    if (valid(saved)) return saved;
    var old = ls('aish-vitrina-theme') || ls('theme') || ls('aish-theme');   // перенос старого выбора
    if (old === 'dark') return 'violet';
    if (old === 'light') return 'light';
    return 'white';
  }
  var cur = initial();

  function apply(s) {
    var m = modeOf(s);
    root.setAttribute('data-style', s);
    if (root.getAttribute('data-theme') !== 'lilac') root.setAttribute('data-theme', m);   // страницы на data-theme
    root.style.colorScheme = m;
    ls(KEY, s);
    ls('aish-vitrina-theme', m); ls('theme', m); ls('aish-theme', m);
    swapOrbs(document);
  }

  /* Шар-маскот: в Чёрной — оранжевый желток с салатовым бликом (orb-*-lime). */
  var ORB_RX = /(^|\/)assets\/(orb(?:-no-eyes|-sm)?)(-cold|-lime)?\.png(\?.*)?$/;
  function swapImg(img) {
    var src = img.getAttribute('src') || '';
    var m = ORB_RX.exec(src);
    if (!m) return;
    var want = ORB_SUFFIX[cur] || '';
    if ((m[3] || '') === want) return;
    img.setAttribute('src', src.replace(ORB_RX, m[1] + 'assets/' + m[2] + want + '.png' + (m[4] || '')));
  }
  function swapOrbs(scope) {
    if (!scope || !scope.querySelectorAll) return;
    if (scope.tagName === 'IMG') { swapImg(scope); return; }
    Array.prototype.forEach.call(scope.querySelectorAll('img[src*="assets/orb"]'), swapImg);
  }

  function set(s) {
    if (!valid(s) || s === cur) return;
    cur = s;
    apply(s);
    paint();
    subs.forEach(function (fn) { try { fn(s, modeOf(s)); } catch (e) {} });
    try { document.dispatchEvent(new CustomEvent('aish:style', { detail: { style: s, mode: modeOf(s) } })); } catch (e) {}
  }

  /* ── кружок: плавающий или в панели (mount replace) ───────────── */
  var fab = null, menu = null, docked = false;

  function paint() {
    if (!fab) return;
    var L = LABEL[lang()];
    fab.querySelector('.aish-fab__dot').className = 'aish-fab__dot aish-style__dot--' + cur;
    fab.setAttribute('aria-label', L.aria + ': ' + L[cur]);
    fab.title = docked ? (L.aria + ': ' + L[cur]) : L.hint;
    Array.prototype.forEach.call(menu.querySelectorAll('[data-style-opt]'), function (b) {
      var on = b.getAttribute('data-style-opt') === cur;
      b.classList.toggle('is-on', on);
      b.setAttribute('aria-checked', on ? 'true' : 'false');
    });
  }

  function readPos() {
    try { var p = JSON.parse(ls(POS) || 'null'); if (p && isFinite(p.x) && isFinite(p.y)) return p; } catch (e) {}
    return null;
  }
  function place(fx, fy) {   // fx, fy — доля ширины/высоты окна (0…1) для центра кружка
    var w = window.innerWidth, h = window.innerHeight, r = 24, pad = 10;
    var x = Math.min(w - r - pad, Math.max(r + pad, fx * w));
    var y = Math.min(h - r - pad, Math.max(r + pad, fy * h));
    fab.style.left = (x - r) + 'px';
    fab.style.top = (y - r) + 'px';
    return { x: x / w, y: y / h };
  }
  function defaultPos() { return window.innerWidth <= 760 ? { x: 0.92, y: 0.62 } : { x: 0.985, y: 0.5 }; }

  function openMenu() {
    menu.hidden = false;
    fab.setAttribute('aria-expanded', 'true');
    var fr = fab.getBoundingClientRect(), mw = menu.offsetWidth, mh = menu.offsetHeight;
    var left, top;
    if (docked) {
      // меню под кнопкой в шапке панели (или справа, если не влезает вниз)
      left = Math.max(8, Math.min(window.innerWidth - mw - 8, fr.left));
      top = fr.bottom + 8;
      if (top + mh > window.innerHeight - 8) top = Math.max(8, fr.top - mh - 8);
    } else {
      left = fr.left + fr.width / 2 > window.innerWidth / 2 ? fr.left - mw - 10 : fr.right + 10;
      top = Math.min(window.innerHeight - mh - 8, Math.max(8, fr.top + fr.height / 2 - mh / 2));
      left = Math.max(8, Math.min(window.innerWidth - mw - 8, left));
    }
    menu.style.left = left + 'px';
    menu.style.top = top + 'px';
    var on = menu.querySelector('.is-on') || menu.querySelector('button');
    if (on) on.focus();
  }
  function closeMenu(focusFab) {
    if (menu.hidden) return;
    menu.hidden = true;
    fab.setAttribute('aria-expanded', 'false');
    if (focusFab) fab.focus();
  }

  function build() {
    if (fab || !document.body) return;
    var L = LABEL[lang()];
    fab = document.createElement('button');
    fab.type = 'button';
    fab.className = 'aish-fab';
    fab.setAttribute('aria-haspopup', 'true');
    fab.setAttribute('aria-expanded', 'false');
    fab.innerHTML = '<span class="aish-fab__dot"></span>';
    menu = document.createElement('div');
    menu.className = 'aish-fab__menu';
    menu.setAttribute('role', 'radiogroup');
    menu.setAttribute('aria-label', L.aria);
    menu.hidden = true;
    STYLES.forEach(function (s) {
      var b = document.createElement('button');
      b.type = 'button';
      b.setAttribute('role', 'radio');
      b.setAttribute('data-style-opt', s);
      b.className = 'aish-fab__opt';
      b.innerHTML = '<span class="aish-style__dot aish-style__dot--' + s + '"></span><span>' + L[s] + '</span><span class="aish-fab__check" aria-hidden="true">✓</span>';
      b.addEventListener('click', function () { set(s); closeMenu(true); });
      menu.appendChild(b);
    });
    menu.addEventListener('keydown', function (e) {
      var opts = Array.prototype.slice.call(menu.querySelectorAll('button'));
      var i = opts.indexOf(document.activeElement);
      if (e.key === 'Escape') { e.preventDefault(); closeMenu(true); }
      else if (e.key === 'ArrowDown' || e.key === 'ArrowRight') { e.preventDefault(); opts[(i + 1) % opts.length].focus(); }
      else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') { e.preventDefault(); opts[(i + opts.length - 1) % opts.length].focus(); }
    });
    document.body.appendChild(fab);
    document.body.appendChild(menu);

    var pos = place.apply(null, (function (p) { return [p.x, p.y]; })(readPos() || defaultPos()));

    // перетаскивание только в плавающем режиме; в панели — обычная кнопка
    var drag = null;
    fab.addEventListener('pointerdown', function (e) {
      if (docked) return;
      if (e.button !== undefined && e.button !== 0) return;
      var r = fab.getBoundingClientRect();
      drag = { id: e.pointerId, dx: e.clientX - r.left, dy: e.clientY - r.top, x0: e.clientX, y0: e.clientY, moved: false };
      try { fab.setPointerCapture(e.pointerId); } catch (_) {}
    });
    fab.addEventListener('pointermove', function (e) {
      if (docked || !drag || e.pointerId !== drag.id) return;
      if (!drag.moved && Math.abs(e.clientX - drag.x0) + Math.abs(e.clientY - drag.y0) < 6) return;
      if (!drag.moved) { drag.moved = true; fab.classList.add('is-drag'); closeMenu(false); }
      e.preventDefault();
      pos = place((e.clientX - drag.dx + 24) / window.innerWidth, (e.clientY - drag.dy + 24) / window.innerHeight);
    });
    function end(e) {
      if (docked || !drag || (e && e.pointerId !== drag.id)) return;
      var moved = drag.moved;
      drag = null;
      fab.classList.remove('is-drag');
      if (moved) { ls(POS, JSON.stringify(pos)); fab._skipClick = true; setTimeout(function () { fab._skipClick = false; }, 0); }
    }
    fab.addEventListener('pointerup', end);
    fab.addEventListener('pointercancel', end);
    fab.addEventListener('click', function () {
      if (fab._skipClick) return;
      if (menu.hidden) openMenu(); else closeMenu(false);
    });
    fab.addEventListener('keydown', function (e) {
      if (docked) return;
      var step = e.shiftKey ? 0.1 : 0.03, d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
      if (!d) return;
      e.preventDefault();
      pos = place(pos.x + d[0], pos.y + d[1]);
      ls(POS, JSON.stringify(pos));
    });
    document.addEventListener('pointerdown', function (e) {
      if (!menu.hidden && !menu.contains(e.target) && e.target !== fab && !fab.contains(e.target)) closeMenu(false);
    }, true);
    window.addEventListener('resize', function () {
      if (!docked) pos = place(pos.x, pos.y);
      if (!menu.hidden) openMenu();
    });
    paint();
  }

  function watch() {
    swapOrbs(document);
    build();
    if (!window.MutationObserver || !document.body) return;
    new MutationObserver(function (list) {
      list.forEach(function (r) {
        if (r.type === 'attributes') swapImg(r.target);
        else Array.prototype.forEach.call(r.addedNodes, function (n) { if (n.nodeType === 1) swapOrbs(n); });
      });
    }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['src'] });
  }

  /** Вставить кружок на место старой кнопки темы (луна/солнце). opts.replace — в панель; opts.compact — размер как у icon-btn.
   *  Можно вызывать повторно с другим el — кружок переедет (например, когда панель чатов скрыта). */
  var dockHost = null;
  function mount(el, opts) {
    if (!el) return null;
    opts = opts || {};
    build();
    if (!fab) return null;
    if (dockHost && dockHost !== el) {
      dockHost.style.display = '';
      dockHost.removeAttribute('aria-hidden');
      dockHost.tabIndex = 0;
    }
    dockHost = el;
    el.style.display = 'none';
    el.setAttribute('aria-hidden', 'true');
    el.tabIndex = -1;
    if (opts.header) {
      docked = true;
      fab.classList.add('is-header');
      fab.classList.remove('is-docked', 'is-compact');
      fab.style.left = '';
      fab.style.top = '';
      fab.style.touchAction = 'manipulation';
      fab.style.cursor = 'pointer';
      if (el.parentNode) el.parentNode.insertBefore(fab, el);
      if (menu.parentNode !== document.body) document.body.appendChild(menu);
      paint();
      return fab;
    }
    if (opts.replace !== false) {
      docked = true;
      fab.classList.add('is-docked');
      fab.classList.remove('is-header');
      fab.classList.toggle('is-compact', !!opts.compact);
      fab.style.left = '';
      fab.style.top = '';
      fab.style.touchAction = 'manipulation';
      fab.style.cursor = 'pointer';
      if (el.parentNode) el.parentNode.insertBefore(fab, el);
      if (menu.parentNode !== document.body) document.body.appendChild(menu);
      paint();
    }
    return fab;
  }

  apply(cur);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', watch); else watch();

  window.AishStyle = {
    STYLES: STYLES,
    get: function () { return cur; },
    mode: function () { return modeOf(cur); },
    isDark: function () { return modeOf(cur) === 'dark'; },
    ground: function () { return GROUND[cur]; },
    set: set,
    mount: mount,
    onChange: function (fn) { if (typeof fn === 'function') subs.push(fn); }
  };
})();
