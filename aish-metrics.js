/* Метрики сайта {AI}-шницы: анонимные события страниц → POST /api/m (отчёт — /admin/metrics).
 *
 * Что пишем: какая страница открыта, сколько на ней пробыли, шаги генерации (идея → модели → «Сгенерировать» →
 * результат / ошибка), где человек ушёл. Кто: vid — случайный id браузера (localStorage), sid — визит (новый после
 * 30 минут тишины). Текст промптов, имена файлов и e-mail не отправляем.
 *
 *   AishM.track('gen_fail', { model: 'seedance-2-5', code: 'moderation' });
 *   AishM.pending(+1) / AishM.pending(-1) — генерация идёт (если человек закроет вкладку — «ушёл, не дождавшись»).
 * Отключить на своём браузере (например, админу): localStorage['aish-no-metrics'] = '1'.
 */
(function (root) {
  'use strict';
  if (root.AishM) return;
  var IDLE = 30 * 60 * 1000, MAX_Q = 12, FLUSH_MS = 5000, URL = '/api/m';
  var noop = { track: function () {}, pending: function () {}, flush: function () {}, vid: '', sid: '' };
  var ls;
  try { ls = root.localStorage; if (ls.getItem('aish-no-metrics') === '1') { root.AishM = noop; return; } } catch (e) { ls = null; }

  function rid() {
    var a = new Uint8Array(12), s = '';
    try { (root.crypto || root.msCrypto).getRandomValues(a); } catch (e) { for (var j = 0; j < a.length; j++) a[j] = Math.floor(Math.random() * 256); }
    for (var i = 0; i < a.length; i++) s += ('0' + a[i].toString(36)).slice(-2);
    return s.slice(0, 20);
  }
  function get(k) { try { return ls ? ls.getItem(k) : null; } catch (e) { return null; } }
  function set(k, v) { try { if (ls) ls.setItem(k, v); } catch (e) {} }

  var vid = get('aish-vid');
  if (!vid || !/^[A-Za-z0-9_-]{8,32}$/.test(vid)) { vid = rid(); set('aish-vid', vid); }
  var sid = get('aish-sid'), last = +(get('aish-sid-t') || 0), now0 = Date.now();
  if (!sid || !last || now0 - last > IDLE) { sid = rid(); set('aish-sid', sid); }
  set('aish-sid-t', String(now0));

  var q = [], timer = 0, pend = 0, errs = 0;
  var page = location.pathname || '/';
  var shownAt = Date.now(), visibleMs = 0, maxScroll = 0;

  function send(useBeacon) {
    clearTimeout(timer); timer = 0;
    if (!q.length) return;
    var t = Date.now();
    var body = JSON.stringify({ vid: vid, sid: sid, events: q.splice(0, 40).map(function (e) { return { n: e.n, page: e.page, ago: t - e.t, p: e.p }; }) });
    set('aish-sid-t', String(t));
    try {
      if (useBeacon && navigator.sendBeacon && navigator.sendBeacon(URL, new Blob([body], { type: 'application/json' }))) return;
    } catch (e) {}
    try { fetch(URL, { method: 'POST', body: body, headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin', keepalive: true }).catch(function () {}); } catch (e) {}
  }
  function track(n, p) {
    if (!n) return;
    q.push({ n: String(n), page: page, t: Date.now(), p: p && typeof p === 'object' ? p : {} });
    set('aish-sid-t', String(Date.now()));
    if (q.length >= MAX_Q) send(false);
    else if (!timer) timer = setTimeout(function () { send(false); }, FLUSH_MS);
  }

  // ── просмотр страницы: откуда пришли, utm, язык, ширина экрана, тема
  (function () {
    var p = {};
    try {
      var r = document.referrer ? new URL(document.referrer) : null;
      if (r && r.host !== location.host) p.ref = r.host.replace(/^www\./, '');
    } catch (e) {}
    try {
      var sp = new URLSearchParams(location.search);
      ['utm_source', 'utm_medium', 'utm_campaign'].forEach(function (k) { if (sp.get(k)) p[k] = sp.get(k).slice(0, 60); });
    } catch (e) {}
    p.lang = String(document.documentElement.lang || navigator.language || '').slice(0, 2);
    p.w = Math.round((root.innerWidth || 0) / 10) * 10;
    var st = document.documentElement.getAttribute('data-style'); if (st) p.theme = st;
    track('page_view', p);
  })();

  // ── время на странице и глубина прокрутки
  function onScroll() {
    var h = (document.documentElement.scrollHeight || 1) - (root.innerHeight || 0);
    var pct = h > 0 ? Math.round(100 * (root.scrollY || 0) / h) : 100;
    if (pct > maxScroll) maxScroll = Math.min(100, pct);
  }
  root.addEventListener('scroll', onScroll, { passive: true });
  var left = false;
  function leave() {
    if (left) return;
    left = true;
    if (shownAt) visibleMs += Date.now() - shownAt;
    shownAt = 0;
    track('page_leave', { ms: visibleMs, scroll: maxScroll, pending: pend > 0 });
    send(true);
  }
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') {
      if (shownAt) { visibleMs += Date.now() - shownAt; shownAt = 0; }
      if (q.length) send(true);
    } else {
      shownAt = Date.now();
      left = false;
    }
  });
  root.addEventListener('pagehide', leave);

  // ── ошибки JS (не больше 3 на страницу)
  root.addEventListener('error', function (e) {
    if (errs >= 3 || !e) return;
    errs += 1;
    var src = String(e.filename || '').split('/').pop().split('?')[0];
    track('js_error', { msg: String(e.message || 'error').slice(0, 120), src: src });
  });

  root.AishM = {
    track: track,
    pending: function (d) { pend = Math.max(0, pend + (d || 0)); },
    flush: function () { send(true); },
    vid: vid, sid: sid
  };
})(typeof window !== 'undefined' ? window : this);
