/* Подключения MCP ({AI}-шница).
 * Кабинет:  AishMcp.account(el)          — раздел «Подключения» (/account#mcp): добавить сервер по адресу, войти, отметить кнопки.
 * Студия:   AishMcp.offer(payload, app)  — после результата генерации: кнопки отмеченных инструментов под результатом.
 *           AishMcp.open(value, app)     — форма инструмента (поля уже заполнены результатом) → «Выполнить» → ответ в чат.
 * API: /api/mcp* (mcp_routes.py). Ничего не вызывается без нажатия человека: кнопка → форма → «Выполнить». */
(function () {
  'use strict';
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const safeHref = (u) => (/^https?:\/\//i.test(String(u || '')) ? String(u) : '');
  let csrfTok = '';
  async function csrf() {
    if (csrfTok) return csrfTok;
    const m = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
    if (m) return (csrfTok = decodeURIComponent(m[1]));
    try { const r = await fetch('/api/csrf', { credentials: 'same-origin' }); csrfTok = (await r.json()).csrf_token || ''; } catch (_) {}
    return csrfTok;
  }
  async function api(path, opts) {
    opts = opts || {};
    const method = (opts.method || 'GET').toUpperCase();
    const headers = { 'Content-Type': 'application/json' };
    if (method !== 'GET') headers['X-CSRF-Token'] = await csrf();
    let res, data = {};
    try {
      res = await fetch(path, { method: method, credentials: 'same-origin', headers: headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
      try { data = await res.json(); } catch (_) {}
    } catch (_) { return { res: { ok: false, status: 0 }, data: { message: 'Нет связи с сайтом' } }; }
    return { res: res, data: data || {} };
  }

  /* ───────────── стили (токены кита, с запасными значениями для страниц без него) */
  function css() {
    if (document.getElementById('aish-mcp-css')) return;
    const st = document.createElement('style');
    st.id = 'aish-mcp-css';
    st.textContent = [
      '.mcp-wrap{display:flex;flex-direction:column;gap:16px}',
      '.mcp-add{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr) auto;gap:10px;align-items:end}',
      '.mcp-add .mcp-tok{grid-column:1/-1}',
      '@media (max-width:640px){.mcp-add{grid-template-columns:1fr}}',
      '.mcp-card{border:1px solid var(--ys-line,rgba(91,53,224,.14));border-radius:18px;padding:14px 16px;display:flex;flex-direction:column;gap:10px;background:var(--ys-surface,var(--card,transparent))}',
      '.mcp-head{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center}',
      '.mcp-name{font-weight:800;font-size:16px;color:var(--ys-ink,var(--ink))}',
      '.mcp-host{font-size:13px;color:var(--ys-ink-3,var(--muted2));word-break:break-all}',
      '.mcp-st{font:700 12px Onest,system-ui,sans-serif;padding:3px 10px;border-radius:999px;background:var(--ys-sunken,var(--violet-bg));color:var(--ys-ink-2,var(--muted))}',
      '.mcp-st.ok{background:var(--ok-bg,rgba(22,121,76,.1));color:var(--ok,#16794C)}',
      '.mcp-st.bad{background:rgba(194,48,95,.1);color:var(--err,#C2305F)}',
      '.mcp-acts{display:flex;flex-wrap:wrap;gap:8px;margin-left:auto}',
      '.mcp-acts button{height:34px;padding:0 12px;border-radius:999px;border:1px solid var(--ys-line-strong,var(--field-brd,rgba(91,53,224,.25)));background:transparent;color:var(--ys-ink,var(--ink));font:700 12px Onest,system-ui,sans-serif;cursor:pointer}',
      '.mcp-acts button.pri{background:var(--ys-sel,var(--violet));color:var(--ys-on-sel,#fff);border-color:transparent}',
      '.mcp-err{font-size:13px;color:var(--err,#C2305F)}',
      '.mcp-tools{display:flex;flex-direction:column;gap:6px;max-height:340px;overflow:auto}',
      '.mcp-tool{display:flex;gap:10px;align-items:flex-start;padding:8px 10px;border-radius:12px;cursor:pointer}',
      '.mcp-tool:hover{background:var(--ys-hover,var(--violet-bg))}',
      '.mcp-tool input{margin-top:3px;flex:0 0 auto;width:18px;height:18px;accent-color:var(--violet,#5B35E0)}',
      '.mcp-tool b{font-size:14px;color:var(--ys-ink,var(--ink))}',
      '.mcp-tool small{display:block;font-size:12.5px;line-height:1.4;color:var(--ys-ink-3,var(--muted2))}',
      '.mcp-tag{display:inline-block;margin-left:6px;font:700 10.5px Onest,system-ui,sans-serif;padding:1px 7px;border-radius:999px;background:var(--ys-sunken,var(--violet-bg));color:var(--ys-ink-2,var(--muted));vertical-align:1px}',
      '.mcp-tag.warn{background:rgba(232,105,28,.12);color:var(--orange,#C2550F)}',
      '.mcp-empty{font-size:14px;color:var(--ys-ink-3,var(--muted2));padding:6px 0}',
      '.mcp-ov{position:fixed;inset:0;z-index:9000;background:rgba(10,8,20,.45);backdrop-filter:blur(6px);display:flex;align-items:center;justify-content:center;padding:16px}',
      '.mcp-dlg{width:min(560px,100%);max-height:calc(100vh - 32px);overflow:auto;background:var(--ys-raised,var(--bubble,#fff));color:var(--ys-ink,var(--ink,#1E1238));border-radius:24px;padding:20px;box-shadow:var(--ys-shadow-lg,0 30px 80px -30px rgba(0,0,0,.5));display:flex;flex-direction:column;gap:12px;font-family:Onest,system-ui,sans-serif}',
      '.mcp-dlg h3{margin:0;font:400 20px "Days One",Onest,system-ui,sans-serif}',
      '.mcp-dlg .mcp-sub{font-size:13px;color:var(--ys-ink-3,var(--muted2,#8A80B5))}',
      '.mcp-dlg label{display:flex;flex-direction:column;gap:5px;font-size:13px;font-weight:700}',
      '.mcp-dlg label.ck{flex-direction:row;align-items:center;gap:8px}',
      '.mcp-dlg label i{font-style:normal;font-weight:400;color:var(--ys-ink-3,var(--muted2,#8A80B5))}',
      '.mcp-dlg input:not([type=checkbox]),.mcp-dlg textarea,.mcp-dlg select{width:100%;box-sizing:border-box;padding:10px 12px;border-radius:12px;border:1px solid var(--ys-line-strong,var(--field-brd,rgba(91,53,224,.25)));background:var(--ys-sunken,var(--field,#fff));color:inherit;font:14px Onest,system-ui,sans-serif}',
      '.mcp-dlg textarea{min-height:84px;resize:vertical}',
      '.mcp-dlg .mcp-row{display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap}',
      '.mcp-dlg .mcp-row button{height:40px;padding:0 18px;border-radius:999px;border:1px solid var(--ys-line-strong,rgba(91,53,224,.25));background:transparent;color:inherit;font:700 14px Onest,system-ui,sans-serif;cursor:pointer}',
      '.mcp-dlg .mcp-row button.pri{background:var(--ys-sel,#5B35E0);color:var(--ys-on-sel,#fff);border-color:transparent}',
      '.mcp-dlg .mcp-row button:disabled{opacity:.6;cursor:default}',
      '.mcp-out{white-space:pre-wrap;word-break:break-word;font-size:14px;line-height:1.5;background:var(--ys-sunken,rgba(91,53,224,.06));border-radius:14px;padding:12px;max-height:260px;overflow:auto}',
      '.mcp-out.bad{color:var(--err,#C2305F)}',
      '.mcp-links a{display:block;font-size:13px;word-break:break-all;color:var(--violet,#5B35E0)}',
      '.mcp-imgs img{max-width:100%;border-radius:12px;margin-top:6px}',
      '.mcp-pres{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px}',
      '.mcp-pre{border:1px solid var(--ys-line,rgba(91,53,224,.14));border-radius:16px;padding:12px 14px;display:flex;flex-direction:column;gap:6px;background:var(--ys-surface,var(--card,transparent))}',
      '.mcp-pre b{font-size:15px;color:var(--ys-ink,var(--ink))}',
      '.mcp-pre small{font-size:12.5px;line-height:1.4;color:var(--ys-ink-3,var(--muted2))}',
      '.mcp-pre button{margin-top:auto;align-self:flex-start;height:32px;padding:0 14px;border-radius:999px;border:0;background:var(--ys-sel,var(--violet));color:var(--ys-on-sel,#fff);font:700 12px Onest,system-ui,sans-serif;cursor:pointer}',
      '.mcp-pre button:disabled{opacity:.5;cursor:default}',
      '.mcp-pre.on{opacity:.7}',
      '.mcp-steps{font-size:13.5px;line-height:1.55;padding:12px 14px 12px 32px;margin:0;border-radius:14px;background:var(--ys-sunken,var(--violet-bg))}',
      '.mcp-steps code{font-size:12.5px;padding:1px 6px;border-radius:6px;background:var(--ys-surface,rgba(255,255,255,.6));word-break:break-all}',
      '.mcp-adv{font-size:13px}',
      '.mcp-adv summary{cursor:pointer;font-weight:700;color:var(--ys-ink-2,var(--muted))}',
      '.mcp-adv .mcp-advg{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px}',
      '@media (max-width:640px){.mcp-adv .mcp-advg{grid-template-columns:1fr}}',
      '.sp-top .search{width:100%;box-sizing:border-box;height:40px;padding:0 12px;border-radius:12px;font:14px Onest,system-ui,sans-serif}',
      '.sp-top{flex:0 0 auto}',
      '.sp-cats{flex:0 0 auto;display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;padding:3px;border-radius:14px;background:var(--seg-bg,rgba(91,53,224,.06))}',
      '.sp-cats::-webkit-scrollbar{display:none}',
      '.sp-cat{flex:0 0 auto;height:32px;padding:0 12px;border:0;border-radius:10px;background:transparent;color:var(--muted,#5B4D93);font:600 13px Onest,system-ui,sans-serif;cursor:pointer;white-space:nowrap}',
      '.sp-cat.on{background:var(--seg-on,#fff);color:var(--accent-ink,var(--ink));box-shadow:0 4px 12px -6px var(--shadow,rgba(0,0,0,.2))}',
      '.sp-list{flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;display:flex;flex-direction:column;gap:6px;margin:0 -2px;padding:2px 2px 4px}',
      '.sp-card{box-sizing:border-box;width:100%;min-width:0;flex:0 0 auto;display:flex;flex-direction:column;border-radius:18px;padding:0;cursor:default}',
      '.sp-head{all:unset;box-sizing:border-box;display:flex;width:100%;cursor:pointer;padding:12px 16px;border-radius:18px}',
      '.sp-head:focus-visible{outline:3px solid #8A63FF;outline-offset:2px}',
      '.sp-head .m-main{width:100%}',
      '.sp-kind{font:600 12px Onest,system-ui,sans-serif;color:var(--muted2,#8A80B5);white-space:nowrap}',
      '.sp-ok{font:700 12px Onest,system-ui,sans-serif;color:var(--ok,#16794C);white-space:nowrap}',
      '.sp-bad{font:700 12px Onest,system-ui,sans-serif;color:var(--err,#C2305F);white-space:nowrap}',
      '.sp-det{display:flex;flex-direction:column;gap:8px;padding:0 16px 14px;font-family:Onest,system-ui,sans-serif}',
      '.sp-det .mcp-sub{font-size:13px;line-height:1.45;color:var(--muted,#5B4D93)}',
      '.sp-doc{font-size:12.5px;color:var(--accent-ink,#5B35E0)}',
      '.sp-acts{display:flex;flex-wrap:wrap;gap:6px;align-items:center}',
      '.sp-acts button,.sp-acts a,.sp-form button{height:34px;padding:0 14px;border-radius:999px;border:1px solid var(--field-brd,rgba(91,53,224,.25));background:transparent;color:var(--ink);font:700 12.5px Onest,system-ui,sans-serif;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center}',
      '.sp-acts .pri,.sp-form .pri{background:var(--ys-sel,var(--ink,#1E1238));color:var(--ys-on-sel,#fff);border-color:transparent}',
      '.sp-acts button:disabled,.sp-form button:disabled{opacity:.6}',
      '.sp-det .mcp-steps{font-size:12.5px;padding:10px 12px 10px 28px;overflow-wrap:anywhere}',
      '.sp-det .mcp-steps code{word-break:break-all}',
      '.sp-form{display:flex;flex-direction:column;gap:6px}',
      '.sp-form input{height:38px;padding:0 12px;border-radius:12px;border:1px solid var(--field-brd,rgba(91,53,224,.25));background:var(--field,#fff);color:var(--ink);font:13px Onest,system-ui,sans-serif}',
      '.sp-form button{align-self:flex-start}',
      '.sp-empty{padding:20px 8px;text-align:center;font-size:14px;line-height:1.5;color:var(--muted,#5B4D93)}',
      '.sp-more{align-self:center;font:700 13px Onest,system-ui,sans-serif;color:var(--accent-ink,#5B35E0);text-decoration:none;padding:6px 10px}',
      '#mcpPane{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;gap:10px}',
      '.mcp-warn{font-size:13px;padding:8px 12px;border-radius:12px;background:rgba(232,105,28,.12);color:var(--orange,#C2550F)}'
    ].join('\n');
    document.head.appendChild(st);
  }

  /* ───────────── кабинет: раздел «Подключения» */
  let host = null, state = { list: [], presets: [], redirect: '', max: 10, max_pins: 6, busy: false, note: '', bridge: '' };
  function toast(t) { if (typeof window.toast === 'function') window.toast(t); else state.note = t; }
  const ST = { ok: ['Подключено', 'ok'], auth: ['Нужен вход', 'bad'], error: ['Ошибка', 'bad'], new: ['Подключаю…', ''] };

  function cardHtml(c) {
    const st = ST[c.status] || ST.new;
    const pins = c.tools.filter((t) => t.pinned).length;
    const tools = c.tools.length
      ? '<div class="lbl" style="margin:2px 0 0">Кнопки в студии — отмечено ' + pins + ' из ' + state.max_pins + '</div><div class="mcp-tools">'
        + c.tools.map((t) => '<label class="mcp-tool"><input type="checkbox" data-mcp-pin="' + c.id + '" value="' + esc(t.name) + '"' + (t.pinned ? ' checked' : '') + '><span><b>' + esc(t.title) + '</b>'
          + (t.readOnly ? '<span class="mcp-tag">только чтение</span>' : '') + (t.destructive ? '<span class="mcp-tag warn">меняет или удаляет данные</span>' : '')
          + (t.description ? '<small>' + esc(t.description) + '</small>' : '') + '</span></label>').join('') + '</div>'
      : (c.status === 'ok' ? '<div class="mcp-empty">У сервера нет инструментов.</div>' : '');
    return '<div class="mcp-card" data-mcp-card="' + c.id + '"><div class="mcp-head"><div><div class="mcp-name">' + esc(c.name) + (c.server && c.server !== c.name ? ' <span class="mcp-host">· ' + esc(c.server) + '</span>' : '') + '</div><div class="mcp-host">' + esc(c.url) + '</div></div>'
      + '<span class="mcp-st ' + st[1] + '">' + st[0] + '</span>'
      + '<div class="mcp-acts">'
      + (c.status !== 'ok' && c.auth !== 'token' ? '<button class="pri" data-mcp-act="oauth" data-id="' + c.id + '">Войти через сервис</button>' : '')
      + '<button data-mcp-act="token" data-id="' + c.id + '">' + (c.auth === 'token' ? 'Сменить токен' : 'Вставить токен') + '</button>'
      + '<button data-mcp-act="refresh" data-id="' + c.id + '">Обновить</button>'
      + '<button data-mcp-act="del" data-id="' + c.id + '">Удалить</button></div></div>'
      + (c.error ? '<div class="mcp-err">' + esc(c.error) + '</div>' : '')
      + tools + '</div>';
  }
  function draw() {
    if (!host) return;
    host.innerHTML = '<section class="glass sec mcp-wrap"><h2>Подключения MCP</h2>'
      + '<p class="hint" style="margin:0">Подключите свои сервисы, у которых есть MCP-сервер: хранилище, соцсеть, CRM, таблицы. Отметьте инструменты — они появятся кнопками под результатом генерации в студии. Нажали кнопку — открылась форма с уже подставленной ссылкой и промптом, вы проверяете и нажимаете «Выполнить». Без вашего нажатия ничего не отправляется.</p>'
      + '<p class="hint" style="margin:0">Вход и токены хранятся зашифрованными и видны только вам. Сервер должен быть доступен из интернета по https.</p>'
      + presetsHtml()
      + (state.bridge ? bridgeHtml() : '')
      + '<div class="lbl" style="margin:4px 0 -6px">Другой сервер по адресу</div>'
      + '<form class="mcp-add" data-mcp-add><div><label class="lbl" for="mcpUrl">Адрес MCP-сервера</label><input class="inp" id="mcpUrl" name="url" placeholder="https://example.com/mcp" inputmode="url" autocomplete="off" required></div>'
      + '<div><label class="lbl" for="mcpName">Название (необязательно)</label><input class="inp" id="mcpName" name="name" maxlength="80" placeholder="Мой Dropbox"></div>'
      + '<button class="btn btn-p" type="submit"' + (state.busy ? ' disabled' : '') + '>' + (state.busy ? 'Подключаю…' : 'Подключить') + '</button>'
      + '<div class="mcp-tok"><label class="lbl" for="mcpTok">Токен доступа — если сервис выдал его вместо входа (необязательно)</label><input class="inp" id="mcpTok" name="token" type="password" autocomplete="off" placeholder="Оставьте пустым — тогда войдёте через сервис"></div>'
      + '<details class="mcp-adv mcp-tok"><summary>Своё OAuth-приложение — если сервис не пускает автоматический вход</summary><p class="hint" style="margin:6px 0 0">Зарегистрируйте приложение в кабинете разработчика сервиса с адресом возврата <code>' + esc(state.redirect) + '</code> и вставьте его данные.</p><div class="mcp-advg"><input class="inp" name="client_id" placeholder="client_id" autocomplete="off"><input class="inp" name="client_secret" type="password" placeholder="client_secret (если выдали)" autocomplete="off"></div></details></form>'
      + (state.note ? '<div class="mcp-warn">' + esc(state.note) + '</div>' : '')
      + (state.list.length ? state.list.map(cardHtml).join('') : '<div class="mcp-empty">Пока ничего не подключено.</div>')
      + '<p class="hint" style="margin:0">Подключено ' + state.list.length + ' из ' + state.max + '.</p></section>';
  }
  function presetsHtml() {
    if (!state.presets.length) return '';
    const have = (u) => u && state.list.some((c) => c.url === u);
    return '<div class="lbl" style="margin:4px 0 -6px">Готовые сервисы</div><div class="mcp-pres">' + state.presets.map((p) => {
      const on = have(p.url);
      const btn = p.auth === 'bridge'
        ? '<button type="button" data-mcp-pre="' + esc(p.id) + '">' + (state.bridge === p.id ? 'Скрыть инструкцию' : 'Как подключить') + '</button>'
        : on ? '<button type="button" disabled>Уже подключён</button>'
        : !p.ready ? '<button type="button" disabled title="Владельцу сайта нужно зарегистрировать приложение у сервиса (MCP_CLIENTS)">Скоро</button>'
        : '<button type="button" data-mcp-pre="' + esc(p.id) + '">Подключить</button>';
      return '<div class="mcp-pre' + (on ? ' on' : '') + '"><b>' + esc(p.name) + '</b><small>' + esc(p.note) + '</small>' + btn + '</div>';
    }).join('') + '</div>';
  }
  function bridgeSteps(p) {
    p = p || {};
    const run = p.cmd ? esc(p.cmd) : 'команда запуска сервера из его инструкции';
    const env = p.env ? '<li>Возьмите API-ключ в кабинете ' + esc(p.name) + ' и задайте переменную <code>' + esc(p.env) + '</code> (Windows: <code>set ' + esc(p.env) + '=…</code>, macOS/Linux: <code>export ' + esc(p.env) + '=…</code>).</li>' : '';
    return '<ol class="mcp-steps">'
      + (p.id === 'davinci' ? '<li>Запустите DaVinci Resolve и установите сервер по <a href="' + esc(p.docs) + '" target="_blank" rel="noopener noreferrer">инструкции проекта</a>.</li>' : '')
      + env
      + '<li>Скачайте мост <a href="/download/mcp_bridge.py" download>mcp_bridge.py</a> и запустите: <code>python mcp_bridge.py --port 8765 -- ' + run + '</code>. Он покажет токен.</li>'
      + '<li>Дайте мосту адрес в интернете: <code>cloudflared tunnel --url http://127.0.0.1:8765</code> → появится <code>https://….trycloudflare.com</code>.</li>'
      + '<li>Вставьте адрес <code>https://….trycloudflare.com/mcp</code> и токен из шага с мостом → «Подключить».</li>'
      + '</ol>';
  }
  function bridgeHtml() {
    const p = state.presets.find((x) => x.id === state.bridge) || {};
    return '<div class="lbl" style="margin:0 0 -6px">' + esc(p.name || 'Локальный сервер') + ' — на вашем компьютере</div>' + bridgeSteps(p)
      + '<p class="hint" style="margin:-6px 0 0">Пока мост запущен, инструменты доступны только по вашей кнопке в студии; закройте мост — доступ пропадёт. Адрес и токен — в форму «Другой сервер по адресу» ниже.</p>';
  }
  async function onPreset(id) {
    const p = state.presets.find((x) => x.id === id);
    if (!p) return;
    if (p.auth === 'bridge') { state.bridge = state.bridge === p.id ? '' : p.id; draw(); return; }
    state.busy = true; state.note = ''; draw();
    const { res, data } = await api('/api/mcp', { method: 'POST', body: { url: p.url, name: p.name } });
    state.busy = false;
    if (!res.ok) { state.note = res.status === 409 ? 'Этот сервис уже подключён.' : (data.message || 'Не получилось подключить'); draw(); return; }
    afterConnect(data);
  }
  async function load() {
    const { res, data } = await api('/api/mcp');
    if (res.ok) { state.list = data.connections || []; state.presets = data.presets || []; state.redirect = data.redirect_uri || ''; state.max = data.max || 10; state.max_pins = data.max_pins || 6; }
    else if (res.status === 401) { state.note = 'Войдите в аккаунт, чтобы подключать сервисы.'; }
    draw();
  }
  function upsert(c) {
    const i = state.list.findIndex((x) => x.id === c.id);
    if (i >= 0) state.list[i] = c; else state.list.push(c);
  }
  function afterConnect(data) {
    if (data.connection) upsert(data.connection);
    if (data.oauth_url && safeHref(data.oauth_url)) { location.href = data.oauth_url; return; }
    if (data.need_token) state.note = 'Сервер не даёт войти автоматически — вставьте токен доступа от этого сервиса («Вставить токен»).';
    else if (data.connection && data.connection.status === 'ok') state.note = '';
    draw();
  }
  async function onSubmit(form) {
    const url = form.url.value.trim();
    if (!url) return;
    state.busy = true; state.note = ''; draw();
    const { res, data } = await api('/api/mcp', { method: 'POST', body: { url: url, name: form.name.value.trim(), token: form.token.value.trim(), client_id: form.client_id.value.trim(), client_secret: form.client_secret.value.trim() } });
    state.busy = false;
    if (!res.ok) {
      state.note = res.status === 409 ? 'Этот сервер уже подключён.' : data.error === 'too_many' ? 'Достигнут предел подключений — удалите ненужное.' : (data.message || 'Не получилось подключить');
      draw();
      const f = host.querySelector('[data-mcp-add]');
      if (f) { f.url.value = url; f.name.value = form.name ? form.name.value : ''; }
      return;
    }
    afterConnect(data);
  }
  async function onAct(btn) {
    const id = +btn.getAttribute('data-id');
    const act = btn.getAttribute('data-mcp-act');
    const c = state.list.find((x) => x.id === id);
    if (!c) return;
    if (act === 'del') {
      if (!window.confirm('Удалить подключение «' + c.name + '»? Кнопки этого сервиса пропадут из студии.')) return;
      const { res } = await api('/api/mcp/' + id, { method: 'DELETE' });
      if (res.ok) { state.list = state.list.filter((x) => x.id !== id); draw(); }
      return;
    }
    btn.disabled = true;
    if (act === 'oauth') {
      const { res, data } = await api('/api/mcp/' + id + '/oauth', { method: 'POST' });
      if (res.ok && safeHref(data.oauth_url)) { location.href = data.oauth_url; return; }
      state.note = data.message || 'Сервер не даёт войти автоматически — вставьте токен.';
      draw();
      return;
    }
    if (act === 'token') {
      const t = window.prompt('Токен доступа для «' + c.name + '». Пустое поле — убрать токен.', '');
      if (t === null) { btn.disabled = false; return; }
      const { data } = await api('/api/mcp/' + id, { method: 'POST', body: { token: t.trim() } });
      afterConnect(data);
      return;
    }
    if (act === 'refresh') {
      const { data } = await api('/api/mcp/' + id + '/refresh', { method: 'POST' });
      afterConnect(data);
    }
  }
  async function onPin(box) {
    const id = +box.getAttribute('data-mcp-pin');
    const names = [...host.querySelectorAll('[data-mcp-pin="' + id + '"]:checked')].map((x) => x.value);
    if (names.length > state.max_pins) { box.checked = false; toast('Не больше ' + state.max_pins + ' кнопок на подключение'); return; }
    const { res, data } = await api('/api/mcp/' + id + '/pins', { method: 'POST', body: { tools: names } });
    if (res.ok && data.connection) { upsert(data.connection); draw(); }
    btnCache = null;
  }
  function account(el) {
    css();
    const first = host !== el;
    host = el;
    if (first) {
      el.addEventListener('submit', (e) => { const f = e.target.closest('[data-mcp-add]'); if (f) { e.preventDefault(); onSubmit(f); } });
      el.addEventListener('click', (e) => {
        const b = e.target.closest('[data-mcp-act]'); if (b) { e.preventDefault(); onAct(b); return; }
        const pr = e.target.closest('[data-mcp-pre]'); if (pr) { e.preventDefault(); onPreset(pr.getAttribute('data-mcp-pre')); }
      });
      el.addEventListener('change', (e) => { const b = e.target.closest('[data-mcp-pin]'); if (b) onPin(b); });
      const q = new URLSearchParams(location.search);
      if (q.get('mcp') === 'ok') state.note = '';
      if (q.get('mcp') === 'err') state.note = 'Вход не завершён. Нажмите «Войти через сервис» ещё раз или вставьте токен.';
      if (q.get('mcp')) { q.delete('mcp'); q.delete('id'); history.replaceState(null, '', location.pathname + (q.toString() ? '?' + q : '') + location.hash); }
    }
    draw();
    load();
  }

  /* ───────────── студия: кнопки под результатом */
  let btnCache = null, btnAt = 0;
  async function buttons() {
    if (btnCache && Date.now() - btnAt < 60000) return btnCache;
    const { res, data } = await api('/api/mcp/buttons');
    btnCache = res.ok ? (data.buttons || []) : [];
    btnAt = Date.now();
    return btnCache;
  }
  function lastPrompt(app, url) {
    const msgs = (app && app.state && app.state.msgs) || [];
    const hit = url && msgs.slice().reverse().find((x) => x && x.mediaUrl === url && x.prompt);
    if (hit) return String(hit.prompt);
    const u = msgs.slice().reverse().find((x) => x && x.role === 'user' && x.text);
    return u ? String(u.text) : '';
  }
  async function offer(payload, app) {
    if (!payload || !app || !app.push) return;
    if (app.state && app.state.authed === false) return;
    const list = await buttons();
    if (!list.length) return;
    const ctx = {
      url: payload.url || '', kind: payload.kind || '', work_id: payload.work_id || '',
      text: payload.kind === 'text' ? String(payload.reply || '').slice(0, 8000) : '',
      prompt: lastPrompt(app, payload.url).slice(0, 4000)
    };
    app.push({
      role: 'bot',
      text: list.length === 1 ? 'Можно отправить результат в подключённый сервис:' : 'Можно отправить результат в подключённые сервисы:',
      chips: list.slice(0, 5).map((b) => ({ label: '🔌 ' + b.title + ' · ' + b.conn, action: 'mcp_tool', value: { cid: b.cid, tool: b.tool, ctx: ctx } }))
    });
  }

  function fieldHtml(f, i) {
    const id = 'mcpf' + i;
    const req = f.required ? ' required' : '';
    const hint = f.description ? ' <i>— ' + esc(f.description) + '</i>' : '';
    const title = esc(f.title) + (f.required ? ' *' : '') + hint;
    if (f.widget === 'check') return '<label class="ck"><input type="checkbox" id="' + id + '" data-f="' + esc(f.name) + '"' + (f.value ? ' checked' : '') + '>' + title + '</label>';
    if (f.widget === 'select') {
      return '<label>' + title + '<select id="' + id + '" data-f="' + esc(f.name) + '"' + req + '>' + (f.required ? '' : '<option value="">—</option>')
        + f.enum.map((o) => '<option' + (String(o) === String(f.value) ? ' selected' : '') + '>' + esc(o) + '</option>').join('') + '</select></label>';
    }
    if (f.widget === 'area' || f.widget === 'json') return '<label>' + title + (f.widget === 'json' ? ' <i>(JSON)</i>' : '') + '<textarea id="' + id + '" data-f="' + esc(f.name) + '"' + req + '>' + esc(f.value) + '</textarea></label>';
    return '<label>' + title + '<input id="' + id + '" data-f="' + esc(f.name) + '"' + (f.widget === 'number' ? ' type="number" step="any"' : '') + ' value="' + esc(f.value) + '"' + req + '></label>';
  }
  function close(ov) { if (ov && ov.parentNode) ov.parentNode.removeChild(ov); }
  async function open(value, app) {
    css();
    if (!value || !value.cid) return;
    const ov = document.createElement('div');
    ov.className = 'mcp-ov';
    ov.innerHTML = '<div class="mcp-dlg" role="dialog" aria-modal="true" aria-label="Инструмент MCP"><div class="mcp-sub">Загружаю форму…</div></div>';
    document.body.appendChild(ov);
    ov.addEventListener('click', (e) => { if (e.target === ov) close(ov); });
    document.addEventListener('keydown', function onKey(e) { if (e.key === 'Escape') { close(ov); document.removeEventListener('keydown', onKey); } });
    const dlg = ov.firstChild;
    const { res, data } = await api('/api/mcp/form', { method: 'POST', body: { cid: value.cid, tool: value.tool, ctx: value.ctx || {} } });
    if (!res.ok) {
      dlg.innerHTML = '<h3>Инструмент недоступен</h3><div class="mcp-sub">Подключение удалено или инструмент пропал с сервера. Проверьте раздел «Подключения».</div><div class="mcp-row"><button type="button" data-x>Закрыть</button><button class="pri" type="button" data-go-acc>Подключения</button></div>';
      dlg.querySelector('[data-x]').onclick = () => close(ov);
      dlg.querySelector('[data-go-acc]').onclick = () => { location.href = '/account#mcp'; };
      return;
    }
    const fields = data.fields || [];
    dlg.innerHTML = '<h3>' + esc(data.title) + '</h3><div class="mcp-sub">' + esc(data.conn) + (data.description ? ' · ' + esc(data.description) : '') + '</div>'
      + (data.status !== 'ok' ? '<div class="mcp-warn">Подключение требует входа — если не сработает, войдите заново в разделе <a href="/account#mcp">«Подключения»</a>.</div>' : '')
      + (data.destructive ? '<div class="mcp-warn">Этот инструмент меняет или удаляет данные в сервисе. Проверьте поля перед запуском.</div>' : '')
      + '<form data-mcp-form style="display:flex;flex-direction:column;gap:10px">' + (fields.length ? fields.map(fieldHtml).join('') : '<div class="mcp-sub">У инструмента нет полей.</div>')
      + '<div data-out></div><div class="mcp-row"><button type="button" data-x>Отмена</button><button class="pri" type="submit">Выполнить</button></div></form>';
    dlg.querySelector('[data-x]').onclick = () => close(ov);
    const form = dlg.querySelector('[data-mcp-form]');
    const first = form.querySelector('input,textarea,select');
    if (first) first.focus();
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const args = {};
      form.querySelectorAll('[data-f]').forEach((el) => { args[el.getAttribute('data-f')] = el.type === 'checkbox' ? el.checked : el.value; });
      const run = form.querySelector('button[type=submit]');
      const out = form.querySelector('[data-out]');
      run.disabled = true; run.textContent = 'Выполняю…';
      out.innerHTML = '';
      const r = await api('/api/mcp/call', { method: 'POST', body: { cid: value.cid, tool: value.tool, args: args } });
      run.disabled = false; run.textContent = 'Выполнить';
      const d = r.data || {};
      if (!r.res.ok) {
        const msg = d.error === 'bad_args' ? 'Проверьте поле «' + (d.field || '') + '»' + (fields.find((f) => f.name === d.field && f.widget === 'json') ? ' — нужен JSON' : '')
          : d.error === 'auth_required' ? 'Нужно войти в сервис заново: раздел «Подключения» → «Войти через сервис».'
          : (d.detail ? d.message + ': ' + d.detail : (d.message || 'Не получилось'));
        out.innerHTML = '<div class="mcp-out bad">' + esc(msg) + (d.error === 'auth_required' ? ' <a href="/account#mcp">Открыть</a>' : '') + '</div>';
        if (d.error === 'bad_args') { const el = form.querySelector('[data-f="' + CSS.escape(d.field || '') + '"]'); if (el) el.focus(); }
        return;
      }
      const links = (d.links || []).filter((l) => safeHref(l.url));
      out.innerHTML = '<div class="mcp-out' + (d.ok ? '' : ' bad') + '">' + esc(d.text || (d.ok ? 'Готово' : 'Инструмент вернул ошибку')) + '</div>'
        + (links.length ? '<div class="mcp-links">' + links.map((l) => '<a href="' + esc(l.url) + '" target="_blank" rel="noopener noreferrer">' + esc(l.title || l.url) + '</a>').join('') + '</div>' : '')
        + ((d.images || []).length ? '<div class="mcp-imgs">' + d.images.map((s) => (/^data:image\/(png|jpeg|webp|gif);base64,/.test(s) ? '<img alt="" src="' + esc(s) + '">' : '')).join('') + '</div>' : '');
      run.textContent = 'Выполнить ещё раз';
      if (app && app.push) {
        const head = (d.ok ? '✓ ' : '⚠ ') + d.title + ' · ' + d.conn;
        const body = String(d.text || '').slice(0, 600) + (String(d.text || '').length > 600 ? '…' : '');
        const extra = links.slice(0, 3).map((l) => l.url).filter((u) => body.indexOf(u) < 0).join('\n');
        app.push({ role: 'bot', text: head + (body ? '\n' + body : '') + (extra ? '\n' + extra : '') });
      }
    });
  }


  /* ───────────── студия: третья вкладка правой панели «MCP» — каталог серверов и мои подключения */
  const CATS = [['all', 'Все'], ['mine', 'Мои'], ['viral', 'Виральность'], ['reels', 'Reels'], ['edit', 'Монтаж'], ['3d', '3D'], ['video', 'Видео'], ['voice', 'Голос'], ['storage', 'Файлы']];
  const CAT_LABEL = { viral: 'Виральность', reels: 'Reels', edit: 'Монтаж', '3d': '3D', video: 'Видео', voice: 'Голос', storage: 'Файлы' };
  const sp = { el: null, app: null, list: [], presets: [], cat: 'all', q: '', open: '', note: '', busy: false, loaded: false, authed: true };
  function spConn(p) { return p.url ? sp.list.find((c) => c.url === p.url) : sp.list.find((c) => c._preset === p.id); }
  function spItems() {
    const items = sp.presets.map((p) => ({ p: p, c: spConn(p) }));
    sp.list.filter((c) => !items.some((it) => it.c === c)).forEach((c) => items.push({ p: { id: 'c' + c.id, name: c.name, auth: 'custom', cats: [], note: c.url, official: null }, c: c }));
    const q = sp.q.trim().toLowerCase();
    return items.filter((it) => (sp.cat === 'all' || (sp.cat === 'mine' ? !!it.c : (it.p.cats || []).indexOf(sp.cat) >= 0))
      && (!q || (it.p.name + ' ' + (it.p.note || '')).toLowerCase().indexOf(q) >= 0));
  }
  function spTools(c) {
    if (!c.tools.length) return c.status === 'ok' ? '<div class="mcp-sub">У сервера нет инструментов.</div>' : '';
    return '<div class="mcp-sub" style="margin-top:2px">Кнопки под результатом:</div><div class="mcp-tools" style="max-height:220px">'
      + c.tools.map((t) => '<label class="mcp-tool"><input type="checkbox" data-sp-pin="' + c.id + '" value="' + esc(t.name) + '"' + (t.pinned ? ' checked' : '') + '><span><b>' + esc(t.title) + '</b>'
        + (t.destructive ? '<span class="mcp-tag warn">меняет данные</span>' : '') + (t.description ? '<small>' + esc(t.description) + '</small>' : '') + '</span></label>').join('') + '</div>';
  }
  function spDetail(it) {
    const p = it.p, c = it.c;
    let h = '<div class="sp-det">' + (p.note && p.auth !== 'custom' ? '<div class="mcp-sub">' + esc(p.note) + '</div>' : '')
      + (p.docs ? '<a class="sp-doc" href="' + esc(p.docs) + '" target="_blank" rel="noopener noreferrer">Документация ↗</a>' : '');
    if (c) {
      h += '<div class="sp-acts">'
        + (c.status !== 'ok' && c.auth !== 'token' ? '<button type="button" class="pri" data-sp="oauth" data-id="' + c.id + '">Войти</button>' : '')
        + '<button type="button" data-sp="refresh" data-id="' + c.id + '">Обновить</button><a href="/account#mcp">Настроить</a></div>'
        + (c.error ? '<div class="mcp-err">' + esc(c.error) + '</div>' : '') + spTools(c);
    } else if (p.auth === 'oauth') {
      h += p.ready === false
        ? '<div class="mcp-warn">Скоро: владельцу сайта нужно зарегистрировать приложение у ' + esc(p.name) + '.</div>'
        : '<div class="sp-acts"><button type="button" class="pri" data-sp="add" data-pre="' + esc(p.id) + '"' + (sp.busy ? ' disabled' : '') + '>' + (sp.busy ? 'Подключаю…' : 'Подключить — войти в ' + esc(p.name)) + '</button></div>';
    } else if (p.auth === 'bridge') {
      h += bridgeSteps(p)
        + '<form class="sp-form" data-sp-form="' + esc(p.id) + '"><input name="url" placeholder="https://….trycloudflare.com/mcp" inputmode="url" autocomplete="off" required><input name="token" type="password" placeholder="Токен моста" autocomplete="off" required>'
        + '<button type="submit" class="pri"' + (sp.busy ? ' disabled' : '') + '>' + (sp.busy ? 'Подключаю…' : 'Подключить') + '</button></form>';
    }
    return h + '</div>';
  }
  function spDraw() {
    const el = sp.el;
    if (!el) return;
    if (!sp.authed) {
      el.innerHTML = '<div class="sp-empty">Войдите в аккаунт, чтобы подключать сервисы по MCP: vidIQ, Higgsfield и другие. Их инструменты появятся кнопками под результатом генерации.</div>';
      return;
    }
    const items = sp.loaded ? spItems() : [];
    el.innerHTML = '<div class="sp-top"><input class="search" type="search" data-sp-q placeholder="Поиск сервиса" value="' + esc(sp.q) + '" autocomplete="off" aria-label="Поиск MCP-сервера"></div>'
      + '<div class="sp-cats" role="tablist" aria-label="Категории MCP">' + CATS.map(([k, l]) => '<button type="button" role="tab" class="sp-cat' + (sp.cat === k ? ' on' : '') + '" aria-selected="' + (sp.cat === k) + '" data-sp-cat="' + k + '">' + l + (k === 'mine' && sp.list.length ? ' ' + sp.list.length : '') + '</button>').join('') + '</div>'
      + (sp.note ? '<div class="mcp-warn">' + esc(sp.note) + '</div>' : '')
      + '<div class="sp-list">' + (!sp.loaded ? '<div class="sp-empty">Загружаю…</div>' : items.length ? items.map((it) => {
        const p = it.p, c = it.c, on = sp.open === p.id;
        const right = c ? (c.status === 'ok' ? '<span class="sp-ok">Подключено</span>' : '<span class="sp-bad">Нужен вход</span>')
          : p.auth === 'oauth' ? '<span class="sp-kind">по адресу</span>' : p.auth === 'bridge' ? '<span class="sp-kind">на компьютере</span>' : '';
        const tags = (p.cats || []).map((k) => '<span class="m-kind">' + esc(CAT_LABEL[k] || k) + '</span>').join('')
          + (p.official === true ? '<span class="m-kind">Официальный</span>' : p.official === false ? '<span class="m-kind">Сообщество</span>' : '')
          + (c && c.tools.length ? '<span class="m-kind">' + c.tools.filter((t) => t.pinned).length + ' кнопк. из ' + c.tools.length + '</span>' : '');
        return '<div class="model sp-card' + (on ? ' model-on' : '') + '"><button type="button" class="sp-head" data-sp-open="' + esc(p.id) + '" aria-expanded="' + on + '"><span class="m-main"><span class="m-top"><span class="m-meta"><span class="m-name" style="color:var(--ink)">' + esc(p.name) + '</span></span><span class="m-cost">' + right + '</span></span>'
          + (tags ? '<span class="m-row">' + tags + '</span>' : '') + '</span></button>' + (on ? spDetail(it) : '') + '</div>';
      }).join('') : '<div class="sp-empty">' + (sp.cat === 'mine' ? 'Пока ничего не подключено — выберите сервис во вкладке «Все».' : 'Ничего не нашлось.') + '</div>') + '</div>'
      + '<a class="sp-more" href="/account#mcp">+ Свой сервер по адресу</a>';
  }
  async function spLoad() {
    const { res, data } = await api('/api/mcp');
    sp.authed = res.status !== 401;
    if (res.ok) { sp.list = data.connections || []; sp.presets = data.presets || []; }
    sp.loaded = true;
    spDraw();
  }
  async function spAfter(data) {
    if (data.oauth_url && safeHref(data.oauth_url)) { location.href = data.oauth_url; return; }
    if (data.connection) {
      const i = sp.list.findIndex((x) => x.id === data.connection.id);
      if (i >= 0) sp.list[i] = data.connection; else sp.list.push(data.connection);
      if (data.need_token) sp.note = 'Сервер не даёт войти автоматически — нужен токен (Кабинет → Подключения).';
      else if (data.connection.status === 'ok') sp.note = '';
    }
    btnCache = null;
    spDraw();
  }
  function studio(el, app) {
    css();
    if (sp.el !== el) {
      sp.el = el; sp.app = app;
      el.addEventListener('input', (e) => { if (e.target.matches('[data-sp-q]')) { sp.q = e.target.value; const pos = e.target.selectionStart; spDraw(); const q = el.querySelector('[data-sp-q]'); if (q) { q.focus(); try { q.setSelectionRange(pos, pos); } catch (_) {} } } });
      el.addEventListener('change', async (e) => {
        const b = e.target.closest('[data-sp-pin]');
        if (!b) return;
        const id = +b.getAttribute('data-sp-pin');
        const names = [...el.querySelectorAll('[data-sp-pin="' + id + '"]:checked')].map((x) => x.value);
        const { res, data } = await api('/api/mcp/' + id + '/pins', { method: 'POST', body: { tools: names } });
        if (res.ok) spAfter(data); else b.checked = !b.checked;
      });
      el.addEventListener('submit', async (e) => {
        const f = e.target.closest('[data-sp-form]');
        if (!f) return;
        e.preventDefault();
        const p = sp.presets.find((x) => x.id === f.getAttribute('data-sp-form')) || {};
        sp.busy = true; spDraw();
        const { res, data } = await api('/api/mcp', { method: 'POST', body: { url: f.url.value.trim(), token: f.token.value.trim(), name: p.name || '', back: 'app' } });
        sp.busy = false;
        if (!res.ok) { sp.note = res.status === 409 ? 'Этот адрес уже подключён.' : (data.message || 'Не получилось подключить'); spDraw(); return; }
        if (data.connection) data.connection._preset = p.id;
        sp.open = p.id;
        spAfter(data);
      });
      el.addEventListener('click', async (e) => {
        const cat = e.target.closest('[data-sp-cat]');
        if (cat) { sp.cat = cat.getAttribute('data-sp-cat'); spDraw(); return; }
        const op = e.target.closest('[data-sp-open]');
        if (op) { const id = op.getAttribute('data-sp-open'); sp.open = sp.open === id ? '' : id; spDraw(); return; }
        const b = e.target.closest('[data-sp]');
        if (!b) return;
        const act = b.getAttribute('data-sp');
        if (act === 'add') {
          const p = sp.presets.find((x) => x.id === b.getAttribute('data-pre'));
          if (!p) return;
          sp.busy = true; spDraw();
          const { res, data } = await api('/api/mcp', { method: 'POST', body: { url: p.url, name: p.name, back: 'app' } });
          sp.busy = false;
          if (!res.ok) { sp.note = res.status === 409 ? 'Уже подключён.' : (data.message || 'Не получилось подключить'); spDraw(); return; }
          spAfter(data);
          return;
        }
        const id = b.getAttribute('data-id');
        b.disabled = true;
        if (act === 'oauth') {
          const { res, data } = await api('/api/mcp/' + id + '/oauth', { method: 'POST', body: { back: 'app' } });
          if (res.ok && safeHref(data.oauth_url)) { location.href = data.oauth_url; return; }
          sp.note = data.message || 'Сервер не даёт войти автоматически — вставьте токен в кабинете.';
          spDraw();
          return;
        }
        if (act === 'refresh') { const { data } = await api('/api/mcp/' + id + '/refresh', { method: 'POST' }); spAfter(data); }
      });
      const q = new URLSearchParams(location.search);
      if (q.get('mcp')) {
        sp.note = q.get('mcp') === 'ok' ? 'Подключено. Отметьте инструменты — они появятся кнопками под результатом генерации.' : 'Вход не завершён — попробуйте ещё раз.';
        sp.cat = 'mine';
        const cid = +q.get('id');
        sp._openCid = cid;
        q.delete('mcp'); q.delete('id');
        history.replaceState(null, '', location.pathname + (q.toString() ? '?' + q : '') + location.hash.replace('#mcp', ''));
      }
    }
    spDraw();
    spLoad().then(() => {
      if (sp._openCid) {
        const c = sp.list.find((x) => x.id === sp._openCid);
        const it = c && spItems().find((x) => x.c === c);
        if (it) { sp.open = it.p.id; spDraw(); }
        sp._openCid = 0;
      }
    });
  }
  /** Помощник ведёт в нужную категорию каталога («виральность», «монтаж», «reels»). */
  function studioCat(cat) {
    if (CATS.some((c) => c[0] === cat)) sp.cat = cat;
    sp.open = '';
    if (sp.el) spDraw();
  }
  window.AishMcp = { account: account, offer: offer, open: open, studio: studio, studioCat: studioCat, _reset: () => { btnCache = null; } };
})();
