/* «Выбранная модель главнее»: запоминает, что модель выбрал сам человек, и отправляет сообщение туда, куда надо.
 *
 *   AishModelLock.set(model)        — человек выбрал модель (панель «Модели», список у поля ввода, кнопка помощника «Взять …»)
 *   AishModelLock.clear()           — «Новый чат», выход, помощник ответил ui_do: unlock_model
 *   AishModelLock.ctx()             — поля для context запроса помощника: {model_locked, selected_model_id, selected_model_kind}
 *   AishModelLock.isText()          — выбрана текстовая модель
 *   AishModelLock.handle(data, sendText) — ответ помощника с route:text_model → отправить текст в выбранную текстовую модель
 *
 * model: {id, kind, title}. kind: text | image | video | music | sfx | edit | voice | 3d.
 * Состояние живёт в sessionStorage вкладки: обновление страницы не сбрасывает выбор, новая вкладка — начинает с нуля.
 */
(function (root) {
  'use strict';
  var KEY = 'aish-model-lock';
  var state = null;
  try { state = JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch (e) { state = null; }

  function save() { try { sessionStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }

  var api = {
    set: function (model) {
      if (!model || !model.id) return;
      state = { id: String(model.id), kind: String(model.kind || ''), title: String(model.title || model.id), at: Date.now() };
      save();
    },
    clear: function () { state = null; save(); },
    get: function () { return state; },
    isText: function () { return !!(state && state.kind === 'text'); },
    ctx: function () {
      if (!state) return { model_locked: false };
      return { model_locked: true, selected_model_id: state.id, selected_model_kind: state.kind };
    },
    /** true — ответ обработан здесь (текст ушёл в текстовую модель), рисовать ответ помощника не нужно. */
    handle: function (data, sendText) {
      if (!data) return false;
      if (data.ui_do && data.ui_do.action === 'unlock_model') api.clear();
      if (data.route && data.route.to === 'text_model' && typeof sendText === 'function') {
        sendText(String(data.route.text || ''), String(data.route.model_id || (state && state.id) || ''));
        return true;
      }
      return false;
    }
  };
  root.AishModelLock = api;
})(typeof window !== 'undefined' ? window : this);
