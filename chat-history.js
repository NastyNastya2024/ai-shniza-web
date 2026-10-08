/* История переписки студии (/app).
 *
 * Вошёл в аккаунт → переписка сохраняется на сервере (/api/chats), слева список «Чаты».
 * Гость → 24 часа в этом браузере (localStorage) и честная подпись «войдите, чтобы сохранить».
 * Сами прикреплённые файлы НЕ сохраняются: в истории остаются только плашки «Фото: cat.png»,
 * файлы живут 24 часа (как на сервере, UPLOAD_TTL_SEC) — потом плашка помечается «файл удалён».
 *
 *   AishHistory.init({ api, csrf, t, ago, getMsgs, onRestore, onNew, box: '#chatsBox' })
 *   AishHistory.watch(msgs)      — из render(): сохранить с задержкой, если сообщения поменялись
 *   AishHistory.boot(user)       — после /api/auth/me: восстановить текущий чат (или перенести гостевой в аккаунт)
 *   AishHistory.detach()         — «Новый чат» / на главную: сохранить текущий и начать новый
 *   AishHistory.logout()         — выход: стереть локальную историю с устройства
 *   AishHistory.clean(msgs)      — то, что уходит в хранилище (без номеров файлов и временных полей)
 */
(function () {
  'use strict';

  var DAY = 24 * 3600 * 1000;
  var GUEST_KEY = 'aish-chat-guest';
  var ACTIVE_KEY = 'aish-chat-active';
  var OPEN_KEY = 'aish-chats-open';
  var MAX_LOCAL = 400000;     // символов JSON в localStorage
  var MAX_MSGS = 200;
  var KINDS = { image: 1, audio: 1, video: 1 };
  var MEDIA = { image: 1, video: 1, audio: 1, music: 1 };
  var BLOCKS = { models: 1, prompt: 1, params: 1, summary: 1, brief: 1, variants: 1 };

  var o = null;
  var user = null;            // {id} — вошёл; null — гость
  var chatId = null;          // текущий чат на сервере
  var lastRef = null, lastJson = '', timer = 0, creating = null, booted = false;
  var gen = 0;                // номер «текущего чата»: растёт при новом чате, открытии другого, входе и выходе
  var items = [];             // список чатов (для вошедших)
  var days = 30;             // сколько сервер хранит чаты (CHAT_HISTORY_DAYS) — для подписи
  var open = false;

  function ls(op, k, v) {
    try {
      if (op === 'get') return localStorage.getItem(k);
      if (op === 'set') localStorage.setItem(k, v);
      if (op === 'del') localStorage.removeItem(k);
    } catch (e) {}
    return null;
  }
  function readJSON(k) { try { return JSON.parse(ls('get', k) || 'null'); } catch (e) { return null; } }
  function t(k, p) { return o && o.t ? o.t(k, p) : k; }
  function str(v, n) { return String(v == null ? '' : v).slice(0, n); }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

  /* ---------- что сохраняем ---------- */
  function cleanFiles(list) {
    if (!Array.isArray(list)) return [];
    var seen = {};
    var out = [];
    list.forEach(function (f) {
      if (!f || !KINDS[f.kind] || seen[f.kind]) return;
      seen[f.kind] = 1;
      out.push({ kind: f.kind, name: str(f.name, 60) });   // без id (upl_…), url, размера
    });
    return out;
  }
  function cleanOne(m) {
    if (!m || (m.role !== 'user' && m.role !== 'bot') || m.history === 'note') return null;
    var c = { role: m.role, text: str(m.text, 4000), ts: m.ts || Date.now() };
    var files = cleanFiles(m.files);
    if (files.length) c.files = files;
    if (m.role === 'bot') {
      if (m.assistant && typeof m.assistant === 'object') {
        var a = { text: str(m.assistant.text || m.assistant.reply || '', 4000) };
        if (m.assistant.lang) a.lang = m.assistant.lang;
        var bl = (m.assistant.blocks || []).filter(function (b) { return b && BLOCKS[b.type]; });
        if (bl.length) a.blocks = bl.slice(0, 8);
        c.assistant = a;
        if (!c.text) c.text = a.text;
      }
      if (m.result) {
        c.result = true;
        if (m.mediaUrl && /^(https?:\/\/|\/(?!\/))/.test(String(m.mediaUrl))) c.mediaUrl = str(m.mediaUrl, 1000);
        c.mediaKind = MEDIA[m.mediaKind] ? m.mediaKind : 'image';
      }
      if (m.workId) c.workId = String(m.workId);
      if (m.published) c.published = true;   // опубликованная — хранится; неопубликованная через 24 ч удаляется
      if (m.job) c.job = true;
      if (m.loginCta) c.loginCta = true;
      if (m.topup) c.topup = true;
    }
    if (!c.text && !c.files && !c.result && !c.assistant) return null;
    return c;
  }
  function clean(msgs) {
    return (msgs || []).map(cleanOne).filter(Boolean).slice(-MAX_MSGS);
  }

  /* ---------- сеть ---------- */
  function req(method, url, body, keepalive) {
    var send = function (tok) {
      var h = { 'Content-Type': 'application/json' };
      if (method !== 'GET') h['X-CSRF-Token'] = tok || '';
      return fetch(url, { method: method, credentials: 'same-origin', headers: h, cache: 'no-store',
        keepalive: !!keepalive, body: body == null ? undefined : JSON.stringify(body) })
        .then(function (res) { return res.json().catch(function () { return {}; }).then(function (data) { return { ok: res.ok, status: res.status, data: data }; }); });
    };
    if (method === 'GET') return send('');
    return Promise.resolve(o.csrf ? o.csrf() : '').then(send);
  }

  /* ---------- сохранение ---------- */
  function setActive(id) {
    chatId = id;
    if (id && user) ls('set', ACTIVE_KEY, JSON.stringify({ uid: user.id, id: id, at: Date.now() }));
    else ls('del', ACTIVE_KEY);
  }

  function saveNow(msgs, keepalive) {
    var data = clean(msgs);
    var json = JSON.stringify(data);
    if (!data.length || json === lastJson) return Promise.resolve();
    lastJson = json;
    if (!user) {
      var payload = { at: Date.now(), msgs: data };
      while (JSON.stringify(payload).length > MAX_LOCAL && payload.msgs.length > 2) payload.msgs = payload.msgs.slice(2);
      ls('set', GUEST_KEY, JSON.stringify(payload));
      return Promise.resolve();
    }
    var my = gen;             // «Новый чат» / другой чат / выход во время запроса — ответ уже не про текущий чат
    var id = chatId;
    if (id) {
      setActive(id);
      return req('PUT', '/api/chats/' + encodeURIComponent(id), { messages: data }, keepalive).then(function (r) {
        if (my !== gen) return;
        if (r.status === 404) { chatId = null; lastJson = ''; return saveNow(msgs); }   // чат удалили в другой вкладке
        if (!r.ok) { lastJson = ''; return; }
        bumpItem(id, data);
      }).catch(function () { if (my === gen) lastJson = ''; });
    }
    if (creating) return creating.then(function () { if (my !== gen) return; lastJson = ''; return saveNow(msgs); });
    var p = req('POST', '/api/chats', { messages: data }, keepalive).then(function (r) {
      if (creating === p) creating = null;
      if (my !== gen) return;
      if (r.ok && r.data && r.data.id) { setActive(r.data.id); bumpItem(r.data.id, data); }
      else lastJson = '';
    }).catch(function () { if (creating === p) creating = null; if (my === gen) lastJson = ''; });
    creating = p;
    return p;
  }

  function bumpItem(id, data) {
    var title = '';
    for (var i = 0; i < data.length && !title; i++) if (data[i].role === 'user' && data[i].text) title = data[i].text.replace(/\s+/g, ' ').slice(0, 60);
    var it = items.filter(function (x) { return x.id === id; })[0];
    if (!it) { it = { id: id }; items.unshift(it); }
    else { items = [it].concat(items.filter(function (x) { return x !== it; })); }
    it.title = title || it.title || t('studio.history.untitled');
    it.n = data.length;
    it.updated_at = new Date().toISOString();
    renderBox();
  }

  function watch(msgs) {
    if (!o || !booted || msgs === lastRef) return;
    lastRef = msgs;
    clearTimeout(timer);
    timer = setTimeout(function () { saveNow(o.getMsgs()); }, 1200);
    renderBox();
  }

  function flush(keepalive) {
    clearTimeout(timer);
    if (!o || !booted) return Promise.resolve();
    return saveNow(o.getMsgs(), keepalive);
  }

  /* ---------- восстановление ---------- */
  function restore(msgs, opts2) {
    lastJson = JSON.stringify(clean(msgs));
    var now = Date.now();
    var hadFiles = msgs.some(function (m) { return m.files && m.files.length; });
    var gone = msgs.some(function (m) { return m.files && m.files.length && now - (m.ts || 0) > DAY; });
    var out = msgs.map(function (m) { var c = Object.assign({}, m); c.history = true; return c; });
    var note = (opts2 && opts2.note) || 'restored';
    var text = t('studio.history.note.' + note);
    if (hadFiles) text += ' ' + t(gone ? 'studio.history.note.filesGone' : 'studio.history.note.files24');
    // помощник помнит разговор 24 часа (та же cookie) — можно продолжить с того же места: модель, промпт, параметры
    out.push({ role: 'note', history: 'note', text: text, resume: note === 'restored' || note === 'guest' });
    o.onRestore(out);
    lastRef = null;
  }

  function resetAssistant() {
    return req('POST', '/api/assistant/chat/reset', {}).catch(function () {});
  }

  function loadChat(id, note) {
    return req('GET', '/api/chats/' + encodeURIComponent(id)).then(function (r) {
      if (!r.ok || !r.data || !Array.isArray(r.data.messages)) { if (r.status === 404) setActive(null); return false; }
      setActive(id);
      if (r.data.messages.length) restore(r.data.messages, { note: note });
      renderBox();
      return true;
    }).catch(function () { return false; });
  }

  function boot(u) {
    user = u && u.id != null ? { id: u.id } : null;
    var guest = readJSON(GUEST_KEY);
    if (guest && !(guest.at && Date.now() - guest.at < DAY && Array.isArray(guest.msgs))) { ls('del', GUEST_KEY); guest = null; }
    var done;
    if (!user) {
      ls('del', ACTIVE_KEY);
      if (guest && guest.msgs.length) restore(guest.msgs, { note: 'guest' });
      done = Promise.resolve();
    } else if (guest && guest.msgs.length) {
      // вошли после гостевой переписки → переносим её в аккаунт
      ls('del', GUEST_KEY);
      done = req('POST', '/api/chats', { messages: clean(guest.msgs) }).then(function (r) {
        if (r.ok && r.data && r.data.id) setActive(r.data.id);
        restore(guest.msgs, { note: 'moved' });
      }).catch(function () { restore(guest.msgs, { note: 'guest' }); });
    } else {
      var act = readJSON(ACTIVE_KEY);
      if (act && act.uid === user.id && act.id && Date.now() - (act.at || 0) < DAY) done = loadChat(act.id, 'restored');
      else { ls('del', ACTIVE_KEY); done = Promise.resolve(); }
    }
    return done.then(function () {
      booted = true;
      lastRef = o.getMsgs();
      if (user) refreshList(); else renderBox();
    });
  }

  function refreshList() {
    if (!user) { items = []; renderBox(); return Promise.resolve(); }
    return req('GET', '/api/chats').then(function (r) {
      if (r.ok && r.data && Array.isArray(r.data.items)) items = r.data.items;
      if (r.ok && r.data && r.data.days) days = r.data.days;
      renderBox();
    }).catch(function () {});
  }

  /* ---------- новый чат, открыть чат, выход ---------- */
  function detach() {
    var p = flush();
    gen++;
    creating = null;
    chatId = null;
    lastJson = '';
    ls('del', ACTIVE_KEY);
    if (!user) ls('del', GUEST_KEY);
    resetAssistant();
    renderBox();
    return p.then(function () { if (user) return refreshList(); });
  }

  function openChat(id) {
    if (id === chatId) return Promise.resolve();
    return flush().then(function () {
      gen++;
      creating = null;
      resetAssistant();       // память помощника принадлежала прежнему чату
      return loadChat(id, 'opened');
    });
  }

  function remove(id) {
    if (!window.confirm(t('studio.history.confirmDelete'))) return;
    req('DELETE', '/api/chats/' + encodeURIComponent(id), {}).then(function () {
      items = items.filter(function (x) { return x.id !== id; });
      if (id === chatId) { gen++; clearTimeout(timer); chatId = null; lastJson = ''; ls('del', ACTIVE_KEY); resetAssistant(); o.onNew(); }
      renderBox();
    });
  }

  function logout() {
    clearTimeout(timer);
    gen++;
    creating = null;
    ls('del', GUEST_KEY);
    ls('del', ACTIVE_KEY);
    user = null; chatId = null; items = []; lastJson = '';
    resetAssistant();
    renderBox();
  }

  /** Вход / выход без перезагрузки страницы (окно входа прямо в студии). */
  function setUser(u) {
    if (!booted) return;
    var id = u && u.id != null ? u.id : null;
    if ((user && user.id) === id || (!user && id == null)) return;
    if (id == null) { logout(); return; }
    clearTimeout(timer);
    gen++;
    creating = null;
    user = { id: id };
    chatId = null;
    lastJson = '';
    ls('del', GUEST_KEY);     // гостевая переписка переезжает в аккаунт
    ls('del', ACTIVE_KEY);
    flush();
    refreshList();
  }

  /* ---------- левая панель: «Чаты» ---------- */
  function renderBox() {
    var box = o && document.querySelector(o.box || '#chatsBox');
    if (!box) return;
    var msgs = (o.getMsgs() || []).filter(function (m) { return m.role === 'user' || m.role === 'bot'; });
    box.textContent = '';
    box.classList.toggle('chats-guest', !user);

    var head = el('div', 'chats-head');
    var tog = el('button', 'chats-toggle');
    tog.type = 'button';
    tog.setAttribute('aria-expanded', open && user ? 'true' : 'false');
    tog.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 21l1.9-5.4A8 8 0 1 1 21 12z"></path></svg>';
    tog.appendChild(el('span', 'chats-title', t('studio.history.title')));
    if (user && items.length) tog.appendChild(el('span', 'chats-cnt', String(items.length)));
    if (user && !o.side) {
      var chev = el('span', 'chats-chev');
      chev.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg>';
      tog.appendChild(chev);
      tog.addEventListener('click', function () { open = !open; ls('set', OPEN_KEY, open ? '1' : '0'); renderBox(); });
    } else tog.disabled = true;
    if (o.side) tog.setAttribute('aria-expanded', 'true');
    head.appendChild(tog);
    var nw = el('button', 'chats-new', t('studio.history.new'));
    nw.type = 'button';
    nw.title = t('studio.history.newTitle');
    nw.setAttribute('data-chat-new', '');
    nw.disabled = !msgs.length;
    nw.addEventListener('click', function () { detach(); o.onNew(); });
    head.appendChild(nw);
    box.appendChild(head);

    if (!user && o.side) {
      // гость: один текущий чат в этом браузере + приглашение войти
      var gl = el('ul', 'chats-list');
      if (msgs.length) {
        var gi = el('li', 'chats-item is-on');
        var gb = el('div', 'chats-open');
        var first = msgs.filter(function (m) { return m.role === 'user' && m.text; })[0];
        gb.appendChild(el('span', 'chats-name', first ? first.text.replace(/\s+/g, ' ').slice(0, 60) : t('studio.history.current')));
        gb.appendChild(el('span', 'chats-when', t('studio.history.guestWhen')));
        gi.appendChild(gb);
        gl.appendChild(gi);
      }
      gl.appendChild(el('li', 'chats-empty', t('studio.history.guestEmpty', { days: days })));
      box.appendChild(gl);
    }
    if (user && (open || o.side)) {
      var list = el('ul', 'chats-list');
      if (!items.length) list.appendChild(el('li', 'chats-empty', t('studio.history.empty')));
      items.forEach(function (it) {
        var li = el('li', 'chats-item' + (it.id === chatId ? ' is-on' : ''));
        var b = el('button', 'chats-open');
        b.type = 'button';
        if (it.id === chatId) b.setAttribute('aria-current', 'true');
        b.appendChild(el('span', 'chats-name', it.title || t('studio.history.untitled')));
        b.appendChild(el('span', 'chats-when', o.ago ? o.ago(it.updated_at) : ''));
        b.addEventListener('click', function () { openChat(it.id); });
        li.appendChild(b);
        var x = el('button', 'chats-del');
        x.type = 'button';
        x.setAttribute('aria-label', t('studio.history.delete', { title: it.title || '' }));
        x.title = t('studio.history.deleteShort');
        x.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"></path></svg>';
        x.addEventListener('click', function () { remove(it.id); });
        li.appendChild(x);
        list.appendChild(li);
      });
      box.appendChild(list);
    }
    box.appendChild(el('p', 'chats-note', t(user ? 'studio.history.noteAuthed' : 'studio.history.noteGuest', { days: days })));
  }

  function init(opts) {
    o = opts;
    open = ls('get', OPEN_KEY) === '1';
    renderBox();
    // закрыли вкладку / ушли на /auth или /account — дописать последнее
    window.addEventListener('pagehide', function () { flush(true); });
    document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'hidden') flush(true); });
  }

  window.AishHistory = {
    init: init, watch: watch, boot: boot, setUser: setUser, detach: detach, logout: logout, flush: flush,
    openChat: openChat, refreshList: refreshList, clean: clean,
    current: function () { return chatId; },
    _DAY: DAY
  };
})();
