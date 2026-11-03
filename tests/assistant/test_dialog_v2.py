"""Диалог v2: идея раньше моделей, без стартового меню и без «собрать промпт?»."""
import json

from assistant.dialog_flow import capabilities
from assistant.session import MemoryStore


def _a(make_assistant, store=None):
    a = make_assistant(llm=False, dialog_v2=True)
    if store is not None:
        a.d.store = store
    return a


def test_no_start_menu(make_assistant):
    d = _a(make_assistant).handle("привет", session_id="hi")
    labels = " ".join(c.get("label") or "" for c in d.get("chips") or [])
    assert "Раскадровка" not in labels and "Озвучка" not in labels
    assert not any(c.get("action") == "pipe_stage" for c in d.get("chips") or [])
    assert "Опишите" in d["text"] or "Здравствуйте" in d["text"]


def test_marketplace_asks_product_before_models(make_assistant):
    d = _a(make_assistant).handle("мне нужно сделать карточку для маркетплейса", session_id="m1")
    assert d["intent"] == "flow_slots"
    assert d["dialog"]["story"] == "COM.CARD"
    assert not any(b.get("type") == "models" for b in d.get("blocks") or [])
    assert "Собрать или улучшить" not in d["text"]
    assert "одним сообщением" not in d["text"]
    assert d["text"].count("?") <= 2


def test_marketplace_known_slots_go_to_idea_then_models(make_assistant):
    a = _a(make_assistant)
    d = a.handle("вб, инфографика, кроссовки, белый фон", session_id="m2")
    assert d["intent"] == "variants"
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    assert len(items) >= 2
    assert not any(b.get("type") == "models" for b in d["blocks"])
    d = a.handle("", session_id="m2", action={"type": "use_variant", "value": items[0]["id"]})
    assert d["intent"] == "use_variant"
    assert {m["id"] for m in d["models"]} & {"claude-sonnet-5", "gpt-5-4"}
    d = a.handle("", session_id="m2", action={"type": "skip_polish"})
    assert d["intent"] == "advise"
    items = next(b["items"] for b in d["blocks"] if b["type"] == "models")
    assert items[0].get("badge") == "Советую"
    assert len(items) <= 3
    assert "Промпт под" not in d["text"]
    d = a.handle("", session_id="m2", action={"type": "pick_model", "value": items[0]["id"]})
    assert d["generate_model"] == items[0]["id"]
    assert "кроссов" in (d.get("generate_prompt") or "").lower()
    assert d["dialog"]["stage"] == "card"
    assert any(b.get("type") == "summary" for b in d["blocks"])
    caps = capabilities()
    assert all((caps.get(it["id"]) or {}).get("text_render", 0) >= 2 for it in items)
    assert "3:4" in str(d["blocks"])


def test_reels_path_then_direct_and_skip(make_assistant):
    a = _a(make_assistant)
    d = a.handle("хочу сделать рилс который залетит про кофейню", session_id="r1")
    assert d["intent"] == "flow_slots"
    assert not any(b.get("type") == "models" for b in d.get("blocks") or [])
    d = a.handle("", session_id="r1", action={"type": "flow_slot", "value": {"slot": "own", "value": "no"}})
    assert d["intent"] == "variants"
    d = a.handle("", session_id="r1", action={"type": "idea_next"})
    actions = {c["action"] for c in d["chips"]}
    assert {"path_photos", "path_board", "path_direct"} <= actions
    assert "Сначала фото" in d["text"] and "Раскадровка" in d["text"] and "Сразу видео" in d["text"]
    d = a.handle("давай сразу видео", session_id="r2")
    # новая фраза без слотов ещё спросит цель; пропуск пути — после идеи
    a.handle("хочу сделать рилс который залетит про кофейню", session_id="r3")
    a.handle("", session_id="r3", action={"type": "flow_slot", "value": {"slot": "own", "value": "no"}})
    d = a.handle("давай сразу видео", session_id="r3")
    assert d["intent"] == "advise"
    assert any(b.get("type") == "models" for b in d["blocks"])
    assert "15" in d["text"]


def test_video_refines_prompt_before_each_path(make_assistant):
    a = _a(make_assistant)
    d = a.handle("хочу сделать рилс который залетит про кофейню", session_id="pr")
    assert d["intent"] == "flow_slots"
    d = a.handle("", session_id="pr", action={"type": "flow_slot", "value": {"slot": "own", "value": "no"}})
    assert d["intent"] == "variants"
    assert "промпт" in d["text"].lower()
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    d = a.handle("", session_id="pr", action={"type": "use_variant", "value": items[0]["id"]})
    assert {m["id"] for m in d["models"]} & {"claude-sonnet-5", "gpt-5-4"}
    d = a.handle("", session_id="pr", action={"type": "skip_polish"})
    assert d["intent"] == "flow_path"
    d = a.handle("", session_id="pr", action={"type": "path_photos"})
    assert d["intent"] == "variants"
    assert not any(b.get("type") == "models" for b in d.get("blocks") or [])
    photo = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    a.handle("", session_id="pr", action={"type": "use_variant", "value": photo[0]["id"]})
    d = a.handle("", session_id="pr", action={"type": "skip_polish"})
    assert d["intent"] == "advise"
    d = a.handle("хочу сделать рилс который залетит про кофейню", session_id="bd")
    a.handle("", session_id="bd", action={"type": "flow_slot", "value": {"slot": "own", "value": "no"}})
    a.handle("", session_id="bd", action={"type": "idea_next"})
    d = a.handle("", session_id="bd", action={"type": "path_board"})
    assert d["intent"] == "variants"
    board = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    a.handle("", session_id="bd", action={"type": "use_variant", "value": board[0]["id"]})
    d = a.handle("", session_id="bd", action={"type": "skip_polish"})
    assert d["intent"] in ("sb_frames", "sb_intro")


def test_reels_photos_then_storyboard_hint(make_assistant):
    a = _a(make_assistant)
    a.handle("хочу сделать рилс который залетит про кофейню", session_id="ph")
    a.handle("", session_id="ph", action={"type": "flow_slot", "value": {"slot": "own", "value": "no"}})
    a.handle("", session_id="ph", action={"type": "idea_next"})
    d = a.handle("", session_id="ph", action={"type": "path_photos"})
    assert d["intent"] == "variants"
    photo = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    a.handle("", session_id="ph", action={"type": "use_variant", "value": photo[0]["id"]})
    d = a.handle("", session_id="ph", action={"type": "skip_polish"})
    assert d["intent"] == "advise"
    assert d["models"][0].get("id")
    assert any(it.get("badge") == "Советую" for b in d["blocks"] if b["type"] == "models" for it in b["items"])
    d = a.handle("", session_id="ph", action={"type": "media_add", "value": {"kind": "image", "url": "/w/1", "name": "hero.png"}})
    labels = " ".join(c.get("label") or "" for c in d["chips"])
    assert "раскадровка" in labels and "видео из этой картинки" in labels


def test_advice_repeat_and_compare(make_assistant):
    a = _a(make_assistant)
    a.handle("вб, инфографика, кружка, белый фон", session_id="c1")
    first = a.handle("", session_id="c1", action={"type": "idea_next"})
    again = a.handle("а какой посоветуешь", session_id="c1")
    assert again["intent"] == "advise"
    assert not any(b.get("type") == "models" for b in again.get("blocks") or [])
    assert first["models"][0]["title"] in again["text"]
    d = a.handle("чем отличается Seedance 2.5 от Kling 3.0", session_id="c2")
    assert d["intent"] == "compare"
    assert "Чем отличаются" in d["text"]
    assert not any(b.get("type") == "models" for b in d.get("blocks") or [])


def test_summary_edit_and_memory(make_assistant):
    store = MemoryStore()
    a = _a(make_assistant, store)
    b = _a(make_assistant, store)
    a.handle("хочу сделать рилс который залетит про кофейню", session_id="mem")
    a.handle("", session_id="mem", action={"type": "flow_slot", "value": {"slot": "own", "value": "no"}})
    d = a.handle("а теперь ночью", session_id="mem")
    blob = d["text"] + " ".join(
        (bl.get("text") or "") + " ".join(it.get("text") or "" for it in bl.get("items") or [])
        for bl in d.get("blocks") or [])
    assert "Ноч" in blob
    d = b.handle("", session_id="mem", action={"type": "flow_show"})
    blob = d["text"] + " ".join(
        (bl.get("text") or "") + " ".join(it.get("text") or "" for it in bl.get("items") or [])
        for bl in d.get("blocks") or [])
    assert "Ноч" in blob
    assert d["dialog"]["task"] == "video"
    a.handle("", session_id="mem", action={"type": "idea_next"})
    d = a.handle("", session_id="mem", action={"type": "path_direct"})
    mid = d["models"][0]["id"]
    d = a.handle("", session_id="mem", action={"type": "pick_model", "value": mid})
    d = a.handle("", session_id="mem", action={"type": "edit_prompt", "value": {"text": "Ночная кофейня, неон, 9:16"}})
    assert "неон" in (d.get("generate_prompt") or "")


def test_capabilities_keep_unknown_null():
    caps = capabilities()
    assert caps
    assert any(row.get("realism") is None for row in caps.values())
    assert any(row.get("text_render") is None for row in caps.values())
    strong = [i for i, row in caps.items() if isinstance(row.get("text_render"), int) and row["text_render"] >= 2]
    assert "ideogram-v3-turbo" in strong
    assert "seedream-5-pro" in strong


def test_claude_handoff_shows_idea_before_models(make_assistant):
    a = _a(make_assistant)
    reply = "Вот текст.\n```prompt\nЖенщина 35 лет идёт сквозь толпу\n```\nПодойдёт?"
    r = a.handle("", {}, "sw", action={"type": "model_switch", "value": {
        "text": "хорошо теперь сгенери видео по этому",
        "kind": "video",
        "from_name": "Claude Sonnet 5",
        "from_id": "claude-sonnet-5",
        "replies": [reply],
    }})
    assert r["intent"] == "model_switch"
    assert not r.get("models")
    shown = " ".join(it.get("text") or "" for b in r.get("blocks") or [] if b.get("type") == "variants" for it in b.get("items") or [])
    assert "Женщина 35 лет" in shown
    assert any(c.get("action") == "stay_text" for c in r["chips"])
    r = a.handle("", {}, "sw", action={"type": "idea_next"})
    assert r["intent"] == "flow_path"
    r = a.handle("", {}, "sw", action={"type": "path_direct"})
    assert r["intent"] == "advise" and r["models"]


def test_status_names_dialog(make_assistant):
    from assistant.flask_adapter import status
    d = status(_a(make_assistant))
    assert d["dialog_manager"] == "on"
    assert isinstance(d["build"], str) and d["build"]
    assert "session_store" in d
