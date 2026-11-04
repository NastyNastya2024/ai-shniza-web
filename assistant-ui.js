/* Чат-ассистент студии {AI}-шница: клиент + отрисовка карточек. Без зависимостей.
 *
 * Сервер (POST /api/assistant/chat) отвечает {text, blocks, chips, generate_*, lang, ...}.
 * Блоки: models | prompt | params | summary (см. assistant/render.py).
 *
 * ВАРИАНТ A — самостоятельный чат (demo/demo.html):
 *   const chat = AssistantUI.mount({ root, api, getContext, onFillForm, onGenerate, onUiAction });
 *   chat.send('кот жарит яичницу');
 *
 * ВАРИАНТ B — встроить в существующий список сообщений app.html (#msgs + msgEl):
 *   const eggy = AssistantUI.controller({ api, getContext, onFillForm, onGenerate, onUiAction,
 *     avatarHTML: '<span class="bot-av">…orb…</span>',
 *     onUser: (label) => push({role:'user', text: label}),        // эхо нажатой кнопки
 *     onBot: (data) => push({role:'bot', assistant: data}),       // новое сообщение ассистента
 *     onTyping: (on) => setState({typing: on}) });
 *   eggy.send(text);                                              // вместо fetch('/api/chat')
 *   // в msgEl(m): if (m.assistant) return eggy.render(m.assistant);
 *   // смена параметра НЕ добавляет сообщение: eggy сам перерисует последнее «настроечное» на месте.
 */
(function (root) {
  'use strict';
  var SERVER = { pick_model: 1, more: 1, choose_type: 1, has_prompt: 1, add_prompt: 1, use_mine: 1, param: 1, pick_camera: 1, refine: 1, improve: 1, send: 1,
    similar: 1, cheaper: 1, faster: 1, no_photo_model: 1, rephrase: 1, resume: 1,
    brief: 1, variants: 1, more_variants: 1, back_brief: 1, back: 1, use_variant: 1, skip_polish: 1, restart: 1,
    reel_start: 1, reel_answer: 1, reel_next: 1, reel_back: 1, reel_edit: 1, reel_frame: 1, reel_rebuild: 1,
    reel_sheet: 1, reel_exit: 1,
    sb_start: 1, sb_noscript: 1, sb_answer: 1, sb_edit: 1, sb_frame: 1, sb_rebuild: 1, sb_setup: 1, sb_frames_view: 1, sb_back: 1, sb_exit: 1,
    pipe_result: 1, pipe_menu: 1, pipe_stage: 1, pipe_sub: 1, pipe_dialog_save: 1, pipe_video_plain: 1, pipe_voice_model: 1, pipe_summary: 1, pipe_arts: 1,
    mode_start: 1, mode_input: 1, mode_next: 1, mode_back: 1, mode_redo: 1, mode_go: 1, mode_episode: 1, mode_exit: 1, mode_pause: 1, mode_resume: 1,
    tree_hint: 1, tree_event: 1, edit_prompt: 1, files_confirm: 1, files_drop: 1, files_sync: 1, media_pick: 1, resume_task: 1,
    model_switch: 1, switch_pick: 1, text_note: 1, look_done: 1, look_skip: 1, look_next: 1, make: 1,
    lock_keep: 1, lock_switch: 1, intent_option: 1, format_cat: 1, format_sub: 1, format_send: 1,
    idea_next: 1, idea_alt: 1, path_photos: 1, path_board: 1, path_direct: 1, flow_polish: 1,
    flow_slot: 1, flow_next: 1, flow_show: 1, flow_skip: 1,
    open_mcp: 1, mcp_goal: 1, mcp_compare: 1, mcp_try: 1, mcp_connected: 1, mcp_failed: 1, mcp_support: 1, mcp_topic: 1,
    ui_more: 1 };
  var PIPE_TYPE_ICON = { prompt: '✍️', videoPrompt: '🎬', speechPrompt: '🎙', style: '{ }', hero: '👤', image: '🖼', board: '🎞', video: '🎬', voiceTrack: '🔊' };
  var KIND_ICON = { prompt: '✍️', image: '🖼', video: '🎬', music: '🎵', text: '✍️', sfx: '🔊', edit: '✏️' };

  /* метрики сайта (aish-metrics.js): что ответил помощник и какие кнопки жмут */
  function M(n, p) { try { if (root.AishM) root.AishM.track(n, p); } catch (e) {} }
  function short(v) { return v == null ? '' : (typeof v === 'object' ? '' : String(v).slice(0, 40)); }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  /* ---------------------------------------------------------------- controller */
  function controller(opts) {
    var url = opts.url || '/api/assistant/chat';
    var busy = false;
    var lang = 'ru';
    var form = { model: null, prompt: '', params: {} };
    var summarySaved = '';
    var summaryDraft = null;
    var summaryTimer = 0;
    var summarySave = null;
    var setupNode = null;
    var lastBody = null;
    var allNodes = [];
    var pendingCamPreview = null;
    var pipeExpect = null;          // флоу помощника ждёт результат генерации → после неё шлём pipe_result   // «смотреть пример» → сначала выбрать движение, потом открыть витрину

    function L(ru, en) { return lang === 'en' ? en : ru; }

    function chipBtn(c) {
      var btn = el('button', 'aich-chip' + (c.primary ? ' aich-chip--primary' : '') + (c.action === 'reel_start' ? ' aich-chip--reel' : '') + (c.action === 'sb_start' ? ' aich-chip--sb' : '') + (c.action === 'tree_hint' ? ' aich-chip--tree' : ''), c.label);
      btn.type = 'button';
      if (c.action === 'choose_type' && KIND_ICON[c.value]) btn.textContent = KIND_ICON[c.value] + ' ' + c.label;
      btn.addEventListener('click', function (e) {
        var row = e.target.closest && e.target.closest('.aich-row, .aich-block, .aich');
        var area = row && (row.querySelector('.aich-summary__prompt') || row.querySelector('.aich-prompt__area'));
        onChip(c, area && area.value);
      });
      return btn;
    }

    /** Типы (видео/картинка/…) и примеры — отдельными рядами, если в ответе есть и то и другое. */
    function renderChips(list) {
      var types = [], examples = [], rest = [];
      // главное меню флоу (Промпт · Картинка · Раскадровка · Видео · Озвучка) — первым рядом, как типы
      var menuRow = (list || []).filter(function (c) { return c && c.action === 'pipe_stage'; }).length >= 4;
      (list || []).forEach(function (c) {
        // устаревшие кнопки воронки «создать ролик» / этапы проекта — больше не показываем
        if (!c || !c.action || /^project_/.test(c.action)) return;
        if (c.action === 'choose_type' || (menuRow && c.action === 'pipe_stage') || (c.action === 'reel_start' && c.value !== 'new') || (c.action === 'sb_start' && c.value !== 'new')) types.push(c);
        else if (c.example || (c.action === 'send' && c.value && String(c.value).length > 12)) examples.push(c);
        else rest.push(c);
      });
      var wrap = el('div', 'aich-chips-wrap');
      if (types.length) {
        var row1 = el('div', 'aich-chips aich-chips--types');
        types.forEach(function (c) { row1.appendChild(chipBtn(c)); });
        wrap.appendChild(row1);
      }
      if (examples.length) {
        var row2 = el('div', 'aich-chips aich-chips--examples');
        examples.forEach(function (c) { row2.appendChild(chipBtn(c)); });
        wrap.appendChild(row2);
      }
      if (rest.length) {
        var row3 = el('div', 'aich-chips');
        rest.forEach(function (c) { row3.appendChild(chipBtn(c)); });
        wrap.appendChild(row3);
      }
      return wrap.childNodes.length === 1 ? wrap.firstChild : wrap;
    }

    function modelCard(it) {
      var card = el('button', 'aich-model');
      card.type = 'button';
      var top = el('div', 'aich-model__top');
      top.appendChild(el('span', 'aich-model__title', it.title));
      if (it.badge) top.appendChild(el('span', 'aich-badge', it.badge));
      card.appendChild(top);
      card.appendChild(el('div', 'aich-model__why', it.why));
      if (it.note) card.appendChild(el('div', 'aich-model__note', it.note));
      var priceLine = it.estimate || it.price;
      if (priceLine) card.appendChild(el('div', 'aich-model__price', priceLine));
      if (!it.estimate && it.speed) card.appendChild(el('div', 'aich-model__sub', it.speed));
      if (it.cta) {
        card.appendChild(el('span', 'aich-model__cta', it.cta));
      } else if (it.vitrina_url) {
        var link = el('a', 'aich-model__link', L('Примеры на витрине →', 'Examples in showcase →'));
        link.href = it.vitrina_url;
        link.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          if (opts.onUiAction) opts.onUiAction('open_vitrina', it.id);
          else location.href = it.vitrina_url;
        });
        card.appendChild(link);
      }
      card.addEventListener('click', function () { onChip({ label: it.title, action: 'pick_model', value: it.id }); });
      return card;
    }

    function renderModels(bl) {
      var wrap = el('div', 'aich-models-wrap');
      var grid = el('div', 'aich-models');
      var items = bl.items || [];
      var shown = 6;
      function paint() {
        grid.textContent = '';
        items.slice(0, shown).forEach(function (it) { grid.appendChild(modelCard(it)); });
        var old = wrap.querySelector('.aich-models__more');
        if (old) old.remove();
        if (shown < items.length) {
          var more = el('button', 'aich-models__more', L('Ещё модели', 'More models'));
          more.type = 'button';
          more.addEventListener('click', function () {
            shown = Math.min(items.length, shown + 6);
            paint();
          });
          wrap.appendChild(more);
        }
      }
      wrap.appendChild(grid);
      paint();
      return wrap;
    }

    function expandSvg(open) {
      var d = open
        ? 'M8 4v4H4M16 4v4h4M8 20v-4H4M16 20v-4h4'
        : 'M4 8V4h4M20 8V4h-4M4 16v4h4M20 16v4h-4';
      return '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="' + d + '"></path></svg>';
    }

    /** Поле промпта: правка прямо в тексте и иконка «Развернуть». */
    function promptExpand(ta) {
      var open = false;
      var btn = el('button', 'aich-prompt__expand');
      btn.type = 'button';
      btn.setAttribute('aria-expanded', 'false');
      function paint() {
        var name = open ? L('Свернуть', 'Collapse') : L('Развернуть', 'Expand');
        btn.innerHTML = expandSvg(open);
        btn.setAttribute('aria-label', name);
        btn.title = name;
      }
      function fit() {
        if (!open) { ta.style.height = ''; return; }
        ta.style.height = 'auto';
        ta.style.height = Math.max(140, ta.scrollHeight + 2) + 'px';
      }
      paint();
      btn.addEventListener('click', function () {
        open = !open;
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        ta.classList.toggle('is-open', open);
        paint();
        fit();
      });
      ta.addEventListener('input', fit);
      return btn;
    }

    function renderPrompt(bl) {
      var box = el('div', 'aich-prompt');
      box.appendChild(el('div', 'aich-prompt__label', bl.label ? bl.title : L('Промпт для ', 'Prompt for ') + bl.title));
      var txt = el('textarea', 'aich-prompt__text aich-prompt__area');
      txt.value = bl.text || '';
      txt.rows = 6;
      txt.spellcheck = false;
      txt.addEventListener('input', function () {
        form.prompt = txt.value.trim();
        opts.onFillForm && opts.onFillForm({ model: form.model, prompt: form.prompt, params: form.params, ready: true });
      });
      box.appendChild(txt);
      box.appendChild(promptExpand(txt));
      if (bl.note) box.appendChild(el('div', 'aich-prompt__note', bl.note));
      box.appendChild(el('div', 'aich-prompt__hint', L('можно исправить прямо здесь', 'you can edit it right here')));
      return box;
    }

    /** Режимы «Рилс» / «Сериал»: сценарий, герои, подпись — по строкам, только чтение (правка — сообщением). */
    function renderModeText(bl) {
      var box = el('div', 'aich-mtext');
      if (bl.title) box.appendChild(el('div', 'aich-mtext__title', bl.title));
      box.appendChild(el('div', 'aich-mtext__text', bl.text || ''));
      if (bl.note) box.appendChild(el('div', 'aich-mtext__note', bl.note));
      return box;
    }

    function renderParams(bl) {
      var wrap = el('div', 'aich-params');
      bl.groups.forEach(function (g) {
        var row = el('div', 'aich-param');
        row.appendChild(el('div', 'aich-param__label', g.label));
        var box = el('div', 'aich-param__opts');
        g.options.forEach(function (o) {
          var b = el('button', 'aich-opt' + (o.selected ? ' is-on' : ''), o.label);
          b.type = 'button';
          b.setAttribute('aria-pressed', o.selected ? 'true' : 'false');
          b.addEventListener('click', function () {
            if (o.selected) return;
            post({ action: { type: 'param', value: { name: g.name, value: o.value } } }, true);
          });
          box.appendChild(b);
        });
        row.appendChild(box);
        wrap.appendChild(row);
      });
      return wrap;
    }

    /** Движения камеры: сначала тип, затем сабменю-табы; по умолчанию — без движения. */
    function renderCamera(bl) {
      var wrap = el('div', 'aich-camera');
      var head = el('div', 'aich-camera__head');
      head.appendChild(el('div', 'aich-param__label', bl.label || L('Добавим движение камеры?', 'Add a camera move?')));
      if (bl.hint) head.appendChild(el('div', 'aich-prompt__hint', bl.hint));
      wrap.appendChild(head);

      var selected = (bl.items || []).find(function (it) { return it.selected; });
      /* Сабменю только после выбора типа; если уже выбрано движение — открываем его группу */
      var activeGroup = selected && selected.group ? selected.group : '';
      var groups = bl.groups || [];

      var gRow = el('div', 'aich-camera__groups');
      var clear = el('button', 'aich-opt aich-camera__none' + (!selected ? ' is-on' : ''),
                     L('Без движения', 'No move'));
      clear.type = 'button';
      clear.addEventListener('click', function () {
        activeGroup = '';
        post({ action: { type: 'pick_camera', value: 'none' } }, true);
      });
      gRow.appendChild(clear);
      wrap.appendChild(gRow);

      var sub = el('div', 'aich-camera__sub');
      sub.hidden = true;
      wrap.appendChild(sub);

      function openVitSide(workId, fallbackHref) {
        if (window.vitOpenWork && workId && window.vitOpenWork(workId)) return;
        if (fallbackHref) location.href = fallbackHref;
      }
      function pickMove(it, alsoPreview) {
        if (it.selected) {
          if (alsoPreview) openVitSide(it.work_id, it.vitrina);
          return;
        }
        /* таб: выбираем движение; «смотреть пример» ещё и открывает витрину после ответа */
        if (alsoPreview) pendingCamPreview = { work_id: it.work_id, vitrina: it.vitrina };
        post({ action: { type: 'pick_camera', value: it.id } }, true).then(function () {
          if (!alsoPreview || !pendingCamPreview) return;
          var p = pendingCamPreview;
          pendingCamPreview = null;
          openVitSide(p.work_id, p.vitrina);
        });
      }
      function paintGroups() {
        gRow.textContent = '';
        gRow.appendChild(clear);
        groups.forEach(function (g) {
          var b = el('button', 'aich-opt aich-camera__gchip' + (activeGroup === g.id ? ' is-on' : ''), g.label);
          b.type = 'button';
          b.setAttribute('aria-pressed', activeGroup === g.id ? 'true' : 'false');
          b.addEventListener('click', function () {
            activeGroup = g.id;
            refresh();
          });
          gRow.appendChild(b);
        });
      }
      function paintSub() {
        sub.textContent = '';
        if (!activeGroup) {
          sub.hidden = true;
          return;
        }
        sub.hidden = false;
        var row = el('div', 'aich-camera__row');
        row.setAttribute('role', 'tablist');
        var n = 0;
        (bl.items || []).forEach(function (it) {
          if (it.group !== activeGroup) return;
          n += 1;
          var card = el('div', 'aich-camera__chip' + (it.selected ? ' is-on' : ''));
          var pick = el('button', 'aich-camera__name');
          pick.type = 'button';
          pick.setAttribute('role', 'tab');
          pick.setAttribute('aria-selected', it.selected ? 'true' : 'false');
          pick.setAttribute('aria-pressed', it.selected ? 'true' : 'false');
          pick.textContent = it.title;
          pick.addEventListener('click', function () { pickMove(it, false); });
          card.appendChild(pick);
          if (it.work_id || it.vitrina) {
            var ex = el('button', 'aich-camera__example');
            ex.type = 'button';
            ex.setAttribute('aria-label', L('Выбрать и смотреть пример', 'Select and watch example'));
            ex.title = L('Выбрать и смотреть пример', 'Select and watch example');
            ex.textContent = L('смотреть пример →', 'watch example →');
            ex.addEventListener('click', function (e) {
              e.preventDefault();
              e.stopPropagation();
              pickMove(it, true);
            });
            card.appendChild(ex);
          }
          row.appendChild(card);
        });
        if (!n) {
          sub.appendChild(el('div', 'aich-prompt__hint', L('В этом типе пока нет движений', 'No moves in this type yet')));
          return;
        }
        sub.appendChild(row);
      }
      function refresh() {
        paintGroups();
        paintSub();
        clear.classList.toggle('is-on', !selected && !activeGroup);
      }

      refresh();
      return wrap;
    }

    /** Уточняющие вопросы: варианты ответов кнопками, «Не добавлять» по умолчанию. Клик — обновление на месте. */
    function renderBrief(bl) {
      var wrap = el('div', 'aich-params aich-brief');
      var open = bl.questions.filter(function (q) { return !q.options || !q.options.length; });
      if (open.length) {   // кто, где, что происходит, нюансы — отвечают своими словами
        var box0 = el('div', 'aich-open');
        var ul = el('ul', 'aich-open__list');
        open.forEach(function (q) { ul.appendChild(el('li', null, q.label)); });
        box0.appendChild(ul);
        wrap.appendChild(box0);
      }
      bl.questions.forEach(function (q) {
        if (!q.options || !q.options.length) return;
        var row = el('div', 'aich-param');
        row.appendChild(el('div', 'aich-param__label', q.label));
        var box = el('div', 'aich-param__opts');
        q.options.forEach(function (o) {
          var b = el('button', 'aich-opt' + (o.selected ? ' is-on' : ''), o.label);
          b.type = 'button';
          b.setAttribute('aria-pressed', o.selected ? 'true' : 'false');
          b.addEventListener('click', function () {
            if (o.selected) return;
            post({ action: { type: 'brief', value: { id: q.id, value: o.value } } }, true);
          });
          box.appendChild(b);
        });
        row.appendChild(box);
        wrap.appendChild(row);
      });
      return wrap;
    }

    /** Варианты промпта: текст можно дописать, «Выбрать» уносит уже дополненный вариант. */
    function renderVariants(bl) {
      var list = el('div', 'aich-variants');
      bl.items.forEach(function (v, i) {
        var card = el('div', 'aich-variant');
        var top = el('div', 'aich-variant__top');
        top.appendChild(el('span', 'aich-variant__n', String(i + 1)));
        top.appendChild(el('span', 'aich-variant__title', v.title));
        card.appendChild(top);
        var text = el('textarea', 'aich-variant__text');
        text.value = v.text || '';
        text.rows = 6;
        text.spellcheck = false;
        card.appendChild(text);
        card.appendChild(promptExpand(text));
        var cta = el('button', 'aich-variant__cta', L('Выбрать этот →', 'Use this →'));
        cta.type = 'button';
        cta.addEventListener('click', function () {
          onChip({ label: L('Вариант «', 'Option “') + v.title + L('»', '”'), action: 'use_variant', value: v.id },
                 text.value.trim());
        });
        card.appendChild(cta);
        list.appendChild(card);
      });
      return list;
    }

    function renderSummary(bl) {
      var box = el('div', 'aich-summary');
      var head = el('div', 'aich-summary__head');
      head.appendChild(el('b', null, bl.title));
      head.appendChild(el('span', 'aich-summary__price', bl.estimate || bl.price));
      box.appendChild(head);
      if (bl.params && bl.params.length) box.appendChild(el('div', 'aich-summary__params', bl.params.join(' · ')));
      if (bl.prompt) {
        box.appendChild(el('div', 'aich-prompt__label', L('Промпт для ', 'Prompt for ') + (bl.title || '')));
        var ta = el('textarea', 'aich-summary__prompt');
        ta.value = bl.prompt;
        ta.rows = 4;
        ta.addEventListener('input', function () { rememberSummary(ta.value); });
        box.appendChild(ta);
        box.appendChild(promptExpand(ta));
        summarySaved = String(bl.prompt || '').trim();
      }
      return box;
    }

    function filePreview(it) {
      if (it.work_id) return '/api/works/' + encodeURIComponent(it.work_id) + '/media';
      if (it.preview) return it.preview;
      var shots = (window.AishAttach && AishAttach.shots) ? AishAttach.shots() : [];
      var hit = shots.find(function (s) { return s.id && s.id === it.id; })
        || shots.find(function (s) { return it.file && s.name === it.file; });
      if (hit && hit.preview) return hit.preview;
      return chatResultSrc(it);
    }

    function chatResultSrc(it) {
      var kind = it.kind || '';
      if (kind !== 'image' && kind !== 'video') return '';
      var n = 0;
      var mark = String(it.origin || it.name || '').match(/№\s*(\d+)/);
      if (mark) n = parseInt(mark[1], 10) || 0;
      var msgs = (window.app && app.state && app.state.msgs) || [];
      var hits = [];
      msgs.forEach(function (row) {
        if (!row || !row.result || !(row.mediaUrl || row.workId)) return;
        var k = row.mediaKind === 'music' ? 'audio' : (row.mediaKind || 'image');
        if (k === kind) hits.push(row);
      });
      var row = (n && hits[n - 1]) || hits[hits.length - 1];
      if (!row) return '';
      if (row.workId) return '/api/works/' + encodeURIComponent(row.workId) + '/media';
      return row.mediaUrl || '';
    }

    function paintPreview(row, it, src) {
      if (!src) return;
      var old = row.querySelector('.aich-files__preview');
      if (old) old.remove();
      var node;
      if (it.kind === 'video') {
        node = document.createElement('video');
        node.muted = true;
        node.playsInline = true;
        node.preload = 'metadata';
        node.src = src;
      } else if (it.kind === 'audio') {
        return;
      } else {
        node = document.createElement('img');
        node.alt = '';
        node.src = src;
      }
      node.className = 'aich-files__preview';
      var meta = row.querySelector('.aich-files__meta');
      if (meta) row.insertBefore(node, meta);
      else row.appendChild(node);
    }

    function renderFiles(bl) {
      var box = el('div', 'aich-files');
      box.appendChild(el('div', 'aich-files__title', bl.title || L('Что отправляем', 'What we send')));
      var picked = {};
      (bl.items || []).forEach(function (it) {
        var row = el('div', 'aich-files__row');
        if (bl.need_confirm) {
          var cb = document.createElement('input');
          cb.type = 'checkbox';
          cb.checked = !!it.checked;
          if (it.checked) picked[it.id] = it.role || '';
          cb.addEventListener('change', function () {
            if (cb.checked) picked[it.id] = it.role || '';
            else delete picked[it.id];
          });
          row.appendChild(cb);
        }
        var meta = el('span', 'aich-files__meta');
        meta.appendChild(el('b', null, it.file || it.name || ''));
        meta.appendChild(el('span', null, (it.role ? it.role : '') + (it.origin ? ' · ' + it.origin : '')));
        row.appendChild(meta);
        var del = el('button', 'aich-files__del', L('Удалить', 'Remove'));
        del.type = 'button';
        del.addEventListener('click', function () {
          if (window.AishAttach && AishAttach.removeId) AishAttach.removeId(it.id);
          if (window.app && Array.isArray(app._keptFiles)) app._keptFiles = app._keptFiles.filter(function (f) { return !f || f.id !== it.id; });
          post({ action: { type: 'files_drop', value: { id: it.id } } }, true);
        });
        row.appendChild(del);
        paintPreview(row, it, filePreview(it));
        if (!row.querySelector('.aich-files__preview') && /^upl_[a-f0-9]{24}$/.test(it.id || '')) {
          fetch('/api/uploads/' + encodeURIComponent(it.id), { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
              if (data && data.preview_url && row.isConnected) paintPreview(row, it, data.preview_url);
            })
            .catch(function () {});
        }
        box.appendChild(row);
      });
      var bar = el('div', 'aich-files__bar');
      var add = el('button', 'aich-files__add', L('Прикрепить файлы', 'Attach files'));
      add.type = 'button';
      add.addEventListener('click', function () { opts.onUiAction && opts.onUiAction('attach'); });
      bar.appendChild(add);
      if (bl.need_confirm) {
        var ok = el('button', 'aich-summary__save', L('Оставить отмеченные', 'Keep the ticked ones'));
        ok.type = 'button';
        ok.addEventListener('click', function () {
          var items = Object.keys(picked).map(function (id) { return { id: id, role: picked[id] }; });
          post({ action: { type: 'files_confirm', value: { items: items } } }, true);
        });
        bar.appendChild(ok);
      }
      box.appendChild(bar);
      return box;
    }

    /* ------------------------------------------------ режим «Рилс» (reels.py) */
    var REEL_BLOCKS = { reel_steps: 1, choice: 1, reel_character: 1, reel_script: 1, reel_storyboard: 1, reel_final: 1 };

    function reelEdit(path, value) { post({ action: { type: 'reel_edit', value: { path: path, value: value } } }, true); }

    /** Поле, которое правят прямо в карточке: сохраняем на сервере, когда человек ушёл из поля. */
    function editable(tag, cls, text, path, save) {
      var n = el(tag, cls, text || '');
      n.contentEditable = 'true';
      n.spellcheck = false;
      var was = text || '';
      n.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey && tag !== 'div') { e.preventDefault(); n.blur(); } });
      n.addEventListener('blur', function () {
        var now = n.textContent.trim();
        if (now !== was.trim()) { was = now; (save || reelEdit)(path, now); }
      });
      return n;
    }

    function renderSteps(bl) {
      var box = el('div', 'reel-steps');
      if (!bl.current) { box.appendChild(el('span', 'reel-steps__label', L('Подготовка · ', 'Setup · ') + bl.label)); return box; }
      box.appendChild(el('span', 'reel-steps__label', L('Шаг ', 'Step ') + bl.current + L(' из ', ' of ') + bl.total + ' · ' + bl.label));
      var bar = el('div', 'reel-steps__bar');
      bl.steps.forEach(function (s) { var seg = el('i', 'is-' + s.state); seg.title = s.title; bar.appendChild(seg); });
      box.appendChild(bar);
      return box;
    }

    function safeUrl(u) {
      return /^https?:\/\//i.test(u || '') || (u && u.charAt(0) === '/') ? u : '';
    }

    /** Уточняющее окно: своя идея первой (раскадровка) или пронумерованные примеры. */
    function renderChoice(bl) {
      var card = el('div', 'reel-choice');
      card.appendChild(el('div', 'reel-choice__title', bl.title));
      var picked = (!bl.custom_first && bl.options.length) ? bl.options[0].id : null;
      var style = bl.extra ? (bl.extra.selected || (bl.extra.options[0] || {}).id) : null;
      var refsPicked = {};
      ((bl.refs && bl.refs.selected) || []).forEach(function (id) { refsPicked[id] = 1; });
      var items = [];
      var list = el('div', 'reel-choice__list');
      function paint() {
        items.forEach(function (it) {
          var on = it.id === picked;
          it.node.classList.toggle('is-on', on);
          it.node.setAttribute('aria-expanded', on ? 'true' : 'false');
        });
        if (own) own.classList.toggle('is-on', !picked && !!ta.value.trim());
      }
      var own = el('label', 'reel-opt reel-opt--own' + (bl.custom_first ? ' reel-opt--lead' : ''));
      if (bl.custom_label) own.appendChild(el('span', 'reel-opt__label', '✎ ' + bl.custom_label));
      else own.appendChild(el('span', 'reel-opt__n', String(bl.options.length + 1)));
      var ta = el('textarea', 'reel-opt__input');
      ta.rows = bl.custom_first ? 3 : 2;
      ta.placeholder = bl.custom_placeholder || '';
      ta.addEventListener('input', function () { if (ta.value.trim()) { picked = null; paint(); } });
      own.appendChild(ta);
      function addOption(o, i) {
        var b = el('button', 'reel-opt');
        b.type = 'button';
        var head = el('span', 'reel-opt__head');
        head.appendChild(el('span', 'reel-opt__n', String(i + 1)));
        head.appendChild(el('span', 'reel-opt__label', o.label));
        head.appendChild(el('span', 'reel-opt__chev', '›'));
        b.appendChild(head);
        if (o.detail) b.appendChild(el('span', 'reel-opt__detail', o.detail));
        b.addEventListener('click', function () { picked = o.id; ta.value = ''; paint(); });
        list.appendChild(b);
        items.push({ id: o.id, node: b });
      }
      if (bl.custom_first) {
        list.appendChild(own);
        if (bl.options.length) list.appendChild(el('div', 'reel-choice__or', L('или выберите пример', 'or pick an example')));
        bl.options.forEach(addOption);
      } else {
        bl.options.forEach(addOption);
        list.appendChild(own);
      }
      card.appendChild(list);
      if (bl.refs) {
        var rf = el('div', 'sb-refs');
        rf.appendChild(el('div', 'reel-choice__sub', bl.refs.title));
        rf.appendChild(el('p', 'sb-refs__note', bl.refs.note || ''));
        if (bl.refs.items && bl.refs.items.length) {
          var thumbs = el('div', 'sb-refs__row');
          bl.refs.items.forEach(function (it) {
            var src = safeUrl(it.url);
            if (!src) return;
            var b = el('button', 'sb-ref' + (refsPicked[it.id] ? ' is-on' : ''));
            b.type = 'button';
            var img = el('img', 'sb-ref__img');
            img.src = src; img.alt = it.title || '';
            b.appendChild(img);
            if (it.title) b.appendChild(el('span', 'sb-ref__cap', it.title));
            b.addEventListener('click', function () {
              if (refsPicked[it.id]) delete refsPicked[it.id]; else refsPicked[it.id] = 1;
              b.classList.toggle('is-on', !!refsPicked[it.id]);
            });
            thumbs.appendChild(b);
          });
          rf.appendChild(thumbs);
        }
        if (bl.refs.attached && bl.refs.attached.length) {
          rf.appendChild(el('div', 'sb-refs__got', L('Уже в скрепке: ', 'Already attached: ') + bl.refs.attached.join(', ')));
        }
        if (bl.refs.attach) {
          var att = el('button', 'aich-opt sb-refs__attach', bl.refs.attach);
          att.type = 'button';
          att.addEventListener('click', function () { opts.onUiAction && opts.onUiAction('attach'); });
          rf.appendChild(att);
        }
        card.appendChild(rf);
      }
      if (bl.extra) {
        var ex = el('div', 'reel-choice__extra');
        ex.appendChild(el('div', 'reel-choice__sub', bl.extra.title));
        var pills = el('div', 'aich-param__opts');
        bl.extra.options.forEach(function (o) {
          var p = el('button', 'aich-opt' + (o.id === style ? ' is-on' : ''), o.label);
          p.type = 'button';
          p.title = o.detail || '';
          p.addEventListener('click', function () {
            style = o.id;
            Array.prototype.forEach.call(pills.children, function (x) { x.classList.toggle('is-on', x === p); });
          });
          pills.appendChild(p);
        });
        ex.appendChild(pills);
        card.appendChild(ex);
      }
      var go = el('button', 'reel-choice__go', bl.cta || L('Продолжить', 'Continue'));
      go.type = 'button';
      go.addEventListener('click', function () {
        var text = ta.value.trim();
        if (!text && !picked) { ta.focus(); return; }
        var opt = bl.options.filter(function (o) { return o.id === picked; })[0];
        var value = { q: bl.id, option: text ? '' : picked, text: text };
        if (bl.extra) value.style = style;
        if (bl.refs) value.refs = Object.keys(refsPicked);
        opts.onUser && opts.onUser(text || (opt ? opt.label : ''));
        lastBody = { action: { type: bl.action || 'reel_answer', value: value } };
        post(lastBody);
      });
      card.appendChild(go);
      paint();
      return card;
    }

    /** Карточка персонажа на светло-сером фоне: поля правятся прямо в ней. */
    function renderCharacter(bl) {
      var wrap = el('div', 'reel-chars');
      (bl.characters || []).forEach(function (c, i) {
        var card = el('div', 'reel-char');
        var head = el('div', 'reel-char__head');
        head.appendChild(editable('span', 'reel-char__name', c.name, 'characters.' + i + '.name'));
        head.appendChild(editable('span', 'reel-char__role', c.role, 'characters.' + i + '.role'));
        card.appendChild(head);
        if (bl.refs && bl.refs.length) card.appendChild(el('div', 'reel-char__ref', L('Лицо с фото: ', 'Face from: ') + bl.refs.join(', ')));
        var grid = el('dl', 'reel-char__grid');
        bl.fields.forEach(function (f) {
          if (f === 'name' || f === 'role') return;
          grid.appendChild(el('dt', null, bl.labels[f]));
          var dd = el('dd');
          dd.appendChild(editable('span', 'reel-edit', c[f], 'characters.' + i + '.' + f));
          grid.appendChild(dd);
        });
        card.appendChild(grid);
        var det = el('details', 'reel-char__sheet');
        det.appendChild(el('summary', null, bl.sheet_label));
        det.appendChild(editable('div', 'reel-edit reel-mono', c.sheet_prompt, 'characters.' + i + '.sheet_prompt'));
        card.appendChild(det);
        wrap.appendChild(card);
      });
      return wrap;
    }

    function renderScript(bl) {
      var card = el('div', 'reel-card');
      if (bl.title) card.appendChild(editable('div', 'reel-card__title', bl.title, 'script.title'));
      var lab = bl.labels || {};
      function row(key, label) {
        var r = el('div', 'reel-row');
        r.appendChild(el('div', 'reel-row__label', label));
        r.appendChild(editable('div', 'reel-edit', bl[key], 'script.' + key));
        card.appendChild(r);
      }
      row('logline', lab.logline);
      row('hook', lab.hook);
      var r = el('div', 'reel-row');
      r.appendChild(el('div', 'reel-row__label', lab.beats));
      var ol = el('ol', 'reel-beats');
      (bl.beats || []).forEach(function (b, i) { var li = el('li'); li.appendChild(editable('span', 'reel-edit', b, 'script.beats.' + i)); ol.appendChild(li); });
      r.appendChild(ol);
      card.appendChild(r);
      row('ending', lab.ending);
      row('mood', lab.mood);
      return card;
    }

    function cameraSelect(bl, f) {
      var sel = el('select', 'reel-cam');
      var none = el('option', null, bl.labels.none); none.value = ''; sel.appendChild(none);
      var groups = {};
      (bl.cameras || []).forEach(function (m) {
        if (!groups[m.group]) { groups[m.group] = el('optgroup'); groups[m.group].label = m.group; sel.appendChild(groups[m.group]); }
        var o = el('option', null, m.title); o.value = m.id; groups[m.group].appendChild(o);
      });
      sel.value = f.camera || '';
      sel.addEventListener('change', function () { reelEdit('frames.' + (f.n - 1) + '.camera', sel.value); });
      return sel;
    }

    /** Раскадровка: кадр = время, план, действие, камера, промпт; «Переписать кадр» — своими словами. */
    function renderStoryboard(bl) {
      var list = el('div', 'reel-board');
      bl.frames.forEach(function (f) {
        var card = el('div', 'reel-frame');
        var top = el('div', 'reel-frame__top');
        top.appendChild(el('span', 'aich-variant__n', String(f.n)));
        top.appendChild(el('b', null, f.role || ''));
        top.appendChild(el('span', 'reel-frame__time', f.start + '–' + f.end + L(' с', ' s') + (f.shot ? ' · ' + f.shot : '')));
        card.appendChild(top);
        card.appendChild(editable('div', 'reel-edit', f.action, 'frames.' + (f.n - 1) + '.action'));
        var cam = el('label', 'reel-frame__cam');
        cam.appendChild(el('span', null, bl.labels.camera));
        cam.appendChild(cameraSelect(bl, f));
        card.appendChild(cam);
        var det = el('details', 'reel-frame__prompt');
        det.appendChild(el('summary', null, bl.labels.prompt));
        det.appendChild(editable('div', 'reel-edit reel-mono', f.prompt, 'frames.' + (f.n - 1) + '.prompt'));
        card.appendChild(det);
        var redo = el('div', 'reel-frame__redo');
        var inp = el('input', 'reel-frame__input');
        inp.placeholder = bl.labels.redo_ph;
        var b = el('button', 'aich-opt', bl.labels.redo);
        b.type = 'button';
        function send() { post({ action: { type: 'reel_frame', value: { n: f.n, text: inp.value.trim() } } }, true); }
        b.addEventListener('click', send);
        inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); send(); } });
        redo.appendChild(inp);
        redo.appendChild(b);
        card.appendChild(redo);
        list.appendChild(card);
      });
      return list;
    }

    /** Общий промпт: правится на месте, модель — пилюлями. «Сгенерировать» — обычная кнопка запуска. */
    function renderFinal(bl) {
      var box = el('div', 'aich-prompt reel-final');
      box.appendChild(el('div', 'aich-prompt__label', bl.labels.prompt + ' · ' + bl.seconds + L(' с · ', ' s · ') + bl.aspect));
      var txt = el('textarea', 'aich-prompt__text aich-prompt__area reel-mono');
      txt.value = bl.prompt || '';
      txt.rows = 6;
      txt.spellcheck = false;
      txt.addEventListener('input', function () {
        form.prompt = txt.value.trim();
        opts.onFillForm && opts.onFillForm({ model: form.model, prompt: form.prompt, params: form.params, ready: true, files: form.files });
      });
      txt.addEventListener('blur', function () { if (txt.value.trim() !== (bl.prompt || '').trim()) reelEdit('final', txt.value.trim()); });
      box.appendChild(txt);
      box.appendChild(promptExpand(txt));
      box.appendChild(el('div', 'aich-prompt__hint', bl.labels.hint));
      var m = el('div', 'aich-param');
      m.appendChild(el('div', 'aich-param__label', bl.labels.model));
      var pills = el('div', 'aich-param__opts');
      bl.models.forEach(function (o) {
        var p = el('button', 'aich-opt' + (o.selected ? ' is-on' : ''), o.title + (o.price ? ' · ' + o.price : ''));
        p.type = 'button';
        p.addEventListener('click', function () { if (!o.selected) reelEdit('model', o.id); });
        pills.appendChild(p);
      });
      m.appendChild(pills);
      box.appendChild(m);
      if (bl.files && bl.files.length) box.appendChild(el('div', 'aich-summary__files', bl.labels.files + ': ' + bl.files.join(' · ')));
      return box;
    }

    /* ------------------------------------------- режим «Раскадровка» (storyboard.py) */
    function sbEdit(path, value) { post({ action: { type: 'sb_edit', value: { path: path, value: value } } }, true); }

    function sbPills(group, pick) {
      var row = el('div', 'aich-param');
      row.appendChild(el('div', 'aich-param__label', group.label));
      var box = el('div', 'aich-param__opts');
      group.options.forEach(function (o) {
        var p = el('button', 'aich-opt' + (String(o.id) === String(group.selected) ? ' is-on' : ''), o.label);
        p.type = 'button';
        p.addEventListener('click', function () {
          if (String(o.id) === String(group.selected)) return;
          if (pick) pick(o.id); else sbEdit('set.' + group.key, o.id);
        });
        box.appendChild(p);
      });
      row.appendChild(box);
      return row;
    }

    /** Как ляжет лист: сетка колонки × ряды с номерами кадров. */
    function sbSheetMap(sheet, n) {
      var box = el('div', 'sb-map');
      var g = el('div', 'sb-map__grid');
      g.style.gridTemplateColumns = 'repeat(' + sheet.cols + ', 1fr)';
      for (var i = 0; i < sheet.cols * sheet.rows; i++) g.appendChild(el('i', i < n ? '' : 'is-empty', i < n ? String(i + 1) : ''));
      box.appendChild(g);
      box.appendChild(el('span', 'sb-map__cap', L('Лист ', 'Sheet ') + sheet.cols + ' × ' + sheet.rows + (sheet.aspect ? ' · ' + sheet.aspect : '')));
      return box;
    }

    /** Список кадров: номер, время, подпись, описание, план, камера. Всё правится на месте. */
    function renderSbFrames(bl) {
      var lab = bl.labels;
      var wrap = el('div', 'sb');
      var setup = bl.step === 'setup';
      if (setup && bl.summary) wrap.appendChild(el('div', 'sb-summary', bl.summary));
      var list = el('ol', 'sb-list');
      function sbIcon(name) {
        var paths = {
          up: 'M6 14l6-6 6 6',
          down: 'M6 10l6 6 6-6',
          del: 'M6 7h12M9 7V5h6v2M8 7l1 12h6l1-12',
          add: 'M12 6v12M6 12h12'
        };
        var b = el('button', 'sb-ico sb-ico--' + name);
        b.type = 'button';
        b.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="' + paths[name] + '"></path></svg>';
        return b;
      }
      if (!setup) bl.frames.forEach(function (f) {
        var i = f.n - 1;
        var last = i === bl.frames.length - 1;
        var li = el('li', 'sb-frame');
        var top = el('div', 'sb-frame__top');
        top.appendChild(el('span', 'sb-num', (f.n < 10 ? '0' : '') + f.n));
        top.appendChild(el('span', 'sb-time', f.time));
        top.appendChild(editable('span', 'reel-edit sb-frame__title', f.title, 'frames.' + i + '.title', sbEdit));
        var cam = el('label', 'sb-meta sb-meta--cam');
        var sel = el('select', 'reel-cam');
        var none = el('option', null, lab.none); none.value = ''; sel.appendChild(none);
        var groups = {};
        (bl.cameras || []).forEach(function (m) {
          if (!groups[m.group]) { groups[m.group] = el('optgroup'); groups[m.group].label = m.group; sel.appendChild(groups[m.group]); }
          var o = el('option', null, m.title); o.value = m.id; groups[m.group].appendChild(o);
        });
        sel.value = f.camera || '';
        sel.setAttribute('aria-label', lab.camera);
        sel.addEventListener('change', function () { sbEdit('frames.' + i + '.camera', sel.value); });
        cam.appendChild(sel);
        top.appendChild(cam);
        var tools = el('div', 'sb-tools');
        var up = sbIcon('up');
        up.title = L('Выше', 'Move up');
        up.setAttribute('aria-label', up.title);
        up.disabled = i === 0;
        up.addEventListener('click', function () { if (i > 0) sbEdit('frames.move.' + i + '.up'); });
        var down = sbIcon('down');
        down.title = L('Ниже', 'Move down');
        down.setAttribute('aria-label', down.title);
        down.disabled = last;
        down.addEventListener('click', function () { if (!last) sbEdit('frames.move.' + i + '.down'); });
        tools.appendChild(up);
        tools.appendChild(down);
        if (bl.can_del) {
          var del = sbIcon('del');
          del.title = lab.del;
          del.setAttribute('aria-label', lab.del + ' ' + f.n);
          del.addEventListener('click', function () { sbEdit('frames.del.' + i); });
          tools.appendChild(del);
        }
        top.appendChild(tools);
        li.appendChild(top);
        var ta = el('textarea', 'aich-prompt__area sb-frame__area');
        ta.value = f.text || '';
        ta.rows = 4;
        ta.spellcheck = false;
        var was = ta.value;
        ta.addEventListener('blur', function () {
          var now = ta.value.trim();
          if (now && now !== was.trim()) { was = now; sbEdit('frames.' + i + '.text', now); }
        });
        li.appendChild(ta);
        li.appendChild(promptExpand(ta));
        list.appendChild(li);
      });
      if (!setup && bl.frames.length) wrap.appendChild(list);
      if (bl.can_add) {
        var add = sbIcon('add');
        add.classList.add('sb-add');
        add.title = lab.add;
        add.setAttribute('aria-label', lab.add);
        add.addEventListener('click', function () { sbEdit('frames.add.' + bl.frames.length); });
        wrap.appendChild(add);
      }
      var set = el('div', 'sb-settings');
      (bl.settings || []).forEach(function (g) { set.appendChild(sbPills(g)); });
      if (bl.models && bl.models.length) {
        set.appendChild(sbPills({ key: 'model', label: lab.model, selected: bl.model,
          options: bl.models.map(function (m) { return { id: m.id, label: m.title + (m.price ? ' · ' + m.price : '') }; }) },
          function (id) { sbEdit('model', id); }));
      }
      var foot = el('div', 'sb-foot');
      if (bl.sheet) foot.appendChild(sbSheetMap(bl.sheet, bl.count || bl.frames.length));
      if (bl.cost) foot.appendChild(el('div', 'sb-cost', bl.cost));
      if (bl.files && bl.files.length) foot.appendChild(el('div', 'aich-summary__files', lab.files + ': ' + bl.files.join(' · ')));
      if (foot.childNodes.length) set.appendChild(foot);
      if (set.childNodes.length) wrap.appendChild(set);
      return wrap;
    }

    /** Флоу помощника: артефакты сессии по этапам. Живут только в этом чате — пометка внизу. */
    function safeUrl(u) { u = String(u || ''); return /^(https?:\/\/|\/(?!\/))/.test(u) ? u : ''; }
    function renderPipeArts(bl) {
      var box = el('div', 'pipe-arts');
      box.appendChild(el('div', 'pipe-arts__head', bl.title || ''));
      var list = el('div', 'pipe-arts__list');
      (bl.groups || []).forEach(function (g) {
        var row = el('div', 'pipe-arts__stage' + ((g.items && g.items.length) ? '' : ' is-empty'));
        row.appendChild(el('div', 'pipe-arts__name', g.title));
        var items = el('div', 'pipe-arts__items');
        if (!g.items || !g.items.length) items.appendChild(el('span', 'pipe-arts__none', '—'));
        (g.items || []).forEach(function (it) {
          var a = el('span', 'pipe-art');
          var url = safeUrl(it.url);
          if (url && it.kind === 'image') { var im = el('img'); im.src = url; im.alt = ''; im.loading = 'lazy'; a.appendChild(im); }
          else a.appendChild(el('span', 'pipe-art__ic', PIPE_TYPE_ICON[it.type] || '•'));
          var t = el('span', 'pipe-art__t', it.title || '');
          if (it.sub) t.appendChild(el('small', null, it.sub));
          a.appendChild(t);
          if (url) { var lnk = el('a', 'pipe-art__open', '↗'); lnk.href = url; lnk.target = '_blank'; lnk.rel = 'noopener'; lnk.title = L('Открыть', 'Open'); a.appendChild(lnk); }
          items.appendChild(a);
        });
        row.appendChild(items);
        list.appendChild(row);
      });
      box.appendChild(list);
      if (bl.note) box.appendChild(el('div', 'pipe-note', '⏳ ' + bl.note));
      return box;
    }
    function renderPipeJson(bl) {
      var box = el('div', 'pipe-json');
      var head = el('div', 'pipe-json__head');
      head.appendChild(el('span', null, bl.title || 'JSON'));
      var copy = el('button', 'aich-opt', L('Копировать', 'Copy'));
      copy.type = 'button';
      copy.addEventListener('click', function () {
        try { navigator.clipboard.writeText(bl.json || ''); copy.textContent = L('Скопировано', 'Copied'); } catch (e) {}
      });
      head.appendChild(copy);
      box.appendChild(head);
      box.appendChild(el('pre', 'pipe-json__code', bl.json || ''));
      return box;
    }
    function renderPipeMethod(bl) {
      var box = el('div', 'pipe-method');
      (bl.steps || []).forEach(function (st, i) {
        if (i) box.appendChild(el('span', 'pipe-method__arrow', '→'));
        var s = el('div', 'pipe-method__step');
        s.appendChild(el('b', null, st.t));
        s.appendChild(el('span', null, st.s));
        box.appendChild(s);
      });
      return box;
    }

    function fill(row, data) {
      if (data.lang) lang = data.lang;
      row.textContent = '';
      var av = el('div', 'aich-av');
      if (opts.avatarHTML) av.innerHTML = opts.avatarHTML; else av.className = 'aich-avatar';
      row.appendChild(av);
      var col = el('div', 'aich-col');
      var said = String(data.text || data.reply || '').trim();
      var hasBlocks = data.blocks && data.blocks.length;
      var hasChips = data.chips && data.chips.length;
      if (said) col.appendChild(el('div', 'aich-bubble', said));
      else if (!hasBlocks && !hasChips) return row;
      var chips = (data.chips || []).slice();
      var summary = null;
      (data.blocks || []).forEach(function (b) { if (b && b.type === 'summary') summary = b; });
      if (summary && summary.model_id && summary.prompt && !chips.some(function (c) { return c && c.action === 'generate'; })) {
        chips.unshift({ label: L('Сгенерировать', 'Generate'), action: 'generate', value: summary.model_id, primary: true });
      }
      if (summary && summary.allow_file && !chips.some(function (c) { return c && c.action === 'attach'; })) {
        chips.push({ label: L('Прикрепить файл', 'Attach a file'), action: 'attach' });
      }
      (data.blocks || []).forEach(function (bl) {
        if (bl.type === 'models') col.appendChild(renderModels(bl));
        else if (bl.type === 'prompt') col.appendChild(renderPrompt(bl));
        else if (bl.type === 'mode_text') col.appendChild(renderModeText(bl));
        else if (bl.type === 'params') col.appendChild(renderParams(bl));
        else if (bl.type === 'summary') col.appendChild(renderSummary(bl));
        else if (bl.type === 'files') col.appendChild(renderFiles(bl));
        else if (bl.type === 'brief') col.appendChild(renderBrief(bl));
        else if (bl.type === 'variants') col.appendChild(renderVariants(bl));
        else if (bl.type === 'camera') col.appendChild(renderCamera(bl));
        else if (bl.type === 'reel_steps') col.appendChild(renderSteps(bl));
        else if (bl.type === 'choice') col.appendChild(renderChoice(bl));
        else if (bl.type === 'reel_character') col.appendChild(renderCharacter(bl));
        else if (bl.type === 'reel_script') col.appendChild(renderScript(bl));
        else if (bl.type === 'reel_storyboard') col.appendChild(renderStoryboard(bl));
        else if (bl.type === 'reel_final') col.appendChild(renderFinal(bl));
        else if (bl.type === 'sb_frames') col.appendChild(renderSbFrames(bl));
        else if (bl.type === 'pipe_arts') col.appendChild(renderPipeArts(bl));
        else if (bl.type === 'pipe_json') col.appendChild(renderPipeJson(bl));
        else if (bl.type === 'pipe_method') col.appendChild(renderPipeMethod(bl));
      });
      if (chips.length) col.appendChild(renderChips(chips));
      row.appendChild(col);
      var setup = (data.blocks || []).some(function (b) {
        return b.type === 'params' || b.type === 'prompt' || b.type === 'brief' || b.type === 'camera' || b.type === 'summary' || b.type === 'files' || (REEL_BLOCKS[b.type] && b.type !== 'reel_steps') || b.type === 'sb_frames';
      });
      if (setup) setupNode = row;
      return row;
    }

    /** DOM-узел сообщения ассистента. Новый узел гасит кнопки у предыдущих (чтобы не нажимали устаревшее). */
    function render(data) {
      allNodes.forEach(function (n) { n.classList.add('is-old'); });
      var row = fill(el('div', 'aich-row'), data);
      allNodes.push(row);
      return row;
    }

    function post(body, inPlace) {
      if (busy) return Promise.resolve(null);
      busy = true;
      body.context = (opts.getContext && opts.getContext()) || {};
      if (!inPlace && opts.onTyping) opts.onTyping(true);
      return opts.api(url, { method: 'POST', body: JSON.stringify(body) })
        .then(function (r) {
          busy = false;
          if (opts.onTyping) opts.onTyping(false);
          var data = r && r.data;
          if (!r || !r.res || !r.res.ok || !data) {
            var status = r && r.res ? r.res.status : 0;
            opts.onBot({ text: status === 429 ? L('Слишком много сообщений подряд — подождите минуту.', 'Too many messages — wait a minute.')
              : L('Не удалось связаться с помощником. Попробуйте ещё раз.', 'Could not reach the assistant. Try again.'),
              chips: [{ label: L('Повторить', 'Retry'), action: 'retry' }] });
            return null;
          }
          var nModels = (data.models && data.models.length) || 0;
          (data.blocks || []).forEach(function (b) { if (b && b.type === 'models' && b.items) nModels = Math.max(nModels, b.items.length); });
          M('assist_reply', { intent: data.intent || 'unknown', degraded: !!data.degraded, gate: data.gate || '', models: nModels });
          if (nModels) M('models_shown', { n: nModels, kind: data.kind || '' });
          if (data.gate === 'login' || data.gate === 'topup') M('gate', { type: data.gate, src: 'assistant' });
          if ('pipe_expect' in data) pipeExpect = data.pipe_expect || null;
          if (root.AishModelLock && AishModelLock.handle(data, opts.onTextModel)) return data;
          if (data.silent) return data;
          if (inPlace && setupNode && setupNode.parentNode) fill(setupNode, data);   // параметры — на месте
          else opts.onBot(data);
          // помощник сам делает безопасное обратимое действие: тема, панель справа, новый чат
          if (data.ui_do && data.ui_do.action && opts.onUiAction) {
            try { opts.onUiAction(data.ui_do.action, data.ui_do.value); } catch (_) {}
          }
          if (data.generate_model || data.generate_prompt) {
            form = { model: data.generate_model, prompt: data.generate_prompt || '', params: data.generate_params || {},
                     files: data.generate_files || [], series: data.generate_series || null };
            opts.onFillForm && opts.onFillForm({ model: form.model, prompt: form.prompt, params: form.params, ready: !!data.ready, files: form.files,
              quiet: !!data.quiet_reply, attach_urls: data.attach_urls || [], keepAssistant: !!data.keep_assistant, kind: data.generate_kind || '' });
          }
          return data;
        })
        .catch(function () {
          busy = false;
          if (opts.onTyping) opts.onTyping(false);
          opts.onBot({ text: L('Нет связи. Проверьте интернет и повторите.', 'No connection. Check the internet and retry.'),
            chips: [{ label: L('Повторить', 'Retry'), action: 'retry' }] });
          return null;
        });
    }

    function rememberSummary(text) {
      summaryDraft = String(text || '');
      form.prompt = summaryDraft.trim();
      if (opts.onFillForm) opts.onFillForm({ model: form.model, prompt: form.prompt, params: form.params, ready: true, files: form.files || [] });
      clearTimeout(summaryTimer);
      summaryTimer = setTimeout(flushSummary, 400);
    }
    function flushSummary() {
      clearTimeout(summaryTimer);
      summaryTimer = 0;
      if (summaryDraft == null) return summarySave || Promise.resolve();
      var text = String(summaryDraft).trim();
      summaryDraft = null;
      if (!text || text === summarySaved) return summarySave || Promise.resolve();
      summarySaved = text;
      var body = { action: { type: 'edit_prompt', value: { text: text, quiet: true } } };
      body.context = (opts.getContext && opts.getContext()) || {};
      summarySave = opts.api(url, { method: 'POST', body: JSON.stringify(body) }).catch(function () {}).then(function () { summarySave = null; });
      return summarySave;
    }
    function onChip(c, livePrompt) {
      if (!c || !c.action || busy) return;
      if (c.action === 'intent_other') {
        var box = root.document && root.document.getElementById('prompt');
        if (box) box.focus();
        return;
      }
      if (summaryDraft != null || summarySave) {
        var again = c;
        var typed = livePrompt;
        flushSummary().then(function () { onChip(again, typed); });
        return;
      }
      if (c.action === 'generate') {
        opts.onUser && opts.onUser(c.label);
        var prompt = (livePrompt && String(livePrompt).trim()) || form.prompt;
        form.prompt = prompt;
        opts.onGenerate && opts.onGenerate({ model: form.model || c.value, prompt: prompt, params: form.params, files: form.files || [] });
        return;
      }
      // «Раскадровка» по кадрам: серия картинок — приложение запускает их подряд, по одной
      if (c.action === 'generate_series') {
        if (!form.series || !form.series.length) return;
        opts.onUser && opts.onUser(c.label);
        if (opts.onGenerateSeries) opts.onGenerateSeries({ model: form.model || c.value, params: form.params, files: form.files || [], items: form.series });
        return;
      }
      if (c.action === 'retry' && lastBody) { post(lastBody); return; }
      if (c.action === 'open_vitrina') {
        if (opts.onUiAction) opts.onUiAction('open_vitrina', c.value);
        else if (c.value) location.href = c.value;
        return;
      }
      if (c.action === 'pipe_result') {
        lastBody = { action: { type: 'pipe_result', value: c.value } };
        post(lastBody);
        return;
      }
      if ((c.action === 'look_skip' || c.action === 'look_next') && opts.onUiAction) opts.onUiAction(c.action);
      if (c.action === 'pick_model' && root.AishModelLock) {
        var mid = String(c.value || '');
        var models = (root.app && root.app.MODELS) || [];
        var picked = models.find(function (x) { return x.model_key === mid || x.slug === mid; });
        AishModelLock.set({ id: mid, kind: (picked && picked.type) || '', title: (picked && picked.name) || c.label || mid });
      }
      if (SERVER[c.action]) {
        M('assist_action', { action: c.action, value: short(c.value) });
        if (c.action === 'pick_model') M('model_pick', { model: short(c.value), src: 'assistant' });
        if (c.action === 'tree_hint') M('tree_hint', { story: short(c.value && c.value.s), step: c.value && c.value.t, i: c.value && c.value.i });
        opts.onUser && opts.onUser(c.label);
        var action = { type: c.action, value: c.value };
        if (livePrompt && String(livePrompt).trim()) action.prompt = String(livePrompt).trim().slice(0, 8000);
        lastBody = { action: action };
        post(lastBody);
        return;
      }
      opts.onUiAction && opts.onUiAction(c.action, c.value);
    }

    function softReset() {
      clearTimeout(summaryTimer);
      summaryTimer = 0;
      summaryDraft = null;
      summarySaved = '';
      summarySave = null;
      setupNode = null;
      pipeExpect = null;
      form = { model: null, prompt: '', params: {} };
      allNodes = [];
      lastBody = null;
      busy = false;
    }

    var ctl = {
      send: function (text) {
        text = String(text || '').trim().slice(0, 2000);
        if (!text || busy) return Promise.resolve(null);
        opts.onUser && opts.onUser(text);
        lastBody = { message: text };
        return post(lastBody);
      },
      /** Ошибка джобы уже в getContext().last_error — помощник предложит другие модели / что делать. */
      explainJob: function () {
        if (busy) return Promise.resolve(null);
        lastBody = { message: '' };
        return post(lastBody);
      },
      chip: onChip,
      mcpConnected: function (id, name) {
        if (busy) return Promise.resolve(null);
        lastBody = { action: { type: 'mcp_connected', value: { id: id || '', name: name || '' } } };
        return post(lastBody);
      },
      mcpFailed: function () {
        if (busy) return Promise.resolve(null);
        lastBody = { action: { type: 'mcp_failed' } };
        return post(lastBody);
      },
      /** Вернулись после входа или пополнения: сервер заново проверит вход → баланс и покажет то же место. */
      resume: function () { if (busy) return Promise.resolve(null); lastBody = { action: { type: 'resume' } }; return post(lastBody); },
      syncFiles: function () {
        if (busy || !document.querySelector('.aich-summary, .aich-files')) return Promise.resolve(null);
        lastBody = { action: { type: 'files_sync' } };
        return post(lastBody, true);
      },
      /** Новый диалог: сбросить cookie/память на сервере и спросить тип генерации. */
      restart: function () {
        softReset();
        var resetUrl = (opts.url || '/api/assistant/chat').replace(/\/?$/, '') + '/reset';
        return opts.api(resetUrl, { method: 'POST', body: '{}' }).catch(function () { return null; }).then(function () {
          lastBody = { action: { type: 'restart' } };
          return post(lastBody);
        });
      },
      softReset: softReset,
      /** Открыли сохранённый чат: вернуть модель и промпт, чтобы «Сгенерировать» сработало. */
      revive: function (setup) {
        if (!setup || !setup.model) return;
        form = { model: setup.model, prompt: String(setup.prompt || ''), params: setup.params || {}, files: [], series: null };
        summarySaved = form.prompt.trim();
        if (opts.onFillForm) opts.onFillForm({ model: form.model, prompt: form.prompt, params: form.params, ready: true, files: [] });
      },
      /** Генерация завершилась: если флоу ждёт результат — сообщить серверу, он сохранит артефакт и предложит шаг дальше.
       *  payload: {kind: image|video|audio|text, url, urls?, series?, model, work_id, reply?} */
      result: function (payload, tries) {
        if (!pipeExpect || !payload) return Promise.resolve(null);
        tries = tries || 0;
        if (busy) {
          if (tries > 20) return Promise.resolve(null);
          return new Promise(function (r) { setTimeout(r, 1500); }).then(function () { return ctl.result(payload, tries + 1); });
        }
        lastBody = { action: { type: 'pipe_result', value: payload } };
        return post(lastBody, false);
      },
      pipeExpect: function () { return pipeExpect; },
      /** Событие под результатом для дерева подсказок: like · dislike · regen · error · topup_needed · download.
       *  Помощник ответит коротко и предложит следующий шаг истории (если человек в истории); иначе ответ silent. */
      /** Команда в чате с Claude/GPT: не отвечать текстом, а перейти к видео/картинке/музыке. */
      handoff: function (value) {
        if (busy || !value) return Promise.resolve(null);
        lastBody = { action: { type: 'model_switch', value: value } };
        return post(lastBody);
      },
      /** Ответ текстовой модели остаётся в памяти разговора — следующий «по этому» его найдёт. */
      noteText: function (value) {
        if (!value || !value.text) return Promise.resolve(null);
        return post({ action: { type: 'text_note', value: value } }, false);
      },
      /** Opus посмотрел фото — разобрать ответ в сетку действий. */
      lookDone: function (text) {
        lastBody = { action: { type: 'look_done', value: { text: String(text || '') } } };
        return post(lastBody);
      },
      mediaAdd: function (payload) {
        if (!payload) return Promise.resolve(null);
        return post({ action: { type: 'media_add', value: payload } }, false);
      },
      treeEvent: function (name) {
        if (busy || !name) return Promise.resolve(null);
        return post({ action: { type: 'tree_event', value: { name: String(name) } } }, false);
      },
      render: render,
      isBusy: function () { return busy; },
      form: function () { return form; }
    };
    return ctl;
  }

  /* ------------------------------------------------------------- standalone */
  function mount(opts) {
    var thread = opts.root;
    function scroll() { var sc = thread.closest('[data-chat-scroll]') || thread; sc.scrollTop = sc.scrollHeight; }
    var c = controller(Object.assign({}, opts, {
      onUser: function (text) {
        var row = el('div', 'aich-row aich-row--user');
        row.appendChild(el('div', 'aich-bubble aich-bubble--user', text));
        thread.appendChild(row); scroll();
      },
      onBot: function (data) { thread.appendChild(c.render(data)); scroll(); },
      onTyping: function (on) {
        var t = thread.querySelector('.aich-typing');
        if (on && !t) {
          t = el('div', 'aich-row aich-typing');
          t.appendChild(el('div', 'aich-avatar'));
          var b = el('div', 'aich-bubble');
          b.innerHTML = '<span class="aich-dots"><i></i><i></i><i></i></span>';
          t.appendChild(b);
          thread.appendChild(t); scroll();
        } else if (!on && t) t.remove();
      }
    }));
    return c;
  }

  root.AssistantUI = { mount: mount, controller: controller };
})(typeof window !== 'undefined' ? window : this);
