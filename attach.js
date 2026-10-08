/* Скрепка студии: выбор файла, перетаскивание, вставка из буфера, загрузка с прогрессом,
 * превью-плашки над кнопками, передача в /api/generate.
 *
 *   AishAttach.init({ composer, button, getModel, t, csrf, onChange })
 *   AishAttach.payload(model)  → { body: {image?, audio?, video?}, unsupported: [...] }
 *   AishAttach.busy()          → true, пока что-то загружается
 *   AishAttach.has(kind)       → есть готовый файл этого типа
 *   AishAttach.park()          → спрятать плашки после отправки в чат (файлы остаются для /api/generate)
 *   AishAttach.consume()       → убрать файлы после запуска генерации (на сервере живут сутки)
 *   AishAttach.open()          → открыть выбор файла (кнопка «Прикрепить» ассистента)
 *
 * Можно прикрепить несколько файлов одного типа. В /api/generate уходит первое
 * поддерживаемое фото / аудио / видео (контракт API — по одному полю на тип).
 */
(function () {
  'use strict';

  var KINDS = ['image', 'audio', 'video'];
  var MAX_ITEMS = 12;
  var ACCEPT = {
    image: 'image/jpeg,image/png,image/webp,image/gif',
    audio: 'audio/mpeg,audio/mp3,audio/wav,audio/x-wav,audio/mp4,audio/x-m4a,audio/ogg,audio/flac,audio/webm,.mp3,.wav,.m4a,.ogg,.flac',
    video: 'video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm'
  };
  var MAX_MB = { image: 20, audio: 30, video: 100 };   // как на сервере (UPLOAD_MAX_*_MB)
  var RU = {
    'attach.add': 'Прикрепить файл',
    'attach.remove': 'Убрать файл {name}',
    'attach.uploading': 'Загружаю… {pct}%',
    'attach.ready': 'Готово',
    'attach.retry': 'Повторить',
    'attach.drop': 'Отпустите, чтобы прикрепить',
    'attach.kind.image': 'Фото',
    'attach.kind.audio': 'Аудио',
    'attach.kind.video': 'Видео',
    'attach.notFor': '{model} не принимает {kind} — файл не уйдёт в генерацию',
    'attach.noFiles': '{model} работает только с текстом. Выберите модель «из фото» — или отправьте без файла',
    'attach.err.too_large': 'Файл больше {mb} МБ',
    'attach.err.type': 'Этот формат не подходит. Нужны JPG, PNG, WebP, GIF, MP3, WAV, M4A, MP4, MOV',
    'attach.err.heic': 'HEIC не поддерживается — сохраните фото как JPG',
    'attach.err.network': 'Не загрузилось — проверьте интернет',
    'attach.err.rate': 'Слишком много файлов подряд — подождите пару минут',
    'attach.err.server': 'Не получилось сохранить файл, попробуйте ещё раз',
    'attach.err.bad': 'Файл повреждён',
    'attach.announce.added': 'Прикреплено: {name}',
    'attach.announce.removed': 'Файл убран',
    'attach.and': ' и ',
    'attach.kb': '{n} КБ',
    'attach.mb': '{n} МБ'
  };

  var S = {
    items: [],            // {lid, kind, name, size, status, pct, id, preview, error, xhr}
    opts: null,
    input: null,
    tray: null,
    live: null,
    dragDepth: 0
  };

  function t(key, p) {
    var o = S.opts;
    var full = 'studio.' + key;
    var s = null;
    if (o && typeof o.t === 'function') {
      try { s = o.t(full, p); } catch (_) { s = null; }
      if (s === full) s = null;
    }
    if (!s) s = RU[key] || key;
    return String(s).replace(/\{(\w+)\}/g, function (_, k) { return p && p[k] != null ? p[k] : ''; });
  }

  function fmtSize(n) {
    if (n >= 1024 * 1024) {
      var mb = Number((n / 1024 / 1024).toFixed(n >= 10 * 1024 * 1024 ? 0 : 1));
      var lang = (document.documentElement.lang || 'ru').slice(0, 2);
      return t('attach.mb', { n: mb.toLocaleString(lang === 'en' ? 'en-US' : 'ru-RU') });
    }
    return t('attach.kb', { n: Math.max(1, Math.round(n / 1024)) });
  }

  function kindOf(file) {
    var type = (file.type || '').toLowerCase();
    var name = (file.name || '').toLowerCase();
    if (type.indexOf('image/') === 0 || /\.(jpe?g|png|webp|gif|heic|heif|avif)$/.test(name)) return 'image';
    if (type.indexOf('audio/') === 0 || /\.(mp3|wav|m4a|ogg|flac|aac)$/.test(name)) return 'audio';
    if (type.indexOf('video/') === 0 || /\.(mp4|mov|webm|m4v)$/.test(name)) return 'video';
    return '';
  }

  function modelInputs(model) {
    var ins = (model && model.inputs) || [];
    return KINDS.filter(function (k) { return ins.indexOf(k) >= 0; });
  }

  function announce(text) {
    if (!S.live) return;
    S.live.textContent = '';
    setTimeout(function () { S.live.textContent = text; }, 30);
  }

  function changed() {
    render();
    if (S.opts && typeof S.opts.onChange === 'function') {
      try { S.opts.onChange(api.state()); } catch (_) {}
    }
  }

  /* ---------- загрузка ---------- */

  function errorText(code, kind, data) {
    if (code === 'file_too_large') return t('attach.err.too_large', { mb: (data && data.max_mb) || MAX_MB[kind] || 20 });
    if (code === 'unsupported_type') return t('attach.err.type');
    if (code === 'heic_unsupported') return t('attach.err.heic');
    if (code === 'rate_limited') return t('attach.err.rate');
    if (code === 'bad_file' || code === 'image_too_big' || code === 'empty_file') return t('attach.err.bad');
    if (code === 'network') return t('attach.err.network');
    return t('attach.err.server');
  }

  function upload(item, file) {
    item.status = 'uploading';
    item.pct = 0;
    item.error = '';
    changed();
    var csrfP = (S.opts && S.opts.csrf) ? Promise.resolve(S.opts.csrf()) : Promise.resolve('');
    csrfP.then(function (token) {
      if (item.status !== 'uploading') return;   // успели убрать
      var xhr = new XMLHttpRequest();
      item.xhr = xhr;
      xhr.open('POST', '/api/uploads');
      xhr.withCredentials = true;
      if (token) xhr.setRequestHeader('X-CSRF-Token', token);
      xhr.upload.onprogress = function (e) {
        if (!e.lengthComputable) return;
        item.pct = Math.min(99, Math.round(e.loaded / e.total * 100));
        renderItem(item);
      };
      xhr.onload = function () {
        item.xhr = null;
        var data = {};
        try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) {}
        if (xhr.status === 201 || xhr.status === 200) {
          item.status = 'ready';
          item.pct = 100;
          item.id = data.id;
          item.kind = data.kind || item.kind;
          item.size = data.size || item.size;
          if (!item.preview && data.preview_url && item.kind === 'image') item.preview = data.preview_url;
          announce(t('attach.announce.added', { name: item.name }));
        } else {
          item.status = 'error';
          item.error = errorText(data.error || (xhr.status === 413 ? 'file_too_large' : 'server'), item.kind, data);
          item.file = file;
        }
        changed();
      };
      xhr.onerror = function () {
        item.xhr = null;
        item.status = 'error';
        item.error = errorText('network', item.kind);
        item.file = file;
        changed();
      };
      var fd = new FormData();
      fd.append('file', file, file.name || ('file.' + (item.kind === 'image' ? 'png' : 'bin')));
      xhr.send(fd);
    });
  }

  function addFiles(list) {
    var files = Array.prototype.slice.call(list || []);
    var room = Math.max(0, MAX_ITEMS - S.items.filter(isLive).length);
    files.slice(0, room).forEach(function (file) {
      var kind = kindOf(file);
      var item = {
        lid: 'a' + Date.now() + Math.random().toString(16).slice(2, 6),
        kind: kind || 'file',
        name: file.name || 'файл',
        size: file.size || 0,
        status: 'error',
        pct: 0,
        id: '',
        preview: '',
        error: ''
      };
      S.items.push(item);
      if (!kind) { item.error = t('attach.err.type'); changed(); return; }
      if (/\.(heic|heif)$/i.test(file.name || '') || /heic|heif/i.test(file.type || '')) { item.error = t('attach.err.heic'); changed(); return; }
      if (file.size > MAX_MB[kind] * 1024 * 1024) { item.error = t('attach.err.too_large', { mb: MAX_MB[kind] }); changed(); return; }
      if (kind === 'image' && window.URL && URL.createObjectURL) item.preview = URL.createObjectURL(file);
      upload(item, file);
    });
  }

  function remove(lid, silent) {
    var item = S.items.find(function (x) { return x.lid === lid; });
    if (!item) return;
    if (item.xhr) { try { item.xhr.abort(); } catch (_) {} }
    item.status = 'removed';
    if (item.preview && item.preview.indexOf('blob:') === 0) { try { URL.revokeObjectURL(item.preview); } catch (_) {} }
    if (item.id) {
      var p = (S.opts && S.opts.csrf) ? Promise.resolve(S.opts.csrf()) : Promise.resolve('');
      p.then(function (token) {
        fetch('/api/uploads/' + encodeURIComponent(item.id), {
          method: 'DELETE', credentials: 'same-origin', headers: token ? { 'X-CSRF-Token': token } : {}
        }).catch(function () {});
      });
    }
    S.items = S.items.filter(function (x) { return x.lid !== lid; });
    if (!silent) announce(t('attach.announce.removed'));
    changed();
  }

  /* ---------- отрисовка ---------- */

  var ICON = {
    image: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="3"></rect><circle cx="9" cy="10" r="2"></circle><path d="M21 16l-5-5-9 9"></path></svg>',
    audio: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l11-2v13"></path><circle cx="6" cy="18" r="3"></circle><circle cx="17" cy="16" r="3"></circle></svg>',
    video: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="13" height="12" rx="2"></rect><path d="M16 10l5-3v10l-5-3z"></path></svg>',
    x: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"></path></svg>',
    warn: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01"></path><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"></path></svg>'
  };

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
  }

  function currentModel() {
    try { return S.opts && S.opts.getModel ? S.opts.getModel() : null; } catch (_) { return null; }
  }

  function itemHTML(item) {
    var model = currentModel();
    var ins = modelInputs(model);
    var notFor = item.status === 'ready' && model && ins.indexOf(item.kind) < 0;
    var thumb = item.kind === 'image' && item.preview
      ? '<img src="' + esc(item.preview) + '" alt="" loading="lazy">'
      : ICON[item.kind] || ICON.image;
    var sub;
    if (item.status === 'uploading') sub = '<span class="att-sub">' + esc(t('attach.uploading', { pct: item.pct || 0 })) + '</span>';
    else if (item.status === 'error') sub = '<span class="att-sub att-err">' + esc(item.error) + '</span>';
    else if (notFor) sub = '<span class="att-sub att-warn">' + ICON.warn + esc(t('attach.notFor', { model: model.name || '', kind: t('attach.kind.' + item.kind).toLowerCase() })) + '</span>';
    else sub = '<span class="att-sub">' + esc(t('attach.kind.' + item.kind)) + ' · ' + esc(fmtSize(item.size)) + '</span>';
    var retry = item.status === 'error' && item.file
      ? '<button type="button" class="att-retry" data-att-retry="' + item.lid + '">' + esc(t('attach.retry')) + '</button>' : '';
    return '<div class="att-item att-' + item.status + (notFor ? ' att-notfor' : '') + '" role="listitem" data-att="' + item.lid + '">'
      + '<span class="att-thumb">' + thumb + '</span>'
      + '<span class="att-meta"><span class="att-name" title="' + esc(item.name) + '">' + esc(item.name) + '</span>' + sub + '</span>'
      + retry
      + '<button type="button" class="att-x" data-att-x="' + item.lid + '" aria-label="' + esc(t('attach.remove', { name: item.name })) + '">' + ICON.x + '</button>'
      + (item.status === 'uploading' ? '<span class="att-bar" style="width:' + (item.pct || 0) + '%"></span>' : '')
      + '</div>';
  }

  function renderItem(item) {
    if (!S.tray) return;
    var el = S.tray.querySelector('[data-att="' + item.lid + '"]');
    if (!el) { render(); return; }
    var bar = el.querySelector('.att-bar');
    if (bar) bar.style.width = (item.pct || 0) + '%';
    var sub = el.querySelector('.att-sub');
    if (sub && item.status === 'uploading') sub.textContent = t('attach.uploading', { pct: item.pct || 0 });
  }

  function isLive(x) { return x.status !== 'removed' && x.status !== 'parked'; }
  function isUsable(x) { return (x.status === 'ready' || x.status === 'parked') && x.id; }

  function render() {
    if (!S.tray) return;
    var list = S.items.filter(isLive);
    S.tray.hidden = !list.length;
    S.tray.innerHTML = list.map(itemHTML).join('');
    var btn = S.opts && S.opts.buttonEl;
    if (btn) btn.classList.toggle('att-has', list.some(function (x) { return x.status === 'ready'; }));
    syncAccept();
  }

  function syncAccept() {
    if (!S.input) return;
    var ins = modelInputs(currentModel());
    var kinds = ins.length ? ins : KINDS;   // модель только с текстом — всё равно даём выбрать (ассистент подберёт другую)
    S.input.accept = kinds.map(function (k) { return ACCEPT[k]; }).join(',');
  }

  /* ---------- события ---------- */

  function onDragEnter(e) {
    if (!hasFiles(e)) return;
    e.preventDefault();
    S.dragDepth++;
    S.opts.composerEl.classList.add('att-drop');
    S.opts.composerEl.setAttribute('data-drop-text', t('attach.drop'));
  }
  function onDragLeave(e) {
    if (!hasFiles(e)) return;
    S.dragDepth = Math.max(0, S.dragDepth - 1);
    if (!S.dragDepth) S.opts.composerEl.classList.remove('att-drop');
  }
  function onDragOver(e) { if (hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } }
  function onDrop(e) {
    if (!hasFiles(e)) return;
    e.preventDefault();
    S.dragDepth = 0;
    S.opts.composerEl.classList.remove('att-drop');
    addFiles(e.dataTransfer.files);
  }
  function hasFiles(e) {
    var dt = e.dataTransfer;
    if (!dt || !dt.types) return false;
    return Array.prototype.indexOf.call(dt.types, 'Files') >= 0;
  }
  function onPaste(e) {
    var cd = e.clipboardData;
    if (!cd || !cd.files || !cd.files.length) return;
    var imgs = Array.prototype.filter.call(cd.files, function (f) { return kindOf(f); });
    if (!imgs.length) return;
    e.preventDefault();
    addFiles(imgs);
  }

  /* ---------- публичное API ---------- */

  var api = {
    init: function (opts) {
      S.opts = opts || {};
      var composer = typeof opts.composer === 'string' ? document.querySelector(opts.composer) : opts.composer;
      var button = typeof opts.button === 'string' ? document.querySelector(opts.button) : opts.button;
      if (!composer || !button) return api;
      S.opts.composerEl = composer;
      S.opts.buttonEl = button;

      S.input = document.createElement('input');
      S.input.type = 'file';
      S.input.multiple = true;
      S.input.hidden = true;
      S.input.setAttribute('data-attach-input', '');
      S.input.setAttribute('tabindex', '-1');
      S.input.setAttribute('aria-hidden', 'true');
      composer.appendChild(S.input);
      S.input.addEventListener('change', function () {
        if (S.input.files && S.input.files.length) addFiles(S.input.files);
        S.input.value = '';
      });

      S.tray = document.createElement('div');
      S.tray.className = 'att-tray';
      S.tray.setAttribute('role', 'list');
      S.tray.hidden = true;
      var row = button.parentElement;
      composer.insertBefore(S.tray, row && row.parentElement === composer ? row : composer.firstChild);

      S.live = document.createElement('span');
      S.live.className = 'sr-only';
      S.live.setAttribute('aria-live', 'polite');
      composer.appendChild(S.live);

      button.addEventListener('click', function (e) { e.preventDefault(); api.open(); });
      S.tray.addEventListener('click', function (e) {
        var x = e.target.closest('[data-att-x]');
        if (x) { remove(x.getAttribute('data-att-x')); return; }
        var r = e.target.closest('[data-att-retry]');
        if (r) {
          var it = S.items.find(function (i) { return i.lid === r.getAttribute('data-att-retry'); });
          if (it && it.file) upload(it, it.file);
        }
      });
      composer.addEventListener('dragenter', onDragEnter);
      composer.addEventListener('dragleave', onDragLeave);
      composer.addEventListener('dragover', onDragOver);
      composer.addEventListener('drop', onDrop);
      composer.addEventListener('paste', onPaste);
      syncAccept();
      return api;
    },
    open: function () { if (S.input) { syncAccept(); S.input.click(); } },
    add: addFiles,
    remove: function (lid) { remove(lid); },
    refresh: render,
    busy: function () { return S.items.some(function (x) { return x.status === 'uploading'; }); },
    has: function (kind) { return S.items.some(function (x) { return isUsable(x) && (!kind || x.kind === kind); }); },
    state: function () {
      return S.items.filter(isLive).map(function (x) {
        return { kind: x.kind, name: x.name, size: x.size, status: x.status, id: x.id };
      });
    },
    /* Что положить в /api/generate для этой модели. unsupported — готовые файлы, которые модель не возьмёт.
     * В body — первое готовое фото / аудио / видео (API принимает по одному полю на тип). */
    payload: function (model) {
      var ins = modelInputs(model);
      var body = {};
      var unsupported = [];
      var files = [];
      S.items.forEach(function (x) {
        if (!isUsable(x)) return;
        if (ins.indexOf(x.kind) >= 0) {
          if (!body[x.kind]) {
            body[x.kind] = x.id;
            files.push({ kind: x.kind, name: x.name });
          }
        } else unsupported.push(x.kind);
      });
      return { body: body, unsupported: unsupported, files: files };
    },
    /* Готовые файлы для ассистента: [{kind, name, id}] — он называет их по имени */
    ready: function () {
      return S.items.filter(isUsable)
        .map(function (x) { return { kind: x.kind, name: x.name, id: x.id }; });
    },
    /* «фото «cat.png» и аудио «voice.wav»» */
    describe: function (files) {
      var en = (document.documentElement.lang || '').slice(0, 2) === 'en';
      var parts = (files || []).map(function (f) {
        return t('attach.kind.' + f.kind).toLowerCase() + (en ? ' “' + f.name + '”' : ' «' + f.name + '»');
      });
      if (parts.length < 2) return parts.join('');
      return parts.slice(0, -1).join(', ') + t('attach.and') + parts[parts.length - 1];
    },
    /* После отправки в чат: плашки убрать, номера файлов оставить до генерации. */
    park: function () {
      var n = 0;
      S.items.forEach(function (x) {
        if (x.status === 'ready') {
          x.status = 'parked';
          if (x.preview && x.preview.indexOf('blob:') === 0) {
            try { URL.revokeObjectURL(x.preview); } catch (_) {}
            x.preview = '';
          }
          n++;
        }
      });
      if (n) changed();
    },
    consume: function () {
      S.items.forEach(function (x) {
        if (x.preview && x.preview.indexOf('blob:') === 0) { try { URL.revokeObjectURL(x.preview); } catch (_) {} }
      });
      S.items = [];
      changed();
    },
    noFilesText: function (model) { return t('attach.noFiles', { model: (model && model.name) || '' }); }
  };

  window.AishAttach = api;
})();
