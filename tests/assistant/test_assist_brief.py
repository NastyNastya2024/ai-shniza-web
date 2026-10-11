"""Бриф: понять суть, уточнить детали кнопками, предложить 3 варианта промпта, не принимать мусор."""
import json

import pytest

from assistant import brief as BR
from assistant_testkit import FakeTransport, answer_open_brief, ok_json, pick_want_prompt, to_variants

SID = "b1"


def blk(r, typ):
    return next((b for b in r["blocks"] if b["type"] == typ), None)


def brief_json(clear=True, summary="кот-повар готовит завтрак", qs=None):
    qs = qs if qs is not None else [
        {"id": "cat", "label": "Какой кот", "options": ["Рыжий в колпаке", "Пушистый котёнок", "Толстый ленивый"]},
        {"id": "place", "label": "Где", "options": ["Уютная кухня", "Кафе", "Кемпинг"]},
    ]
    return json.dumps({"clear": clear, "summary": summary, "questions": qs}, ensure_ascii=False)


def variants_json(n=3, tag="A"):
    return json.dumps({"variants": [{"title": f"Вариант {tag}{i}", "prompt": f"A ginger cat chef variant {tag}{i}, warm kitchen light, steam"}
                                    for i in range(n)]}, ensure_ascii=False)


# ---------------- мусор и пустые идеи
@pytest.mark.parametrize("text,junk", [("ооло", True), ("ааа", True), ("фывапр", True), ("ыыы ооо", True), ("qwerty", True),
                                       ("кот", False), ("ок", False), ("кот жарит яичницу", False), ("лоу-фай", False),
                                       ("видео", False), ("Seedance", False)])
def test_is_junk(text, junk):
    assert BR.is_junk(text) is junk


@pytest.mark.parametrize("text,has", [("нужно сделать видео", False), ("сделай красивую картинку", False),
                                      ("видео ооло", False), ("видео про кота", True), ("логотип кофейни", True)])
def test_has_subject(text, has):
    assert BR.has_subject(text) is has


def test_empty_idea_asks_clarifying_questions_without_examples(make_assistant):
    a = make_assistant(brief=True)
    r = a.handle("Нужно сделать видео", {}, SID)
    assert r["intent"] == "need_subject"
    assert "Сначала напишите основную идею" in r["text"] and "помогу сформировать промпт" in r["text"]
    for q in ("Кто в кадре?", "Где это происходит?", "Что происходит", "атмосфера", "Нюансы"):
        assert q in r["text"], q
    assert r["chips"] == [] and "кот" not in r["text"].lower()      # никаких готовых примеров
    r = a.handle("рыжий кот жарит яичницу", {}, SID)          # тип известен — сначала модель
    assert r["intent"] == "generate_task" and blk(r, "models")


def test_junk_message_is_not_accepted(make_assistant):
    a = make_assistant(brief=True)
    r = a.handle("ооло", {}, SID)
    assert r["intent"] == "junk" and "Не совсем поняла" in r["text"]
    a.handle("видео", {}, SID)
    r = a.handle("ооло", {}, SID)
    assert r["intent"] == "need_subject" and "Не совсем поняла" in r["text"]


def test_junk_refine_does_not_touch_prompt(make_assistant):
    a = make_assistant(brief=False)
    a.handle("видео кот жарит яичницу", {}, SID)
    r = pick_want_prompt(a, SID, "seedance-2-5")
    before = r["generate_prompt"]
    r = a.handle("ооло", {}, SID)
    assert r["intent"] == "refine_unclear" and all(c["action"] == "refine" for c in r["chips"])
    r = a.handle("", {}, SID, action={"type": "refine", "value": "ооло"})
    assert r["intent"] == "refine_unclear"
    r = a.handle("", {}, SID, action={"type": "use_mine"})
    assert "ооло" not in r["generate_prompt"] and before


# ---------------- бриф без LLM
def test_rule_brief_questions_preselect_from_text(make_assistant):
    a = make_assistant(llm=False, brief=True)
    a.handle("видео в стиле аниме: кот жарит яичницу", {}, SID)
    r = pick_want_prompt(a, SID, "kling-v2-5-turbo-pro")
    assert r["intent"] == "brief"
    # этап 1: только открытые вопросы из clarify
    assert "под Kling" in r["text"] or "Kling" in r["text"]
    qs = blk(r, "brief")["questions"]
    open_qs = [q for q in qs if q.get("open")]
    assert open_qs and all(q["options"] == [] for q in open_qs)
    assert all(not q.get("options") for q in qs)
    assert any("движение субъекта" in q["label"].lower() or "траектори" in q["label"].lower()
               or "исходный кадр" in q["label"].lower() for q in open_qs)
    # этап 2: после ответа — кнопки слотов; стиль из идеи предвыбран
    r = answer_open_brief(a, SID, "кот жарит яичницу на кухне")
    assert r["intent"] == "brief"
    qs = blk(r, "brief")["questions"]
    style = next(q for q in qs if "стиля" in q["label"].lower())
    assert next(o for o in style["options"] if o["selected"])["value"] == "anime"
    mood = next(q for q in qs if "атмосфер" in q["label"].lower())
    assert mood["options"][-1]["label"] == "Не добавлять" and mood["options"][-1]["selected"]
    assert r["chips"] and any(c["action"] == "variants" for c in r["chips"])


def test_skip_open_brief_goes_to_slot_buttons(make_assistant):
    """Без ответа на открытые вопросы «Продолжить» ведёт к кнопкам, не к вариантам."""
    a = make_assistant(llm=False, brief=True)
    a.handle("музыка: трек для ролика", {}, SID)
    r = pick_want_prompt(a, SID, "ace-step")
    assert r["intent"] == "brief"
    assert any(c["label"] == "Продолжить" for c in r["chips"])
    r = a.handle("", {}, SID, action={"type": "variants", "value": "skip"})
    assert r["intent"] == "brief"
    qs = blk(r, "brief")["questions"]
    assert any(q["id"] == "genre" for q in qs) and any(q.get("options") for q in qs)
    assert "кнопками" in r["text"].lower() or "Make prompt" in r["text"] or "Сделать промпт" in r["text"]
    r = a.handle("", {}, SID, action={"type": "variants", "value": "skip"})
    assert r["intent"] == "variants"


def test_rule_questions_profile_only_when_asked():
    from assistant.cards import load_cards
    cards, _ = load_cards()
    card = cards["seedance-2-5"]
    generic, _ = BR.rule_questions("video", "кот", "ru")
    profile, _ = BR.rule_questions("video", "кот", "ru", card=card, use_profile=True)
    assert any(q["id"] == "who" for q in generic)
    assert any("последовательность" in q["label"].lower() or "референс" in q["label"].lower() for q in profile)
    assert not any(q["id"] == "who" for q in profile)


def test_profile_clarify_skips_facts_already_in_idea():
    """Идея «машина едет по мосту» — не переспрашиваем что/кто, спрашиваем пробелы."""
    from assistant.cards import load_cards
    cards, _ = load_cards()
    card = cards["seedance-2-5"]
    idea = "хочу видео в сиданс где машина едет по мосту над морем"
    q, _ = BR.rule_questions("video", idea, "ru", card=card, use_profile=True, phase="open")
    labels = " ".join(x["label"].lower() for x in q)
    assert "что происходит" not in labels
    assert "кто или что" not in labels
    assert "последовательность" not in labels
    assert q and any("камер" in x["label"].lower() or "стиль" in x["label"].lower()
                     or "звук" in x["label"].lower() or "референс" in x["label"].lower() for x in q)


def test_rule_brief_answer_then_three_distinct_variants(make_assistant):
    a = make_assistant(llm=False, brief=True)
    a.handle("видео: кот жарит яичницу", {}, SID)
    pick_want_prompt(a, SID, "kling-v2-5-turbo-pro")
    answer_open_brief(a, SID, "утро, тёплый свет")
    r = a.handle("", {}, SID, action={"type": "brief", "value": {"id": "mood", "value": "cozy"}})
    mood = next(q for q in blk(r, "brief")["questions"] if q["id"] == "mood")
    assert next(o for o in mood["options"] if o["selected"])["value"] == "cozy"
    r = a.handle("", {}, SID, action={"type": "variants"})
    items = blk(r, "variants")["items"]
    assert r["intent"] == "variants" and len(items) == 3 and len({i["text"] for i in items}) == 3
    assert all("уютная тёплая атмосфера" in i["text"].lower() for i in items)   # выбор человека во всех вариантах
    assert all(i["text"].startswith("Кот жарит яичницу") for i in items)
    r = a.handle("", {}, SID, action={"type": "use_variant", "value": items[1]["id"]})
    assert r["intent"] == "use_variant" and blk(r, "models") and items[1]["title"] in r["text"]
    # без движения по умолчанию — промпт варианта без вставки камеры
    assert blk(r, "prompt")["text"] == items[1]["text"]
    # после варианта — шаг улучшения (Claude/GPT), не сразу генерация
    assert {m["id"] for m in r["models"]} & {"claude-sonnet-5", "gpt-5-4", "claude-4-5-haiku"}
    # «Доработать» → прямой чат с текстовой моделью
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "gpt-5-4"})
    assert r["intent"] == "polish_chat" and r["generate_model"] == "gpt-5-4"
    assert a.d.store.get(SID).get("kind") == "text" and a.d.store.get(SID).get("await") == "chat"
    # «Использовать этот промпт» — к моделям генерации (новый сеанс)
    sid2 = SID + "-skip"
    a.handle("видео: кот жарит яичницу", {}, sid2)
    pick_want_prompt(a, sid2, "kling-v2-5-turbo-pro")
    answer_open_brief(a, sid2, "утро, тёплый свет")
    a.handle("", {}, sid2, action={"type": "brief", "value": {"id": "mood", "value": "cozy"}})
    r = a.handle("", {}, sid2, action={"type": "variants"})
    v2 = blk(r, "variants")["items"]
    a.handle("", {}, sid2, action={"type": "use_variant", "value": v2[1]["id"]})
    r = a.handle("", {}, sid2, action={"type": "skip_polish"})
    # модель уже выбрана на первом шаге — сразу настройки, без второго выбора
    assert r["intent"] == "skip_polish" and not blk(r, "models")
    assert r["generate_model"] == "kling-v2-5-turbo-pro"
    assert r["generate_prompt"] == v2[1]["text"] and blk(r, "params") and blk(r, "prompt")


def test_more_variants_are_different(make_assistant):
    a = make_assistant(llm=False, brief=True)
    a.handle("картинка: лиса в очках", {}, SID)
    pick_want_prompt(a, SID, "seedream-5-pro")
    r1 = to_variants(a, SID)
    r2 = a.handle("", {}, SID, action={"type": "more_variants"})
    t1 = [i["text"] for i in blk(r1, "variants")["items"]]
    t2 = [i["text"] for i in blk(r2, "variants")["items"]]
    assert t1 != t2


def test_free_text_in_brief_becomes_detail(make_assistant):
    a = make_assistant(llm=False, brief=True)
    a.handle("видео: кот жарит яичницу", {}, SID)
    pick_want_prompt(a, SID, "kling-v2-5-turbo-pro")
    r = a.handle("кот в поварском колпаке, на заднем плане окно", {}, SID)
    assert r["intent"] == "brief"  # этап 2 — кнопки после ответа
    assert "поварском колпаке" in ";".join(a.d.store.get(SID).get("brief", {}).get("extra") or [])
    r = a.handle("", {}, SID, action={"type": "variants"})
    assert r["intent"] == "variants"
    assert all("поварском колпаке" in i["text"] for i in blk(r, "variants")["items"])


def test_param_words_in_variants_dont_call_llm(make_assistant):
    tr = FakeTransport(omniroute=[("ok", brief_json()), ("ok", variants_json())])
    a = make_assistant(tr, brief=True)
    a.handle("видео: кот жарит яичницу", {}, SID)
    pick_want_prompt(a, SID, "kling-v2-5-turbo-pro")
    to_variants(a, SID)
    n = len(tr.calls)
    r = a.handle("вертикально", {}, SID)
    assert len(tr.calls) == n and r["intent"] == "variants" and r["generate_params"]["aspect_ratio"] == "9:16"


def test_detailed_idea_skips_questions(make_assistant):
    a = make_assistant(llm=False, brief=True)
    a.handle("видео: рыжий кот в поварском колпаке жарит яичницу на чугунной сковороде на уютной кухне "
             "утренний свет пар поднимается камера медленно приближается", {}, SID)
    r = pick_want_prompt(a, SID, "kling-v2-5-turbo-pro")
    assert r["intent"] == "variants"


# ---------------- бриф с LLM: вопросы под идею и 3 варианта
def test_llm_tailored_questions_and_variants(make_assistant):
    tr = FakeTransport(omniroute=[("ok", variants_json())])
    a = make_assistant(tr, brief=True)
    # тип+идея → модели → «нужен промпт?» → clarify профиля → варианты LLM
    r = a.handle("видео: кодта жарит иишницу", {}, SID)
    assert r["intent"] == "generate_task" and blk(r, "models")
    r = pick_want_prompt(a, SID, "kling-v2-5-turbo-pro")
    assert r["intent"] == "brief" and "Kling" in r["text"]
    assert any(q.get("open") for q in blk(r, "brief")["questions"])
    r = to_variants(a, SID)
    items = blk(r, "variants")["items"]
    assert len(items) == 3 and items[0]["title"] == "Вариант A0" and not r["degraded"]
    sent = json.loads(tr.calls[0]["payload"]["messages"][1]["content"])
    assert "structure" in sent["model"] and "prompt_example" in sent["model"]
    assert "clarify" not in sent["model"]
    assert r["llm"]["used"] and tr.calls[0]["payload"]["max_tokens"] >= 900


def test_llm_says_unclear_asks_subject(make_assistant):
    a = make_assistant(llm=False, brief=True)
    r = a.handle("видео ооло", {}, SID)                             # нет сути — спросить идею
    assert r["intent"] == "need_subject" and "основную идею" in r["text"].lower()
    r = a.handle("рыжий кот жарит яичницу", {}, SID)                # дальше — выбор модели
    assert r["intent"] == "generate_task" and blk(r, "models")


def test_variants_free_text_is_change_for_llm(make_assistant):
    tr = FakeTransport(omniroute=[("ok", variants_json(tag="A")), ("ok", variants_json(tag="B"))])
    a = make_assistant(tr, brief=True)
    a.handle("видео: кот жарит яичницу", {}, SID)
    pick_want_prompt(a, SID, "kling-v2-5-turbo-pro")
    to_variants(a, SID)
    r = a.handle("сделай смешнее, пусть яйцо подпрыгивает", {}, SID)
    sent = json.loads(tr.calls[1]["payload"]["messages"][1]["content"])
    assert sent["change"] == "сделай смешнее, пусть яйцо подпрыгивает"
    assert blk(r, "variants")["items"][0]["title"] == "Вариант B0"


def test_llm_variants_fail_falls_back_to_rules(make_assistant):
    tr = FakeTransport(omniroute=[("http", 503)], groq=[("http", 503)])
    a = make_assistant(tr, brief=True)
    a.handle("видео: кот жарит яичницу", {}, SID)
    pick_want_prompt(a, SID, "kling-v2-5-turbo-pro")
    answer_open_brief(a, SID, "утро, тёплый свет")
    a.handle("", {}, SID, action={"type": "brief", "value": {"id": "mood", "value": "cozy"}})
    r = a.handle("", {}, SID, action={"type": "variants"})
    items = blk(r, "variants")["items"]
    assert r["degraded"] and len(items) >= 2 and all("уютная тёплая атмосфера" in i["text"].lower() for i in items)


def test_brief_answer_must_be_one_of_options(make_assistant):
    a = make_assistant(llm=False, brief=True)
    a.handle("видео: кот", {}, SID)
    pick_want_prompt(a, SID, "kling-v2-5-turbo-pro")
    answer_open_brief(a, SID)
    r = a.handle("", {}, SID, action={"type": "brief", "value": {"id": "style", "value": "<script>"}})
    assert not any(o["selected"] and o["value"] == "<script>" for q in blk(r, "brief")["questions"] for o in q["options"])


def test_validate_brief_and_variants():
    with pytest.raises(ValueError):
        BR.validate_brief({"clear": True, "questions": []})
    d = BR.validate_brief({"clear": True, "questions": [{"id": "X y!", "label": "Кто", "options": ["a", "b", "c", "d", "e"]}]})
    assert d["questions"][0]["id"] == "xy" and len(d["questions"][0]["options"]) == 4
    with pytest.raises(ValueError):
        BR.validate_variants({"variants": [{"title": "a", "prompt": ""}]})
    assert BR.validate_variants({"variants": []}) == {"variants": []}


def test_short_idea_gets_who_where_what_questions(make_assistant):
    a = make_assistant(llm=False, brief=True)
    # тип+идея → сначала модель, потом clarify профиля
    r = a.handle("видео кот", {}, SID)
    assert r["intent"] == "generate_task" and blk(r, "models")
    r = pick_want_prompt(a, SID, "kling-v2-5-turbo-pro")
    assert r["intent"] == "brief"
    open_qs = [q["label"] for q in blk(r, "brief")["questions"] if q.get("open")]
    assert open_qs[0] == "Исходный кадр или текстовый запрос?"
    r = a.handle("рыжий кот на кухне жарит яичницу, утро, тёплый свет", {}, SID)   # ответ → этап 2
    assert r["intent"] == "brief"
    assert any(q["id"] == "style" for q in blk(r, "brief")["questions"])
    r = a.handle("", {}, SID, action={"type": "variants"})
    assert r["intent"] == "variants"
    assert all("рыжий кот на кухне" in i["text"].lower() for i in blk(r, "variants")["items"])


def test_llm_open_questions_have_no_options():
    d = BR.validate_brief({"clear": True, "summary": "кот", "questions": [
        {"id": "mood", "label": "Атмосфера?", "options": ["Уютная", "Смешная"]},
        {"id": "who", "label": "Какой кот?", "options": []},
        {"id": "where", "label": "Где?", "options": ["одна"]}]})
    assert [q["id"] for q in d["questions"]] == ["who", "where", "mood"]     # сначала открытые
    assert d["questions"][1]["options"] == []


# ---------- качество: почему было «Закатом. Тихое, Вечер…» и что теперь
def test_rule_variants_are_readable_sentences(make_assistant):
    qs = [{"id": "mood", "label": "Атмосфера?", "options": [{"value": "Тихое", "label": "Тихое"}]},
          {"id": "time", "label": "Время суток?", "options": [{"value": "Вечер", "label": "Вечер"}]}]
    from assistant.cards import load_cards
    c, _ = load_cards()
    v = BR.rule_variants(c["seedance-2-5"], "нужно видео с закатом", {"mood": "Тихое", "time": "Вечер"}, [], "ru",
                         questions=qs)[0]["text"]
    assert v.startswith("Видео с закатом.") and "Атмосфера: тихое; Время суток: вечер" in v
    assert "Закатом." not in v


def test_variants_second_chance_single_prompt(make_assistant):
    one = json.dumps({"prompt": "A calm sunset over the sea, golden light, slow drone flight", "note": ""})
    tr = FakeTransport(omniroute=[("ok", "not json"), ("ok", "still not json"), ("ok", one)],
                       groq=[("http", 503)])
    a = make_assistant(tr, brief=True)
    a.handle("видео с закатом", {}, SID)
    pick_want_prompt(a, SID, "seedance-2-5")
    r = to_variants(a, SID)
    items = blk(r, "variants")["items"]
    assert not r["degraded"] and len(items) == 3
    assert items[0]["text"].startswith("A calm sunset") and items[1]["text"].startswith("A calm sunset")
    assert items[1]["text"] != items[0]["text"]


def test_variants_call_gets_longer_timeout(make_assistant):
    tr = FakeTransport(omniroute=[("ok", variants_json())])
    a = make_assistant(tr, brief=True)
    a.handle("видео: кот", {}, SID)
    pick_want_prompt(a, SID, "seedance-2-5")
    to_variants(a, SID)
    assert tr.calls[0]["timeout"] > 7      # варианты ×2.5 от базового timeout


def test_validate_variants_tolerates_shapes():
    d = BR.validate_variants({"prompts": ["A first long enough prompt", "A second long enough prompt"]})
    assert [v["text"] for v in d["variants"]] == ["A first long enough prompt", "A second long enough prompt"]
    d = BR.validate_variants({"variants": [{"title": "a", "text": "A cat in a hat"}, {"title": "b", "prompt": "A dog"}]})
    assert len(d["variants"]) == 2


def test_variants_prompt_asks_for_rich_structure():
    assert "model.structure" in BR.VARIANTS_SYSTEM and "Use EVERY detail" in BR.VARIANTS_SYSTEM
    assert "prompt_example" in BR.VARIANTS_SYSTEM and "ONE coherent scene" in BR.VARIANTS_SYSTEM


def test_selfcheck_runs_with_fake_provider(monkeypatch, capsys):
    import assistant.selfcheck as sc
    import assistant.llm as llm_mod
    from assistant.llm import LLMProvider
    monkeypatch.setattr("assistant.flask_adapter.providers_from_env",
                        lambda env=None: [LLMProvider("groq", "https://api.groq.com/openai/v1", "k", "m")])
    answers = iter([brief_json(), variants_json(), ok_json()])

    def tr(url, headers, payload, timeout):
        return 200, {"choices": [{"message": {"content": next(answers)}}], "usage": {}}

    monkeypatch.setattr(llm_mod, "requests_transport", tr)
    assert sc.main(["x", "видео кот"]) == 0
    out = capsys.readouterr().out
    assert "[brief] ok" in out and "[variants] ok" in out and "LLM работает" in out and " k " not in out


# ---------- непонятное несколько раз подряд: не зацикливаться на одном ответе
def test_repeated_junk_escalates_not_loops(make_assistant):
    a = make_assistant(brief=True)
    a.handle("", {}, SID, action={"type": "choose_type", "value": "music"})
    texts = []
    for junk in ("ророро", "ллдлд", "ололол", "прпрпр"):
        r = a.handle(junk, {}, SID)
        texts.append(r["text"])
    assert len(set(texts[:3])) == 3                                  # каждый раз другой ответ
    assert "Для чего он" in texts[0] and "Для чего он" not in texts[1]  # длинный список — только первый раз
    assert r["chips"] and any(c["label"] == "Лоу-фай" for c in r["chips"])
    assert r["chips"][-1]["action"] == "restart"
    r = a.handle("", {}, SID, action={"type": "send", "value": next(c for c in r["chips"] if c["label"] == "Лоу-фай")["value"]})
    assert r["intent"] in ("brief", "variants", "generate_task", "has_prompt", "need_subject")
    r = a.handle("ололо", {}, SID)                                   # счётчик сброшен — снова мягко
    assert "Не совсем поняла" in r["text"] or "Похоже" in r["text"] or r["intent"] in ("brief", "variants", "has_prompt", "need_subject", "generate_task")


def test_pick_model_asks_has_prompt_before_idea(make_assistant):
    """Выбор модели без идеи → сразу «улучшить промпт?», без лишнего «опишите идею одной фразой»."""
    a = make_assistant(brief=True)
    r = a.handle("", {}, SID, action={"type": "choose_type", "value": "video"})
    assert blk(r, "models")
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "veo-3-1"})
    assert r["intent"] == "has_prompt"
    assert "Опишите идею одной фразой" not in r["text"]
    assert any(c.get("action") == "has_prompt" and c.get("value") == "yes" for c in r["chips"])
    r = a.handle("", {}, SID, action={"type": "has_prompt", "value": "yes"})
    assert r["intent"] == "brief"
    assert "Опишите идею одной фразой" not in r["text"]
    # идея в ответе на clarify → дальше слоты, идея сохранена
    r = a.handle("машина едет по мосту над морем", {}, SID)
    assert r["intent"] in ("brief", "variants")
    assert a.d.store.get(SID).get("idea", "").startswith("машина")


def test_skip_polish_keeps_first_model(make_assistant):
    """После одобрения промпта не спрашиваем модель снова — она уже выбрана."""
    a = make_assistant(llm=False, brief=True)
    a.handle("видео: машина на мосту", {}, SID)
    pick_want_prompt(a, SID, "veo-3-1")
    answer_open_brief(a, SID)
    to_variants(a, SID)
    vids = a.d.store.get(SID).get("variants") or []
    assert vids
    a.handle("", {}, SID, action={"type": "use_variant", "value": vids[0]["id"]})
    r = a.handle("", {}, SID, action={"type": "skip_polish"})
    assert r["generate_model"] == "veo-3-1"
    assert not blk(r, "models")
    assert blk(r, "params") or blk(r, "summary") or "Сгенерировать" in " ".join(
        c.get("label") or "" for c in (r.get("chips") or []))


def test_restart_button(make_assistant):
    a = make_assistant(brief=True)
    r = a.handle("", {}, SID, action={"type": "choose_type", "value": "video"})
    assert blk(r, "models")  # тип сразу → сначала модели
    pick_want_prompt(a, SID, "seedance-2-5")
    r = a.handle("", {}, SID, action={"type": "restart"})
    assert r["intent"] == "ask_type" and len(r["chips"]) == 5   # prompt/image/video/music/sfx
    assert r["chips"][0]["value"] == "prompt"


def test_junk_on_variants_does_not_call_llm(make_assistant):
    tr = FakeTransport(omniroute=[("ok", brief_json()), ("ok", variants_json())])
    a = make_assistant(tr, brief=True)
    a.handle("видео: кот", {}, SID)
    pick_want_prompt(a, SID, "seedance-2-5")
    to_variants(a, SID)
    n = len(tr.calls)
    r = a.handle("ророро", {}, SID)
    assert len(tr.calls) == n and r["intent"] == "variants" and "Не совсем поняла" in r["text"]
