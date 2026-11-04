"""Переход между текстовой моделью и генерацией одной командой в чате."""
from __future__ import annotations

from assistant.switch import generation_kind, is_refusal, is_write_request, prompt_candidates


def _models(r):
    return [m for m in (r.get("models") or []) if m.get("id")]


def test_rewrite_goes_to_text_not_video_or_image(make_assistant):
    a = make_assistant(llm=False, dialog_v2=True)
    a.handle("", {}, "rw", action={"type": "restart"})
    r = a.handle(
        "перепиши без ошибок короче Я ходила на свидания и мне было некомфортно с ними",
        {"lang": "ru"}, "rw",
    )
    assert "видео или картинка" not in (r.get("text") or "")
    assert str(r.get("text_ask") or "").startswith("перепиши")
    assert r.get("generate_model")


def test_panel_pick_keeps_the_chosen_model(make_assistant):
    a = make_assistant(llm=False, dialog_v2=True)
    r = a.handle("нужно озвучить текст Привет", {
        "model_locked": True,
        "selected_model_id": "elevenlabs-v3",
        "selected_model_kind": "music",
        "lang": "ru",
    }, "lock-el")
    assert r.get("intent") == "voice_form"
    assert "Claude" not in (r.get("text") or "")
    assert "Озвучка" in (r.get("text") or "")


def test_write_stays_text_generate_switches():
    from assistant.brief import look_ask
    assert generation_kind(look_ask("ru", "оживи фото", "video"), True) is None
    assert generation_kind("напиши промпт для видео про кофе") is None
    assert generation_kind(
        "Доработай этот промпт для генерации: сохрани смысл. Верни только улучшенный промпт.\n\nОживи загруженное фото."
    ) is None
    assert is_write_request("напиши промпт для видео про кофе")
    assert generation_kind("как снять видео про кофе") is None
    assert generation_kind("хорошо теперь сгенери видео по этому") == "video"
    assert generation_kind("сделай картинку по этому") == "image"
    assert generation_kind("озвучь по этому") == "voice"
    assert is_refusal("Я не могу сгенерировать видео, используйте Sora")


def test_switch_uses_prompt_block_and_offers_video_models(make_assistant):
    a = make_assistant(llm=False, brief=True)
    reply = "Вот текст.\n```prompt\nЖенщина 35 лет идёт сквозь толпу\n```\nПодойдёт?"
    r = a.handle("", {}, "sw1", action={"type": "model_switch", "value": {
        "text": "хорошо теперь сгенери видео по этому",
        "kind": "video",
        "from_name": "Claude Sonnet 5",
        "from_id": "claude-sonnet-5",
        "replies": [reply],
    }})
    assert r["intent"] == "model_switch"
    assert 2 <= len(_models(r)) <= 3
    assert any(c.get("action") == "stay_text" and "этому" in (c.get("value") or {}).get("text", "") for c in r["chips"])
    assert "midjourney" not in r["text"].lower() and "sora" not in r["text"].lower()
    shown = " ".join(b.get("text") or "" for b in r.get("blocks") or [] if b.get("type") == "prompt")
    assert "Женщина 35 лет" in shown
    mid = _models(r)[0]["id"]
    r2 = a.handle("", {}, "sw1", action={"type": "pick_model", "value": mid})
    assert r2.get("switch_line", "").startswith("Claude Sonnet 5 →")
    summary = next(b for b in r2["blocks"] if b.get("type") == "summary")
    assert summary.get("editable") is True
    assert "Женщина 35 лет" in summary["prompt"]


def test_two_prompts_asks_which(make_assistant):
    a = make_assistant(llm=False, brief=True)
    r = a.handle("", {}, "sw2", action={"type": "model_switch", "value": {
        "text": "сделай видео по этому",
        "kind": "video",
        "from_name": "Claude Sonnet 5",
        "from_id": "claude-sonnet-5",
        "replies": [
            "```prompt\nЖенщина 35 лет идёт\n```",
            "```prompt\nВариант с толпой на площади\n```",
        ],
    }})
    assert r["intent"] == "switch_which"
    picks = [c for c in r["chips"] if c.get("action") == "switch_pick"]
    assert len(picks) == 2
    r2 = a.handle("", {}, "sw2", action={"type": "switch_pick", "value": 1})
    assert r2["intent"] == "model_switch"
    shown = " ".join(b.get("text") or "" for b in r2.get("blocks") or [] if b.get("type") == "prompt")
    assert "толпой" in shown


def test_prompt_candidates_prefer_fence():
    text = "Коротко.\n```prompt\nЖенщина идёт\n```\nНужно ещё?"
    assert prompt_candidates([text]) == ["Женщина идёт"]


def test_after_video_a_caption_offers_text_model(make_assistant):
    a = make_assistant(llm=False, brief=True)
    a.handle("сделай видео кот на крыше ночью", {"_account": {"authed": True, "available_kop": 10 ** 7}}, "sw3")
    r = a.handle("напиши к этому видео подпись для поста", {"_account": {"authed": True, "available_kop": 10 ** 7}}, "sw3")
    assert r["intent"] == "switch_text"
    assert _models(r)
    r2 = a.handle("", {"_account": {"authed": True, "available_kop": 10 ** 7}}, "sw3",
                  action={"type": "pick_model", "value": _models(r)[0]["id"]})
    assert "подпись" in (r2.get("text_ask") or "")


def test_stored_text_is_found_by_po_etomu(make_assistant):
    a = make_assistant(llm=False, brief=True)
    a.handle("", {}, "sw4", action={"type": "text_note", "value": {
        "model": "claude-sonnet-5", "name": "Claude Sonnet 5",
        "text": "```prompt\nПодпись: женщина в толпе молчит\n```",
    }})
    r = a.handle("сделай видео по этому", {}, "sw4")
    assert r["intent"] == "model_switch"
    shown = " ".join(b.get("text") or "" for b in r.get("blocks") or [] if b.get("type") == "prompt")
    assert "женщина в толпе" in shown


def test_expand_instruction_is_stripped_from_the_prompt():
    from assistant.engine import unwrap_polish
    from assistant.switch import generation_kind
    raw = (
        "Разверни этот промпт для генерации до максимально подробного текста. "
        "Верни только улучшенный промпт.\n\n"
        "Оживи загруженное фото. Человек остаётся как на снимке."
    )
    assert generation_kind(raw) is None
    assert unwrap_polish(raw) == "Оживи загруженное фото. Человек остаётся как на снимке."


def test_polish_instruction_is_stripped_from_the_prompt():
    from assistant.engine import unwrap_polish
    raw = (
        "Доработай этот промпт для генерации: сохрани смысл и движение камеры, сделай ярче и конкретнее. "
        "Верни только улучшенный промпт.\n\n"
        "Доработай этот промпт для генерации: сохрани смысл и движение камеры, сделай ярче и конкретнее. "
        "Верни только улучшенный промпт.\n\n"
        "Оживи загруженное фото. Человек остаётся как на снимке."
    )
    assert unwrap_polish(raw) == "Оживи загруженное фото. Человек остаётся как на снимке."
