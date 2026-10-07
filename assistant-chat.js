/* Клиент ассистента для студии ({AI}-шница). Без зависимостей.
 *
 * Использование (app.html, вместо прямого fetch('/api/chat')):
 *   const eggy = AssistantChat({
 *     api,                                  // существующий helper api(url, opts) → {res, data} (с CSRF)
 *     getContext: () => ({ selected_model_id, has_image, last_error, last_http_status, job_status, job_age_sec, draft }),
 *     onReply: (data) => { показать data.reply (markdown) и кнопки data.chips },
 *     onFillForm: ({model, prompt, params, ready}) => { выбрать модель, вставить промпт, НЕ запускать },
 *     onUiAction: (action, value) => { open_models | open_topup | open_vitrina | login | attach | retry | wait | support | generate | edit_prompt },
 *   });
 *   eggy.send(text);                 // сообщение пользователя
 *   eggy.chip(chip);                 // клик по кнопке из data.chips
 */
(function (root) {
  // Действия, которые обрабатывает сервер (без LLM, кроме pick_model)
  var SERVER_ACTIONS = {
    pick_model: 1, more: 1, choose_type: 1, use_mine: 1, param: 1, send: 1,
    similar: 1, cheaper: 1, faster: 1, no_photo_model: 1, rephrase: 1
  };

  function AssistantChat(opts) {
    var url = opts.url || '/api/assistant/chat';
    var busy = false;

    function post(body) {
      if (busy) return Promise.resolve(null);   // защита от двойного клика: один запрос за раз
      busy = true;
      body.context = (opts.getContext && opts.getContext()) || {};
      return opts.api(url, { method: 'POST', body: JSON.stringify(body) })
        .then(function (r) {
          busy = false;
          var data = r && r.data;
          if (!r || !r.res || !r.res.ok || !data) {
            var status = r && r.res ? r.res.status : 0;
            opts.onReply({
              reply: status === 429 ? 'Слишком много сообщений подряд — подождите минуту.' : 'Не удалось связаться с помощником. Попробуйте ещё раз.',
              chips: [{ label: 'Повторить', action: 'retry' }], intent: 'transport_error'
            });
            return null;
          }
          opts.onReply(data);
          if (data.generate_model || data.generate_prompt) {
            opts.onFillForm && opts.onFillForm({
              model: data.generate_model, prompt: data.generate_prompt,
              params: data.generate_params || {}, ready: !!data.ready
            });
          }
          return data;
        })
        .catch(function () {
          busy = false;
          opts.onReply({ reply: 'Нет связи. Проверьте интернет и повторите.', chips: [{ label: 'Повторить', action: 'retry' }], intent: 'transport_error' });
          return null;
        });
    }

    return {
      send: function (text) { return post({ message: String(text || '').slice(0, 2000) }); },
      chip: function (c) {
        if (!c || !c.action) return Promise.resolve(null);
        if (SERVER_ACTIONS[c.action]) return post({ action: { type: c.action, value: c.value } });
        // generate: только по клику пользователя → обычный POST /api/generate (биллинг, модерация там)
        opts.onUiAction && opts.onUiAction(c.action, c.value);
        return Promise.resolve(null);
      },
      isBusy: function () { return busy; }
    };
  }

  root.AssistantChat = AssistantChat;
})(typeof window !== 'undefined' ? window : this);
