/**
 * Intent Router — определяет, что хочет пользователь, ДО применения любого шаблона промпта.
 *
 * Порядок работы:
 *   1. Пытаемся классифицировать запрос через LLM (быстрый дешёвый вызов, только JSON).
 *   2. Если LLM недоступна / таймаут / вернула мусор — классифицируем по ключевым словам.
 *   3. По результату принимаем решение: собрать промпт, задать уточняющий вопрос или честно отказать.
 *
 * Модуль НЕ зависит от конкретного провайдера LLM: функцию вызова модели передаёте вы (callLLM).
 */

import { ROUTER_SYSTEM_PROMPT } from "./routerPrompt";

// ---------- Типы ----------

export type IntentType = "image" | "video" | "text" | "mixed" | "unclear" | "out_of_scope";
export type TemplateType = "image" | "video" | "text";

export interface IntentResult {
  type: IntentType;
  confidence: number;
  summary: string;
  criticalMissing: string[];
  niceToHave: string[];
  clarifyQuestion: string | null;
  options: string[];
  /** откуда результат: от модели или от запасного разбора по ключевым словам */
  source: "llm" | "keywords";
}

export type RouterDecision =
  | { action: "build_prompt"; template: TemplateType; intent: IntentResult }
  | { action: "clarify"; message: string; options: string[]; intent: IntentResult }
  | { action: "out_of_scope"; message: string; intent: IntentResult };

/** Функция вызова модели: получает system и user, возвращает сырой текст ответа. */
export type CallLLM = (system: string, user: string) => Promise<string>;

export interface RouterOptions {
  callLLM?: CallLLM;
  /** таймаут вызова модели, мс */
  timeoutMs?: number;
  /** ниже этого порога — всегда уточняем */
  minConfidence?: number;
}

// ---------- Константы ----------

const DEFAULT_TIMEOUT_MS = 8000;
const DEFAULT_MIN_CONFIDENCE = 0.7;

const VALID_TYPES: IntentType[] = ["image", "video", "text", "mixed", "unclear", "out_of_scope"];

export const DEFAULT_CLARIFY = {
  question: "Уточните, пожалуйста, что именно нужно?",
  options: ["Тексты для постов", "Баннер или картинка", "Видео / reels", "Комплект для запуска", "Другое"],
};

const FALLBACK_NOTICE = "Редактор сейчас отвечает медленно, поэтому уточню вручную. ";

const OUT_OF_SCOPE_MESSAGE =
  "С этим я помочь не могу. Я умею: промпты для изображений и видео, а также маркетинговые тексты (посты, описания, слоганы). Что из этого вам нужно?";

const MISSING_QUESTIONS: Record<string, string> = {
  subject: "Что должно быть в кадре или о чём материал?",
  product: "Что продаём? Опишите продукт или услугу в паре слов.",
};

// ---------- Запасной разбор по ключевым словам ----------
// Корни слов, чтобы ловить падежи: «картинку», «картинки», «фотографии»…

const KEYWORDS: Record<TemplateType, RegExp> = {
  image:
    /(фото|картин|изображ|иллюстрац|баннер|обложк|постер|плакат|визуал|аватар|карточк[уиа]? товар|кадр|снимок|снимк|image|picture|photo|banner)/i,
  video: /(видео|ролик|рилс|reels?|shorts?|клип|анимац|тикток|tiktok|video|сторис)/i,
  text:
    /(текст|пост(?!ер)|описани|слоган|заголов|статья|стать[юи]|письм|рассылк|сценари|контент[- ]план|подпис|caption|copy|лендинг)/i,
};

const OUT_OF_SCOPE_HINTS = /(погод|курс валют|рецепт|код на|программ|юрист|оплат|возврат денег|пароль)/i;

export function classifyByKeywords(text: string): IntentResult {
  const base = {
    summary: text.trim().slice(0, 120),
    criticalMissing: [] as string[],
    niceToHave: [] as string[],
    source: "keywords" as const,
  };

  const matched = (Object.keys(KEYWORDS) as TemplateType[]).filter((t) => KEYWORDS[t].test(text));

  // «пост с картинкой»: если есть «пост» и визуал — это mixed, а не только image
  if (matched.length === 1) {
    return { ...base, type: matched[0], confidence: 0.75, clarifyQuestion: null, options: [] };
  }
  if (matched.length > 1) {
    return {
      ...base,
      type: "mixed",
      confidence: 0.6,
      clarifyQuestion: "С чего начнём?",
      options: ["Сначала текст", "Сначала визуал", "Сразу всё"],
    };
  }
  if (OUT_OF_SCOPE_HINTS.test(text)) {
    return { ...base, type: "out_of_scope", confidence: 0.6, clarifyQuestion: null, options: [] };
  }
  return {
    ...base,
    type: "unclear",
    confidence: 0.3,
    clarifyQuestion: DEFAULT_CLARIFY.question,
    options: DEFAULT_CLARIFY.options,
  };
}

// ---------- Разбор ответа модели ----------

/** Достаём JSON даже если модель обернула его в ``` или добавила текст. Возвращает null, если не вышло. */
export function parseLLMResponse(raw: string): IntentResult | null {
  if (!raw) return null;
  const start = raw.indexOf("{");
  const end = raw.lastIndexOf("}");
  if (start === -1 || end <= start) return null;

  let data: any;
  try {
    data = JSON.parse(raw.slice(start, end + 1));
  } catch {
    return null;
  }

  if (!VALID_TYPES.includes(data.type)) return null;
  const confidence = Number(data.confidence);
  if (!Number.isFinite(confidence)) return null;

  const strArr = (v: unknown) => (Array.isArray(v) ? v.filter((x) => typeof x === "string") : []);

  return {
    type: data.type,
    confidence: Math.min(1, Math.max(0, confidence)),
    summary: typeof data.summary === "string" ? data.summary : "",
    criticalMissing: strArr(data.critical_missing),
    niceToHave: strArr(data.nice_to_have),
    clarifyQuestion: typeof data.clarify_question === "string" && data.clarify_question.trim() ? data.clarify_question : null,
    options: strArr(data.options).slice(0, 5),
    source: "llm",
  };
}

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("LLM timeout")), ms);
    p.then(
      (v) => { clearTimeout(timer); resolve(v); },
      (e) => { clearTimeout(timer); reject(e); },
    );
  });
}

// ---------- Классификация ----------

export async function classifyIntent(userText: string, opts: RouterOptions = {}): Promise<IntentResult> {
  const text = (userText ?? "").trim();
  if (!text) {
    return { ...classifyByKeywords(""), type: "unclear" };
  }

  if (opts.callLLM) {
    try {
      const raw = await withTimeout(opts.callLLM(ROUTER_SYSTEM_PROMPT, text), opts.timeoutMs ?? DEFAULT_TIMEOUT_MS);
      const parsed = parseLLMResponse(raw);
      if (parsed) return parsed;
      console.warn("[intentRouter] LLM вернула невалидный JSON, переключаюсь на ключевые слова");
    } catch (err) {
      console.warn("[intentRouter] LLM недоступна, переключаюсь на ключевые слова:", (err as Error).message);
    }
  }
  return classifyByKeywords(text);
}

// ---------- Решение: что делать дальше ----------

export function decide(intent: IntentResult, minConfidence = DEFAULT_MIN_CONFIDENCE): RouterDecision {
  const notice = intent.source === "keywords" ? FALLBACK_NOTICE : "";

  if (intent.type === "out_of_scope") {
    return { action: "out_of_scope", message: OUT_OF_SCOPE_MESSAGE, intent };
  }

  if (intent.type === "unclear" || intent.type === "mixed" || intent.confidence < minConfidence) {
    const hasOwnOptions = intent.options.length >= 2;
    return {
      action: "clarify",
      message: notice + (intent.clarifyQuestion ?? DEFAULT_CLARIFY.question),
      options: hasOwnOptions ? intent.options : DEFAULT_CLARIFY.options,
      intent,
    };
  }

  // Тип понятен, но без ключевых данных результат будет бессмысленным
  const missing = intent.criticalMissing.find((m) => MISSING_QUESTIONS[m]);
  if (missing) {
    return {
      action: "clarify",
      message: intent.clarifyQuestion ?? MISSING_QUESTIONS[missing],
      options: intent.options,
      intent,
    };
  }

  return { action: "build_prompt", template: intent.type as TemplateType, intent };
}

/** Главная точка входа: одна функция, которую вызывает обработчик сообщения. */
export async function routeRequest(userText: string, opts: RouterOptions = {}): Promise<RouterDecision> {
  const intent = await classifyIntent(userText, opts);
  const decision = decide(intent, opts.minConfidence);
  logUnusual(userText, decision);
  return decision;
}

// ---------- Логирование нестандартных запросов ----------
// Замените на запись в вашу БД / таблицу. Раз в неделю смотрите, какие запросы повторяются.

export function logUnusual(userText: string, decision: RouterDecision): void {
  if (decision.action === "build_prompt") return;
  console.info(
    "[intentRouter:unusual]",
    JSON.stringify({
      at: new Date().toISOString(),
      text: userText,
      type: decision.intent.type,
      confidence: decision.intent.confidence,
      source: decision.intent.source,
      action: decision.action,
    }),
  );
}
