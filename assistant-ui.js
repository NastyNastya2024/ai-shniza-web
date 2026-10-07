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
  var SERVER = { pick_model: 1, more: 1, choose_type: 1, use_mine: 1, param: 1, refine: 1, improve: 1, send: 1,
    similar: 1, cheaper: 1, faster: 1, no_photo_model: 1, rephrase: 1, resume: 1,
    brief: 1, variants: 1, more_variants: 1, back_brief: 1, use_variant: 1 };
  var KIND_ICON = { image: '🖼', video: '🎬', music: '🎵', sfx: '🔊', edit: '✏️' };

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
    var setupNode = null;
    var lastBody = null;
    var allNodes = [];

    function L(ru, en) { return lang === 'en' ? en : ru; }

    function chipBtn(c) {
      var btn = el('button', 'aich-chip' + (c.primary ? ' aich-chip--primary' : ''), c.label);
      btn.type = 'button';
      if (c.action === 'choose_type' && KIND_ICON[c.value]) btn.textContent = KIND_ICON[c.value] + ' ' + c.label;
      btn.addEventListener('click', function () { onChip(c); });
      return btn;
    }

    /** Типы (видео/картинка/…) и примеры — отдельными рядами, если в ответе есть и то и другое. */
    function renderChips(list) {
      var types = [], examples = [], rest = [];
      (list || []).forEach(function (c) {
        if (c.action === 'choose_type') types.push(c);
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

    function renderModels(bl) {
      var grid = el('div', 'aich-models');
      bl.items.forEach(function (it) {
        var card = el('button', 'aich-model');
        card.type = 'button';
        var top = el('div', 'aich-model__top');
        top.appendChild(el('span', 'aich-model__title', it.title));
        if (it.badge) top.appendChild(el('span', 'aich-badge', it.badge));
        card.appendChild(top);
        card.appendChild(el('div', 'aich-model__why', it.why));
        card.appendChild(el('div', 'aich-model__price', it.estimate || it.price));
        card.appendChild(el('div', 'aich-model__sub', it.estimate ? (it.price + ' · ' + it.speed) : it.speed));
        var link = el('a', 'aich-model__link', L('Примеры на витрине →', 'Examples in showcase →'));
        link.href = it.vitrina_url || '#';
        link.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          if (opts.onUiAction) opts.onUiAction('open_vitrina', it.id);
          else if (it.vitrina_url) location.href = it.vitrina_url;
        });
        card.appendChild(link);
        card.addEventListener('click', function () { onChip({ label: it.title, action: 'pick_model', value: it.id }); });
        grid.appendChild(card);
      });
      return grid;
    }

    function renderPrompt(bl) {
      var box = el('div', 'aich-prompt');
      box.appendChild(el('div', 'aich-prompt__label', L('Промпт под ', 'Prompt for ') + bl.title));
      var txt = el('div', 'aich-prompt__text', bl.text);
      txt.contentEditable = 'true';
      txt.spellcheck = false;
      txt.addEventListener('input', function () {   // правка руками — сразу в форму, без сервера
        form.prompt = txt.textContent.trim();
        opts.onFillForm && opts.onFillForm({ model: form.model, prompt: form.prompt, params: form.params, ready: true });
      });
      box.appendChild(txt);
      if (bl.note) box.appendChild(el('div', 'aich-prompt__note', bl.note));
      box.appendChild(el('div', 'aich-prompt__hint', L('можно исправить прямо здесь', 'you can edit it right here')));
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

    /** Уточняющие вопросы: варианты ответов кнопками, «Не важно» по умолчанию. Клик — обновление на месте. */
    function renderBrief(bl) {
      var wrap = el('div', 'aich-params aich-brief');
      var open = bl.questions.filter(function (q) { return !q.options || !q.options.length; });
      if (open.length) {   // кто, где, что происходит, нюансы — отвечают своими словами
        var box0 = el('div', 'aich-open');
        var ul = el('ul', 'aich-open__list');
        open.forEach(function (q) { ul.appendChild(el('li', null, q.label)); });
        box0.appendChild(ul);
        box0.appendChild(el('div', 'aich-prompt__hint', L('ответьте одним сообщением в поле ниже', 'answer in one message below')));
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

    /** Варианты промпта: карточки, клик — выбрать вариант (дальше параметры и запуск). */
    function renderVariants(bl) {
      var list = el('div', 'aich-variants');
      bl.items.forEach(function (v, i) {
        var card = el('button', 'aich-variant');
        card.type = 'button';
        var top = el('div', 'aich-variant__top');
        top.appendChild(el('span', 'aich-variant__n', String(i + 1)));
        top.appendChild(el('span', 'aich-variant__title', v.title));
        card.appendChild(top);
        card.appendChild(el('div', 'aich-variant__text', v.text));
        card.appendChild(el('div', 'aich-variant__cta', L('Выбрать этот →', 'Use this →')));
        card.addEventListener('click', function () {
          onChip({ label: L('Вариант «', 'Option “') + v.title + L('»', '”'), action: 'use_variant', value: v.id });
        });
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
      return box;
    }

    function fill(row, data) {
      if (data.lang) lang = data.lang;
      row.textContent = '';
      var av = el('div', 'aich-av');
      if (opts.avatarHTML) av.innerHTML = opts.avatarHTML; else av.className = 'aich-avatar';
      row.appendChild(av);
      var col = el('div', 'aich-col');
      if (data.text || !(data.blocks && data.blocks.length)) col.appendChild(el('div', 'aich-bubble', data.text || data.reply || ''));
      (data.blocks || []).forEach(function (bl) {
        if (bl.type === 'models') col.appendChild(renderModels(bl));
        else if (bl.type === 'prompt') col.appendChild(renderPrompt(bl));
        else if (bl.type === 'params') col.appendChild(renderParams(bl));
        else if (bl.type === 'summary') col.appendChild(renderSummary(bl));
        else if (bl.type === 'brief') col.appendChild(renderBrief(bl));
        else if (bl.type === 'variants') col.appendChild(renderVariants(bl));
      });
      if (data.chips && data.chips.length) col.appendChild(renderChips(data.chips));
      row.appendChild(col);
      var setup = (data.blocks || []).some(function (b) { return b.type === 'params' || b.type === 'prompt' || b.type === 'brief'; });
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
          if (inPlace && setupNode && setupNode.parentNode) fill(setupNode, data);   // параметры — на месте
          else opts.onBot(data);
          if (data.generate_model || data.generate_prompt) {
            form = { model: data.generate_model, prompt: data.generate_prompt || '', params: data.generate_params || {} };
            opts.onFillForm && opts.onFillForm({ model: form.model, prompt: form.prompt, params: form.params, ready: !!data.ready });
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

    function onChip(c) {
      if (!c || !c.action || busy) return;
      if (c.action === 'generate') {
        opts.onUser && opts.onUser(c.label);
        opts.onGenerate && opts.onGenerate({ model: form.model || c.value, prompt: form.prompt, params: form.params });
        return;
      }
      if (c.action === 'retry' && lastBody) { post(lastBody); return; }
      if (c.action === 'open_vitrina') {
        if (opts.onUiAction) opts.onUiAction('open_vitrina', c.value);
        else if (c.value) location.href = c.value;
        return;
      }
      if (SERVER[c.action]) {
        opts.onUser && opts.onUser(c.label);
        lastBody = { action: { type: c.action, value: c.value } };
        post(lastBody);
        return;
      }
      opts.onUiAction && opts.onUiAction(c.action, c.value);
    }

    return {
      send: function (text) {
        text = String(text || '').trim().slice(0, 2000);
        if (!text || busy) return Promise.resolve(null);
        opts.onUser && opts.onUser(text);
        lastBody = { message: text };
        return post(lastBody);
      },
      chip: onChip,
      /** Вернулись после входа или пополнения: сервер заново проверит вход → баланс и покажет то же место. */
      resume: function () { if (busy) return Promise.resolve(null); lastBody = { action: { type: 'resume' } }; return post(lastBody); },
      render: render,
      isBusy: function () { return busy; },
      form: function () { return form; }
    };
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
