# Generate assistant: role and system prompt

Date: 2026-09-09  
Code: `CHAT_SYSTEM_PROMPT` + `_with_assistant_persona()` in `server.py`

--------------------------------------------------------------------------------
1. Why
--------------------------------------------------------------------------------

The Generate assistant is not a “bare” LLM — it is a product agent
**“Caring Navigator + Economic Advocate”**:

- helps pick a model for budget and task;
- refines the prompt for the specific model;
- suggests run parameters (video / text / image);
- keeps ethical boundaries (no violence, suicide, extremism, etc.).

The role is applied **regardless of backend model**
(OmniRoute, DeepSeek on Replicate, Claude/GPT, and other `assistants` group models).

--------------------------------------------------------------------------------
2. Where it is wired in code
--------------------------------------------------------------------------------

| Path | How the prompt is applied |
|------|---------------------------|
| `POST /api/chat` (UI: id=`assistant`, kind=`chat`) | `messages = [system: _build_chat_system_prompt(), ...history]` |
| Chat fallback → Replicate DeepSeek | same system+catalog concatenated into a single `prompt` |
| `POST /api/generate` for `group=assistants`, `kind∈{llm,chat}` | `_with_assistant_persona(user_prompt)` (= role + catalog) |
| Image / video / audio generate | **not** applied (media generation only) |

Env (chat):

- `OMNIROUTE_BASE_URL`, `OMNIROUTE_API_KEY`
- `OMNIROUTE_CHAT_MODEL` (default `auto/coding:free`)
- `CHAT_FALLBACK_REPLICATE_MODEL` (default `deepseek-ai/deepseek-v3.1`)

--------------------------------------------------------------------------------
3. /api/chat flow (as-is)
--------------------------------------------------------------------------------

```
Browser (generate.html)
   │  POST /api/chat  { messages: [...] }
   ▼
Flask api_chat()
   │  + system = CHAT_SYSTEM_PROMPT
   ▼
OmniRoute /v1/chat/completions
   preferred → auto/coding:free → auto/best-free → auto/chat
   │
   │  on 4xx/5xx / unavailability
   ▼
Replicate DeepSeek (prompt = system + history)
   │
   ▼
JSON { reply, model, channel: omniroute|replicate }
```

--------------------------------------------------------------------------------
4. Role content (summary)
--------------------------------------------------------------------------------

Full text — constant `CHAT_SYSTEM_PROMPT` + dynamic catalog via
`_build_chat_system_prompt()` in `server.py` (source of truth).

In short:

1. **Catalog only** — does not recommend models outside live `INTEGRATED_MODELS`
   (list + prices are injected into the system prompt on every request).
2. **Short replies** — recommendation ≤12 lines; `max_tokens≈420`,
   server `_compact_chat_reply` (~900 chars). Language = user’s language.
3. **Structure** — forbid a single blob paragraph and reasoning/CoT leaks (English meta).
4. **Missing data** — still immediately offer 1–2 nearest models by action and price;
   do not loop on clarifying questions.
5. **Ethics** — refuse dangerous topics; if the user is in distress — 8-800-2000-122 and
   https://www.iasp.info/suicidalthoughts/ , then a constructive task.
6. **Tone** — friend/mentor, no walls of text, no language switching.

Prices: `models_catalog/catalog.json` via `_integration_prices()`;
if a price is missing — relative labels only, no invented numbers.

--------------------------------------------------------------------------------
5. UI
--------------------------------------------------------------------------------

- Welcome in `generate.html` sets expectations: task, format, budget per generation.
- Choosing “Assistant (OmniRoute)” → `/api/chat`.
- Choosing another assistant (DeepSeek, Claude, …) → `/api/generate` + persona wrapper.

--------------------------------------------------------------------------------
6. Related docs
--------------------------------------------------------------------------------

- Channel overview: [ARCHITECTURE.md](./ARCHITECTURE.md) §4–5, §9
- Catalog + prices: [`../../neural-networks-catalog.md`](../../neural-networks-catalog.md)
- Generate sequence: [sequence.txt](./sequence.txt)
