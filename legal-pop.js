/* Политики открываются окном поверх текущей страницы и закрываются обратно на неё. */
(function () {
  var OK = /^\/legal\/[a-z0-9-]+\.html$/;
  var cache = {};
  var root = null;
  var body = null;
  var openPath = '';

  function pathOf(href, base) {
    try {
      var u = new URL(String(href || ''), base || location.href);
      if (u.origin !== location.origin) return '';
      return OK.test(u.pathname) ? u.pathname : '';
    } catch (e) { return ''; }
  }

  function cameFrom() {
    try {
      if (!document.referrer) return '';
      var u = new URL(document.referrer);
      if (u.origin !== location.origin) return '';
      if (OK.test(u.pathname)) return '';
      return u.pathname + u.search + u.hash;
    } catch (e) { return ''; }
  }

  function ensure() {
    if (root) return;
    var css = document.createElement('style');
    css.textContent = '.lpop{position:fixed;inset:0;z-index:200;display:flex;align-items:center;justify-content:center;padding:16px;background:rgba(15,16,22,.55)}'
      + '.lpop[hidden]{display:none}'
      + '.lpop__card{position:relative;width:min(560px,100%);max-height:min(86dvh,740px);display:flex;flex-direction:column;border-radius:22px;background:#fff;color:#0F1016;box-shadow:0 28px 70px -24px rgba(0,0,0,.55);overflow:hidden}'
      + '.lpop__x{position:absolute;top:8px;right:8px;z-index:2;width:28px;height:28px;border:none;border-radius:8px;background:transparent;color:#646673;display:flex;align-items:center;justify-content:center;cursor:pointer;padding:0}'
      + '.lpop__x svg{width:14px;height:14px;display:block}'
      + '.lpop__x:hover{background:rgba(18,20,32,.06);color:#0F1016}'
      + '.lpop__body{overflow:auto;padding:16px 20px 20px;font:15px/1.5 Onest,system-ui,sans-serif}'
      + '.lpop__body h1,.lpop__body .inner-title{font-family:"Days One",Onest,sans-serif;font-weight:400;font-size:26px;line-height:1.2;margin:4px 28px 8px 0}'
      + '.lpop__body h2{font-size:16px;margin:16px 0 6px}'
      + '.lpop__body p{margin:0 0 10px;color:#4B4D59}'
      + '.lpop__body a{color:#0F1016}'
      + '.lpop__body .legal-updated{font-size:13px;color:#646673}'
      + '.lpop__body .legal-nav{display:flex;flex-wrap:wrap;gap:8px 14px;margin-top:16px}'
      + '.lpop__body .legal-nav a{font-weight:700}'
      + '.lpop__wait{margin:12px 0;color:#4B4D59}'
      + 'html[data-theme="dark"] .lpop__card,html[data-style="black"] .lpop__card,html[data-style="violet"] .lpop__card{background:#202125;color:#F3F4F6}'
      + 'html[data-theme="dark"] .lpop__x,html[data-style="black"] .lpop__x,html[data-style="violet"] .lpop__x{background:transparent;color:#A8ABB2}'
      + 'html[data-theme="dark"] .lpop__x:hover,html[data-style="black"] .lpop__x:hover,html[data-style="violet"] .lpop__x:hover{background:rgba(255,255,255,.08);color:#F3F4F6}'
      + 'html[data-theme="dark"] .lpop__body p,html[data-style="black"] .lpop__body p,html[data-style="violet"] .lpop__body p{color:#A8ABB2}'
      + 'html[data-theme="dark"] .lpop__body a,html[data-style="black"] .lpop__body a,html[data-style="violet"] .lpop__body a{color:#E7EDB0}';
    document.head.appendChild(css);
    root = document.createElement('div');
    root.className = 'lpop';
    root.hidden = true;
    root.innerHTML = '<div class="lpop__card" role="dialog" aria-modal="true" aria-label="Документ"><button type="button" class="lpop__x" aria-label="Закрыть"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button><div class="lpop__body"></div></div>';
    document.body.appendChild(root);
    body = root.querySelector('.lpop__body');
    root.querySelector('.lpop__x').addEventListener('click', close);
    root.addEventListener('click', function (e) {
      if (e.target === root) { close(); return; }
      var a = e.target.closest('a');
      if (!a || !root.contains(a)) return;
      var p = pathOf(a.getAttribute('href'), location.origin + openPath);
      if (!p) return;
      e.preventDefault();
      open(p);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && root && !root.hidden) close();
    });
  }

  function close() {
    if (!root) return;
    root.hidden = true;
    openPath = '';
  }

  function paint(path, html) {
    ensure();
    openPath = path;
    body.innerHTML = html;
    body.scrollTop = 0;
    root.hidden = false;
  }

  function open(path) {
    if (!OK.test(path)) return;
    if (cache[path]) { paint(path, cache[path]); return; }
    paint(path, '<p class="lpop__wait">Открываем…</p>');
    fetch(path, { credentials: 'same-origin' }).then(function (res) {
      if (!res.ok) throw new Error('http');
      return res.text();
    }).then(function (html) {
      var parsed = new DOMParser().parseFromString(html, 'text/html');
      var wrap = parsed.querySelector('.legal-wrap');
      if (!wrap) throw new Error('empty');
      wrap.querySelectorAll('script,style,.legal-kicker').forEach(function (n) { n.remove(); });
      wrap.querySelectorAll('a').forEach(function (a) {
        var next = pathOf(a.getAttribute('href'), location.origin + path);
        if (next) a.setAttribute('href', next);
      });
      cache[path] = wrap.innerHTML;
      if (openPath === path) paint(path, cache[path]);
    }).catch(function () {
      if (openPath === path) paint(path, '<p class="lpop__wait">Не удалось открыть документ.</p>');
    });
  }

  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a');
    if (!a || a.closest('.consent-pop') || a.closest('.lpop')) return;
    var p = pathOf(a.getAttribute('href'));
    if (!p || p === location.pathname) return;
    e.preventDefault();
    e.stopPropagation();
    open(p);
  }, true);

  function fixReturn() {
    if (!OK.test(location.pathname)) return;
    var back = cameFrom();
    document.querySelectorAll('a.nav-link, .legal-kicker a').forEach(function (a) {
      var href = a.getAttribute('href') || '';
      if (href.indexOf('index.html') === -1 && href !== '/' && href !== '../') return;
      if (back) a.setAttribute('href', back);
      else a.addEventListener('click', function (ev) {
        if (history.length > 1) { ev.preventDefault(); history.back(); }
      });
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fixReturn);
  else fixReturn();

  window.AishLegal = { open: open, close: close };
})();
