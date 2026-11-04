import { describe, it, expect } from "vitest";
import { classifyByKeywords, parseLLMResponse, decide, routeRequest } from "./intentRouter";

const llmReturns = (obj: unknown) => async () => JSON.stringify(obj);
const llmDown = async () => { throw new Error("503"); };
const llmHangs = () => new Promise<string>(() => {});

describe("Главный баг: «маркетинговые материалы»", () => {
  it("при упавшей модели НЕ уходит в шаблон промпта, а задаёт уточнение", async () => {
    const d = await routeRequest("мне нужны маркетинговые материалы", { callLLM: llmDown });
    expect(d.action).toBe("clarify");
    if (d.action === "clarify") expect(d.options.length).toBeGreaterThanOrEqual(2);
  });

  it("без модели вообще — тоже уточнение", async () => {
    const d = await routeRequest("мне нужны маркетинговые материалы");
    expect(d.action).toBe("clarify");
  });

  it("при работающей модели с type=unclear — уточнение с кнопками модели", async () => {
    const d = await routeRequest("мне нужны маркетинговые материалы", {
      callLLM: llmReturns({ type: "unclear", confidence: 0.3, summary: "", critical_missing: [], nice_to_have: [],
        clarify_question: "Какие материалы нужны?", options: ["Тексты", "Баннер", "Видео"] }),
    });
    expect(d).toMatchObject({ action: "clarify", message: "Какие материалы нужны?", options: ["Тексты", "Баннер", "Видео"] });
  });
});

describe("Разбор по ключевым словам", () => {
  it.each([
    ["фото кофейной чашки на столе", "image"],
    ["нужен баннер для сайта", "image"],
    ["сделай рилс про кофейню", "video"],
    ["видео с дроном над горами", "video"],
    ["напиши продающий пост", "text"],
    ["слоган для бренда", "text"],
    ["постер к фестивалю", "image"],
    ["пост с картинкой про коллекцию", "mixed"],
    ["маркетинговые материалы", "unclear"],
    ["креативы для рекламы", "unclear"],
    ["какая погода завтра", "out_of_scope"],
  ])("%s → %s", (text, type) => {
    expect(classifyByKeywords(text).type).toBe(type);
  });
});

describe("Ответ модели", () => {
  it("понимает JSON внутри ```", () => {
    const r = parseLLMResponse('```json\n{"type":"image","confidence":0.9}\n```');
    expect(r?.type).toBe("image");
  });
  it("мусор → null", () => {
    expect(parseLLMResponse("Конечно! Вот промпт: ...")).toBeNull();
    expect(parseLLMResponse('{"type":"poster","confidence":1}')).toBeNull();
  });
  it("мусор от модели → запасной разбор", async () => {
    const d = await routeRequest("видео про кофе", { callLLM: async () => "не JSON" });
    expect(d).toMatchObject({ action: "build_prompt", template: "video" });
    expect(d.intent.source).toBe("keywords");
  });
  it("зависшая модель → таймаут → запасной разбор", async () => {
    const d = await routeRequest("маркетинговые материалы", { callLLM: llmHangs, timeoutMs: 50 });
    expect(d.action).toBe("clarify");
  });
});

describe("Решение", () => {
  const base = { summary: "", criticalMissing: [], niceToHave: [], clarifyQuestion: null, options: [], source: "llm" as const };

  it("уверенный image → шаблон image", () => {
    expect(decide({ ...base, type: "image", confidence: 0.9 })).toMatchObject({ action: "build_prompt", template: "image" });
  });
  it("text → шаблон text, а НЕ визуальный", () => {
    expect(decide({ ...base, type: "text", confidence: 0.9 })).toMatchObject({ action: "build_prompt", template: "text" });
  });
  it("низкая уверенность → уточнение", () => {
    expect(decide({ ...base, type: "image", confidence: 0.5 }).action).toBe("clarify");
  });
  it("нет продукта для поста → спрашиваем продукт", () => {
    const d = decide({ ...base, type: "text", confidence: 0.9, criticalMissing: ["product"] });
    expect(d.action).toBe("clarify");
  });
  it("вне темы → честный отказ", () => {
    expect(decide({ ...base, type: "out_of_scope", confidence: 0.9 }).action).toBe("out_of_scope");
  });
});
