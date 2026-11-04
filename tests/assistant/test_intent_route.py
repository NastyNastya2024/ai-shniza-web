"""Intent router: неясный запрос спрашивает, а не собирает визуальный промпт."""
import json

from assistant import intent_route as IR
from assistant_testkit import FakeTransport


CASES = [
    ("фото кофейной чашки на столе", "image"),
    ("нужен баннер для сайта", "image"),
    ("сделай рилс про кофейню", "video"),
    ("видео с дроном над горами", "video"),
    ("напиши продающий пост", "text"),
    ("слоган для бренда", "text"),
    ("постер к фестивалю", "image"),
    ("пост с картинкой про коллекцию", "mixed"),
    ("маркетинговые материалы", "unclear"),
    ("креативы для рекламы", "unclear"),
    ("какая погода завтра", "out_of_scope"),
]


def test_keywords_match_the_router_table():
    for text, kind in CASES:
        assert IR.classify_by_keywords(text)["type"] == kind


def test_garbage_json_falls_back_to_keywords():
    decision = IR.route_request("видео про кофе", lambda _s, _u: "не JSON")
    assert decision["action"] == "build_prompt" and decision["template"] == "video"
    assert decision["intent"]["source"] == "keywords"


def test_named_format_skips_the_menu_and_builds_that_prompt():
    from assistant.formats import build, match_sub
    assert match_sub("нужна обложка для ролика") == "cover"
    text = build("cover", "нужна обложка для ролика")
    assert "Текст на обложке" in text and "1080×1920" in text
    assert "нужна обложка для ролика" in text


def test_low_confidence_asks():
    decision = IR.decide({
        "type": "image", "confidence": 0.5, "summary": "", "critical_missing": [],
        "nice_to_have": [], "clarify_question": None, "options": [], "source": "llm",
    })
    assert decision["action"] == "clarify"


def test_unclear_request_uses_categories_not_model_buttons(make_assistant):
    reply = json.dumps({
        "type": "unclear", "confidence": 0.3, "summary": "формат не указан",
        "critical_missing": [], "nice_to_have": [],
        "clarify_question": "Какие материалы нужны?",
        "options": ["Тексты", "Баннер", "Видео"],
    })
    a = make_assistant(transport=FakeTransport(omniroute=[("ok", reply)]), understand_llm=True, dialog_v2=True)
    d = a.handle("мне нужны маркетинговые материалы", {}, "mkt-llm")
    assert d["intent"] == "intent_clarify"
    assert [c["label"] for c in d["chips"]][0] == "Изображения"
    assert "Комбинация" not in [c["label"] for c in d["chips"]]
