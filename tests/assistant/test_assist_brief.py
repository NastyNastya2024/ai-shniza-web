"""Бриф: понять суть, уточнить детали кнопками, предложить 3 варианта промпта, не принимать мусор."""
import json

import pytest

from assistant import brief as BR
from assistant_testkit import FakeTransport, ok_json

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
    for q in ("Кто в кадре?", "Где это происходит?", "Что происходит", "атмосфера", "Нюансы"):
        assert q in r["text"], q
    assert r["chips"] == [] and "кот" not in r["text"].lower()      # никаких готовых примеров
    r = a.handle("рыжий кот жарит яичницу", {}, SID)          # тип уже известен — сразу модели
    assert r["intent"] == "generate_task" and blk(r, "models") and "кот" in r["text"]


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
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "seedance-2-5"})
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
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "kling-v2-5-turbo-pro"})
    assert r["intent"] == "brief"
    qs = blk(r, "brief")["questions"]
    assert [q["label"] for q in qs] == ["Нюансы: время суток, цвета, звук, детали?", "Стиль", "Атмосфера", "Камера"]
    assert qs[0]["open"] and qs[0]["options"] == []                     # нюансы — своими словами
    style = qs[1]
    assert next(o for o in style["options"] if o["selected"])["value"] == "anime"
    assert qs[2]["options"][-1]["label"] == "Не важно" and qs[2]["options"][-1]["selected"]
    assert r["chips"][0]["action"] == "variants" and r["chips"][0].get("primary")
    assert "generate_prompt" not in r                      # промпта ещё нет — сначала детали


def test_rule_brief_answer_then_three_distinct_variants(make_assistant):
    a = make_assistant(llm=False, brief=True)
    a.handle("видео: кот жарит яичницу", {}, SID)
    a.handle("", {}, SID, action={"type": "pick_model", "value": "kling-v2-5-turbo-pro"})
    r = a.handle("", {}, SID, action={"type": "brief", "value": {"id": "mood", "value": "cozy"}})
    mood = next(q for q in blk(r, "brief")["questions"] if q["id"] == "mood")
    assert next(o for o in mood["options"] if o["selected"])["value"] == "cozy"
    r = a.handle("", {}, SID, action={"type": "variants"})
    items = blk(r, "variants")["items"]
    assert r["intent"] == "variants" and len(items) == 3 and len({i["text"] for i in items}) == 3
    assert all("уютная тёплая атмосфера" in i["text"].lower() for i in items)   # выбор человека во всех вариантах
    assert all(i["text"].startswith("Кот жарит яичницу") for i in items)
    r = a.handle("", {}, SID, action={"type": "use_variant", "value": items[1]["id"]})
    assert r["generate_prompt"] == items[1]["text"] and blk(r, "params") and blk(r, "prompt")
    assert items[1]["title"] in r["text"]


def test_more_variants_are_different(make_assistant):
    a = make_assistant(llm=False, brief=True)
    a.handle("картинка: лиса в очках", {}, SID)
    a.handle("", {}, SID, action={"type": "pick_model", "value": "seedream-5-pro"})
    r1 = a.handle("", {}, SID, action={"type": "variants"})
    r2 = a.handle("", {}, SID, action={"type": "more_variants"})
    t1 = [i["text"] for i in blk(r1, "variants")["items"]]
    t2 = [i["text"] for i in blk(r2, "variants")["items"]]
    assert t1 != t2


def test_free_text_in_brief_becomes_detail(make_assistant):
    a = make_assistant(llm=False, brief=True)
    a.handle("видео: кот жарит яичницу", {}, SID)
    a.handle("", {}, SID, action={"type": "pick_model", "value": "kling-v2-5-turbo-pro"})
    r = a.handle("кот в поварском колпаке, на заднем плане окно", {}, SID)
    assert r["intent"] == "variants"
    assert all("поварском колпаке" in i["text"] for i in blk(r, "variants")["items"])


def test_param_words_in_variants_dont_call_llm(make_assistant):
    tr = FakeTransport(omniroute=[("ok", brief_json()), ("ok", variants_json())])
    a = make_assistant(tr, brief=True)
    a.handle("видео: кот жарит яичницу", {}, SID)
    a.handle("", {}, SID, action={"type": "pick_model", "value": "kling-v2-5-turbo-pro"})
    a.handle("", {}, SID, action={"type": "variants"})
    n = len(tr.calls)
    r = a.handle("вертикально", {}, SID)
    assert len(tr.calls) == n and r["intent"] == "variants" and r["generate_params"]["aspect_ratio"] == "9:16"


def test_detailed_idea_skips_questions(make_assistant):
    a = make_assistant(llm=False, brief=True)
    a.handle("видео: рыжий кот в поварском колпаке жарит яичницу на чугунной сковороде на уютной кухне "
             "утренний свет пар поднимается камера медленно приближается", {}, SID)
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "kling-v2-5-turbo-pro"})
    assert r["intent"] == "variants"


# ---------------- бриф с LLM: вопросы под идею и 3 варианта
def test_llm_tailored_questions_and_variants(make_assistant):
    tr = FakeTransport(omniroute=[("ok", brief_json()), ("ok", variants_json())])
    a = make_assistant(tr, brief=True)
    a.handle("видео: кодта жарит иишницу", {}, SID)
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "kling-v2-5-turbo-pro"})
    assert r["intent"] == "brief" and "Поняла так: кот-повар готовит завтрак" in r["text"]
    qs = blk(r, "brief")["questions"]
    assert qs[0]["label"] == "Какой кот" and qs[0]["options"][0]["label"] == "Рыжий в колпаке"
    sent = json.loads(tr.calls[0]["payload"]["messages"][1]["content"])
    assert sent["idea"] == "видео: кодта жарит иишницу" and sent["kind"] == "video"

    a.handle("", {}, SID, action={"type": "brief", "value": {"id": "cat", "value": "Рыжий в колпаке"}})
    r = a.handle("", {}, SID, action={"type": "variants"})
    items = blk(r, "variants")["items"]
    assert len(items) == 3 and items[0]["title"] == "Вариант A0" and not r["degraded"]
    sent = json.loads(tr.calls[1]["payload"]["messages"][1]["content"])
    assert sent["answers"] == {"Какой кот": "Рыжий в колпаке"}       # ответ ушёл в LLM человеческим текстом
    assert r["llm"]["used"] and tr.calls[1]["payload"]["max_tokens"] >= 900


def test_llm_says_unclear_asks_subject(make_assistant):
    tr = FakeTransport(omniroute=[("ok", brief_json(clear=False, qs=[])), ("ok", brief_json())])
    a = make_assistant(tr, brief=True)
    a.handle("видео кракозябра", {}, SID)
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "kling-v2-5-turbo-pro"})
    assert r["intent"] == "need_subject" and "Не совсем поняла" in r["text"]
    r = a.handle("рыжий кот жарит яичницу", {}, SID)                # после ответа — снова к модели
    assert r["intent"] == "brief" or r["intent"] == "variants"


def test_variants_free_text_is_change_for_llm(make_assistant):
    tr = FakeTransport(omniroute=[("ok", brief_json()), ("ok", variants_json(tag="A")), ("ok", variants_json(tag="B"))])
    a = make_assistant(tr, brief=True)
    a.handle("видео: кот жарит яичницу", {}, SID)
    a.handle("", {}, SID, action={"type": "pick_model", "value": "kling-v2-5-turbo-pro"})
    a.handle("", {}, SID, action={"type": "variants"})
    r = a.handle("сделай смешнее, пусть яйцо подпрыгивает", {}, SID)
    sent = json.loads(tr.calls[2]["payload"]["messages"][1]["content"])
    assert sent["change"] == "сделай смешнее, пусть яйцо подпрыгивает"
    assert blk(r, "variants")["items"][0]["title"] == "Вариант B0"


def test_llm_variants_fail_falls_back_to_rules(make_assistant):
    tr = FakeTransport(omniroute=[("ok", brief_json()), ("http", 503)], groq=[("http", 503)])
    a = make_assistant(tr, brief=True)
    a.handle("видео: кот жарит яичницу", {}, SID)
    a.handle("", {}, SID, action={"type": "pick_model", "value": "kling-v2-5-turbo-pro"})
    a.handle("", {}, SID, action={"type": "brief", "value": {"id": "place", "value": "Кафе"}})
    r = a.handle("", {}, SID, action={"type": "variants"})
    items = blk(r, "variants")["items"]
    assert r["degraded"] and len(items) >= 2 and all("Кафе" in i["text"] for i in items)


def test_brief_answer_must_be_one_of_options(make_assistant):
    a = make_assistant(llm=False, brief=True)
    a.handle("видео: кот", {}, SID)
    a.handle("", {}, SID, action={"type": "pick_model", "value": "kling-v2-5-turbo-pro"})
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
    a.handle("видео кот", {}, SID)
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "kling-v2-5-turbo-pro"})
    open_qs = [q["label"] for q in blk(r, "brief")["questions"] if q.get("open")]
    assert open_qs[:3] == ["Кто в кадре?", "Где это происходит?", "Что происходит — какое действие?"]
    r = a.handle("рыжий кот на кухне жарит яичницу, утро, тёплый свет", {}, SID)   # ответ одним сообщением
    assert r["intent"] == "variants"
    assert all("рыжий кот на кухне" in i["text"].lower() for i in blk(r, "variants")["items"])


def test_llm_open_questions_have_no_options():
    d = BR.validate_brief({"clear": True, "summary": "кот", "questions": [
        {"id": "mood", "label": "Атмосфера?", "options": ["Уютная", "Смешная"]},
        {"id": "who", "label": "Какой кот?", "options": []},
        {"id": "where", "label": "Где?", "options": ["одна"]}]})
    assert [q["id"] for q in d["questions"]] == ["who", "where", "mood"]     # сначала открытые
    assert d["questions"][1]["options"] == []
