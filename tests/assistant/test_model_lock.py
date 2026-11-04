"""Правило «выбранная модель главнее»: текстовая модель отвечает сама, генеративная ведёт задачу без списка моделей.

Модульные тесты с заглушкой ядра. Интеграционные (с настоящим Assistant) — в конце файла, через фикстуру make_assistant
из tests/assistant/conftest.py; без неё пропускаются.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from assistant import model_lock as ML


@dataclass
class Card:
    id: str
    kind: str
    title: str


@dataclass
class Deps:
    cards: dict
    catalog_fn: Any = None


@dataclass
class FakeEngine:
    d: Deps
    picks: list = field(default_factory=list)
    messages: list = field(default_factory=list)

    def _pick(self, mid, ctx, ses, lang, intent="pick_model"):
        self.picks.append((mid, ses.get("idea"), intent))
        return {"text": f"setup {mid}", "reply": "", "chips": [], "blocks": [{"type": "summary"}], "intent": intent}

    def _message(self, msg, ctx, ses, lang):
        self.messages.append((msg, dict(ctx)))
        return {"text": "обычный процесс", "reply": "", "chips": [], "blocks": [], "intent": "generate_task"}


CARDS = {"deepseek-v3": Card("deepseek-v3", "text", "DeepSeek"), "kling-3": Card("kling-3", "video", "Kling 3.0"),
         "gpt-image-2": Card("gpt-image-2", "image", "GPT Image 2")}


def eng():
    return FakeEngine(Deps(cards=CARDS))


def ctx(mid, locked=True):
    return {"selected_model_id": mid, "selected_model_kind": CARDS[mid].kind, "model_locked": locked}


# ---------------------------------------------------------------- распознавание «сделать», а не «написать»
@pytest.mark.parametrize("msg,kind", [
    ("сгенерируй видео про кота", "video"),
    ("сгенери видео по этому сценарию", "video"),
    ("сделай картинку для маркетплейса", "image"),
    ("нарисуй логотип кофейни", "image"),
    ("оживи это фото", "video"),
    ("напиши промпт для видео про кота", None),
    ("сделай промпт для видео", None),
    ("придумай сценарий рилса", None),
    ("как снять видео на телефон", None),
    ("объясни квантовую физику", None),
    ("сделай текст поста про кофе", None),
])
def test_asked_kind(msg, kind):
    assert ML.asked_kind(msg) == kind


# ---------------------------------------------------------------- текстовая модель
def test_text_model_answers_itself_even_if_video_words():
    """Баг: выбран DeepSeek, а помощник запускал поток видео. Теперь сообщение уходит в DeepSeek."""
    a, ses = eng(), {}
    out = ML.before_message(a, "напиши промпт для видео про женщину в толпе", ctx("deepseek-v3"), ses, "ru")
    assert out["silent"] and out["route"] == {"to": "text_model", "model_id": "deepseek-v3",
                                             "text": "напиши промпт для видео про женщину в толпе"}
    assert not a.picks and not a.messages


def test_text_model_plain_question():
    out = ML.before_message(eng(), "объясни разницу между reels и shorts", ctx("deepseek-v3"), {}, "ru")
    assert out["route"]["to"] == "text_model"


def test_text_model_explicit_generation_asks_and_defaults_to_model():
    a, ses = eng(), {}
    out = ML.before_message(a, "сгенерируй видео по этому промпту", ctx("deepseek-v3"), ses, "ru")
    assert out["intent"] == "lock_ask" and "DeepSeek" in out["text"]
    assert out["chips"][0]["action"] == "lock_keep" and out["chips"][0].get("primary")
    keep = ML.action(a, "lock_keep", None, ctx("deepseek-v3"), dict(ses), "ru")
    assert keep["route"]["to"] == "text_model" and keep["route"]["text"] == "сгенерируй видео по этому промпту"


def test_switch_from_text_model_to_generation():
    a, ses = eng(), {}
    ML.before_message(a, "сгенерируй видео по этому промпту", ctx("deepseek-v3"), ses, "ru")
    out = ML.action(a, "lock_switch", "video", ctx("deepseek-v3"), ses, "ru")
    assert out["ui_do"] == {"action": "unlock_model", "value": None}
    assert a.messages and a.messages[0][1]["model_locked"] is False
    # дальше эта же модель не перехватывает, пока человек сам не выберет модель заново
    assert ML.before_message(a, "ещё одно видео", ctx("deepseek-v3"), ses, "ru") is None


# ---------------------------------------------------------------- генеративная модель
def test_generative_model_goes_straight_to_its_setup():
    """Видеомодель уже выбрана: первое сообщение не прыгает в настройки — промпт как в обычном процессе."""
    a, ses = eng(), {}
    out = ML.before_message(a, "рилс про кофейню утром", ctx("kling-3"), ses, "ru")
    assert out is None and a.picks == []
    assert ses["lock"] == "kling-3"
    ready = {"prompt": "Утро в кофейне, пар от чашки.", "idea": "кофейня"}
    card = ML.parameters_if_locked(a, ctx("kling-3"), ready, "ru", "video")
    assert a.picks == [("kling-3", "Утро в кофейне, пар от чашки.", "locked_model")]
    assert card["blocks"]


def test_generative_model_same_task_continues_normally():
    a, ses = eng(), {}
    ML.before_message(a, "рилс про кофейню", ctx("kling-3"), ses, "ru")
    assert ML.before_message(a, "сделай вечером", ctx("kling-3"), ses, "ru") is None   # правка — обычные шаги


def test_image_lock_waits_for_the_prompt():
    a, ses = eng(), {}
    out = ML.before_message(a, "нарисуй рыжего кота на крыше", ctx("gpt-image-2"), ses, "ru")
    assert out is None and a.picks == []
    assert ses["lock"] == "gpt-image-2"


def test_locked_image_opens_parameters_not_the_list():
    a, ses = eng(), {"prompt": "Рыжий кот на крыше", "idea": "кот"}
    out = ML.parameters_if_locked(a, ctx("gpt-image-2"), ses, "ru", "image")
    assert a.picks == [("gpt-image-2", "Рыжий кот на крыше", "locked_model")]
    assert out["blocks"]
    assert ML.parameters_if_locked(a, ctx("gpt-image-2"), {}, "ru", "image") is None


def test_generative_model_other_kind_asks():
    a, ses = eng(), {}
    out = ML.before_message(a, "сделай видео из этой картинки", ctx("gpt-image-2"), ses, "ru")
    assert out["intent"] == "lock_ask" and "GPT Image 2" in out["text"]
    keep = ML.action(a, "lock_keep", None, ctx("gpt-image-2"), ses, "ru")
    assert a.picks[-1][0] == "gpt-image-2" and keep["blocks"]


def test_not_locked_is_normal_flow():
    a = eng()
    assert ML.before_message(a, "сгенерируй видео", ctx("kling-3", locked=False), {}, "ru") is None


def test_unknown_or_hidden_model_is_normal_flow():
    a = eng()
    assert ML.before_message(a, "привет", {"selected_model_id": "nope", "model_locked": True}, {}, "ru") is None
    a.d.catalog_fn = lambda mid: mid != "kling-3"
    assert ML.before_message(a, "рилс", ctx("kling-3"), {}, "ru") is None


# ---------------------------------------------------------------- с настоящим ядром (в репозитории)
def test_real_engine_text_model_route(request):
    try:
        make_assistant = request.getfixturevalue("make_assistant")
    except pytest.FixtureLookupError:
        pytest.skip("нет фикстуры make_assistant — запускается в tests/assistant репозитория")
    a = make_assistant()
    text_ids = [c.id for c in a.d.cards.values() if c.kind == "text"]
    if not text_ids:
        pytest.skip("нет текстовых моделей в карточках")
    r = a.handle("напиши промпт для видео про кота", {"selected_model_id": text_ids[0], "model_locked": True}, "ml1")
    assert r.get("route", {}).get("to") == "text_model" and r.get("silent")
    assert not any(b.get("type") == "models" for b in r.get("blocks") or [])
