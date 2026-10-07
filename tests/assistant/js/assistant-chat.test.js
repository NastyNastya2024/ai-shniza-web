// node tests/js/assistant-chat.test.js
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const ctx = {};
new Function('window', fs.readFileSync(process.env.ASSISTANT_CHAT_JS || path.join(__dirname, '../../integration/assistant-chat.js'), 'utf8'))(ctx);

(async () => {
  const sent = [], replies = [], fills = [], ui = [];
  let next = { res: { ok: true, status: 200 }, data: { reply: 'ok', chips: [], generate_model: 'veo-3-1', generate_prompt: 'p', ready: true } };
  const eggy = ctx.AssistantChat({
    api: (url, o) => { sent.push({ url, body: JSON.parse(o.body) }); return Promise.resolve(next); },
    getContext: () => ({ has_image: false }),
    onReply: (d) => replies.push(d), onFillForm: (f) => fills.push(f), onUiAction: (a, v) => ui.push([a, v]),
  });
  await eggy.send('кот');
  assert.equal(sent[0].url, '/api/assistant/chat');
  assert.deepEqual(sent[0].body, { message: 'кот', context: { has_image: false } });
  assert.deepEqual(fills[0], { model: 'veo-3-1', prompt: 'p', params: {}, ready: true });

  await eggy.chip({ action: 'pick_model', value: 'kling' });
  assert.deepEqual(sent[1].body.action, { type: 'pick_model', value: 'kling' });

  await eggy.chip({ action: 'generate', value: 'veo-3-1' });   // не уходит на сервер ассистента
  await eggy.chip({ action: 'open_topup' });
  assert.equal(sent.length, 2);
  assert.deepEqual(ui, [['generate', 'veo-3-1'], ['open_topup', undefined]]);

  next = { res: { ok: false, status: 429 }, data: { error: 'rate' } };
  await eggy.send('x');
  assert.match(replies.at(-1).reply, /подождите минуту/);

  // двойной клик: второй запрос не уходит, пока первый не завершён
  let release; next = new Promise((r) => { release = r; });
  const p1 = eggy.send('a'); const p2 = eggy.send('b');
  assert.equal(await p2, null);
  release({ res: { ok: true, status: 200 }, data: { reply: 'r', chips: [] } });
  await p1;
  assert.equal(sent.filter((s) => s.body.message === 'b').length, 0);
  console.log('assistant-chat.js: 6 checks passed');
})().catch((e) => { console.error(e); process.exit(1); });
