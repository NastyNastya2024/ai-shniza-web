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
    assert any(it.get("badge") == "Советую" for it in items)
    assert len(items) >= 3
    from assistant.recommend import price_value
    prices = [price_value(it.get("price")) if price_value(it.get("price")) is not None else 1e9 for it in items]
    assert prices == sorted(prices)
    assert "Промпт под" not in d["text"]
    d = a.handle("", session_id="m2", action={"type": "pick_model", "value": items[0]["id"]})
    assert d["generate_model"] == items[0]["id"]
    assert "кроссов" in (d.get("generate_prompt") or "").lower()
    assert d["dialog"]["stage"] == "card"
    assert any(b.get("type") == "summary" for b in d["blocks"])
    caps = capabilities()
    assert all((caps.get(it["id"]) or {}).get("text_render", 0) >= 2 for it in items)
    assert "3:4" in str(d["blocks"])


def test_initial_variant_can_be_extended(make_assistant):
    a = _a(make_assistant)
    d = a.handle("вб, инфографика, кроссовки, белый фон", session_id="add1")
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    assert "Настроение." in items[0]["text"] and "Стиль." in items[0]["text"] and "Камера." in items[0]["text"]
    extra = items[0]["text"] + "\nБлик на носке кроссовка."
    a.handle("", session_id="add1", action={"type": "use_variant", "value": items[0]["id"], "prompt": extra})
    assert "Блик на носке" in (a.d.store.get("add1").get("prompt") or "")
    assert "кроссов" in (a.d.store.get("add1").get("prompt") or "").lower()


def test_photo_grid_asks_opus_then_keeps_the_actions(make_assistant):
    a = _a(make_assistant)
    uid = "upl_" + "ab" * 12
    ctx = {"has_image": True, "attachments": [{"id": uid, "kind": "image", "name": "camp.jpg"}]}
    d = a.handle("оживи фото", ctx, "look1")
    assert d["intent"] == "look_photo"
    assert d["text"].strip() == "Формирую промпт через Claude, около 20 секунд — нейросеть дорабатывает детали."
    labels = [c.get("label") for c in d.get("chips") or []]
    assert labels[:2] == ["Быстрый промпт", "Оставить свой промпт"]
    assert not any(c.get("primary") for c in d.get("chips") or [])
    assert not any("Вернуться" in (c.get("label") or "") for c in d.get("chips") or [])
    assert d["generate_model"] == "claude-opus-4-7"
    assert "прикреплённое фото" in d["text_ask"]
    assert "Разверни" not in (a.d.store.get("look1").get("idea") or "")
    reply = json.dumps({"variants": [
        {"title": "Поворот головы", "prompt": "Кадр — загруженное фото: женщина в красном пальто у окна.\nНастроение. Тихое.\nСтиль. Кино.\nКамера. Крупный план.\nСвет. Мягкий.\nДвижение. Медленно поворачивает голову к окну."},
        {"title": "Шаг вперёд", "prompt": "Кадр — загруженное фото: женщина в красном пальто у окна.\nНастроение. Спокойное.\nСтиль. Реализм.\nКамера. Средний план.\nСвет. Дневной.\nДвижение. Делает один шаг вперёд."},
        {"title": "Ветер", "prompt": "Кадр — загруженное фото: женщина в красном пальто у окна.\nНастроение. Живое.\nСтиль. Реализм.\nКамера. Портрет.\nСвет. Боковой.\nДвижение. Ветер поднимает край пальто."},
    ]}, ensure_ascii=False)
    d = a.handle("", {}, "look1", action={"type": "look_done", "value": {"text": reply}})
    assert d["intent"] == "variants"
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    assert [it["title"] for it in items] == ["Поворот головы", "Шаг вперёд", "Ветер"]
    assert "красном пальто" in items[0]["text"] and "поворачивает голову" in items[0]["text"]
    assert "Движение." in items[2]["text"]
    d = a.handle("", {}, "look1", action={"type": "flow_polish"})
    ids = [m["id"] for m in d["models"]]
    assert ids[0] == "claude-opus-4-7"
    notes = {it["id"]: it.get("note") or "" for b in d["blocks"] if b["type"] == "models" for it in b["items"]}
    assert "Видит" in notes["claude-opus-4-7"]
    assert "не уйдёт" in notes["claude-sonnet-5"]


def test_skip_look_keeps_the_current_prompt(make_assistant):
    a = _a(make_assistant)
    uid = "upl_" + "aa" * 12
    ctx = {"has_image": True, "attachments": [{"id": uid, "kind": "image", "name": "camp.jpg"}]}
    d = a.handle("оживи фото, женщина у окна", ctx, "look4")
    assert d["intent"] == "look_photo"
    d = a.handle("", {}, "look4", action={"type": "look_next"})
    assert d["intent"] == "flow_path"
    assert "Сразу видео" in [c.get("label") for c in d.get("chips") or []]
    assert "женщина у окна" in (a.d.store.get("look4").get("prompt") or "")
    assert not any(b.get("type") == "variants" for b in d.get("blocks") or [])


def test_skip_look_makes_a_quick_prompt(make_assistant):
    a = _a(make_assistant)
    uid = "upl_" + "ef" * 12
    ctx = {"has_image": True, "attachments": [{"id": uid, "kind": "image", "name": "camp.jpg"}]}
    d = a.handle("оживи фото", ctx, "look3")
    assert d["intent"] == "look_photo"
    ses = a.d.store.get("look3")
    ses["idea"] = "Посмотри на прикреплённое фото. Опиши только то, что реально видно и верни JSON."
    a.d.store.set("look3", ses)
    d = a.handle("", {}, "look3", action={"type": "look_skip"})
    assert d["intent"] == "variants"
    assert "Быстрый промпт." in d["text"]
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    assert len(items) >= 2
    body = items[0]["text"]
    assert "Посмотри на прикреплённое" not in body and "JSON" not in body
    assert "Кадр." in body and "Настроение." in body and "Движение." in body


def test_unreadable_look_falls_back_to_variants(make_assistant):
    a = _a(make_assistant)
    uid = "upl_" + "cd" * 12
    ctx = {"has_image": True, "attachments": [{"id": uid, "kind": "image", "name": "camp.jpg"}]}
    d = a.handle("оживи фото", ctx, "look2")
    assert d["intent"] == "look_photo"
    d = a.handle("", {}, "look2", action={"type": "look_done", "value": {"text": "не разобрала"}})
    assert d["intent"] == "variants"
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    assert len(items) >= 2


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
    assert "Добавить фото" in d["text"] and "Раскадровка" in d["text"] and "Сразу видео" in d["text"]
    d = a.handle("давай сразу видео", session_id="r2")
    # новая фраза без слотов ещё спросит цель; пропуск пути — после идеи
    a.handle("хочу сделать рилс который залетит про кофейню", session_id="r3")
    a.handle("", session_id="r3", action={"type": "flow_slot", "value": {"slot": "own", "value": "no"}})
    d = a.handle("давай сразу видео", session_id="r3")
    assert d["intent"] == "advise"
    assert any(b.get("type") == "models" for b in d["blocks"])
    assert "5 с" in d["text"]
    ids = [it["id"] for b in d["blocks"] if b.get("type") == "models" for it in b["items"]]
    assert "gemini-omni-flash" in ids and "seedance-2-5" in ids and "veo-3-1" in ids
    if "gen4-turbo" in ids and any(i.startswith("kling") for i in ids):
        g = ids.index("gen4-turbo")
        last_kling = max(i for i, mid in enumerate(ids) if mid.startswith("kling"))
        assert g == last_kling + 1 and g >= 3


def test_photo_does_not_hide_text_only_video(make_assistant):
    a = _a(make_assistant)
    ctx = {"has_image": True, "attachments": [{"id": "upl_" + "ab" * 12, "kind": "image", "name": "camp.jpg"}]}
    a.handle("хочу сделать рилс который залетит про кофейню", ctx, "gomni")
    a.handle("", {}, "gomni", action={"type": "flow_slot", "value": {"slot": "own", "value": "no"}})
    d = a.handle("давай сразу видео", {}, "gomni")
    items = [it for b in d["blocks"] if b.get("type") == "models" for it in b["items"]]
    gem = next(it for it in items if it["id"] == "gemini-omni-flash")
    assert "не уйдёт" in (gem.get("note") or "")
    assert len(items) >= 13


def test_video_refines_prompt_before_each_path(make_assistant):
    a = _a(make_assistant)
    d = a.handle("хочу сделать рилс который залетит про кофейню", session_id="pr")
    assert d["intent"] == "flow_slots"
    d = a.handle("", session_id="pr", action={"type": "flow_slot", "value": {"slot": "own", "value": "no"}})
    assert d["intent"] == "variants"
    assert "промпт" in d["text"].lower()
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    assert any(c.get("action") == "flow_polish" for c in d["chips"])
    d = a.handle("", session_id="pr", action={"type": "use_variant", "value": items[0]["id"]})
    assert d["intent"] == "flow_path"
    assert {"path_photos", "path_board", "path_direct", "flow_polish"} <= {c["action"] for c in d["chips"]}
    d = a.handle("", session_id="pr", action={"type": "flow_polish"})
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
    picked = a.handle("", {}, "sw2", action={"type": "model_switch", "value": {
        "text": "сделай видео по этому",
        "kind": "video",
        "from_name": "Claude Sonnet 5",
        "from_id": "claude-sonnet-5",
        "replies": [reply],
    }})
    vid = next(b["items"] for b in picked["blocks"] if b["type"] == "variants")
    chosen = a.handle("", {}, "sw2", action={"type": "use_variant", "value": vid[0]["id"]})
    assert chosen["intent"] == "advise"
    assert "Промпт основной идеи готов" not in chosen["text"]
    r = a.handle("", {}, "sw", action={"type": "idea_next"})
    assert r["intent"] == "flow_path"
    r = a.handle("", {}, "sw", action={"type": "path_direct"})
    assert r["intent"] == "advise" and r["models"]


def test_new_chat_short_phrase_does_not_open_old_models(make_assistant):
    """После «Новый чат» короткая фраза не должна открывать старую сетку моделей."""
    a = _a(make_assistant)
    a.handle("", {}, "new1", action={"type": "restart"})
    uid = "upl_" + "cd" * 12
    d = a.handle(
        "оживи картинку",
        {"has_image": True, "attachments": [{"id": uid, "kind": "image", "name": "photo.jpg"}]},
        "new1",
    )
    assert d["intent"] == "look_photo"
    assert "Выберите нейросеть" not in d["text"]
    assert not any(b.get("type") == "models" for b in d.get("blocks") or [])


def test_stuck_idea_step_opens_prompts_not_models(make_assistant):
    """Старый чат помнит шаг «опишите идею». Новая фраза не должна снова спрашивать модель первой."""
    from assistant.session import empty_session

    a = _a(make_assistant)
    ses = empty_session()
    ses["await"] = "idea"
    ses["kind"] = "video"
    ses["assist_mode"] = "direct"
    a.d.store.set("old", ses)
    d = a.handle(
        "оживи картинку",
        {"attachments": [{"id": "upl_" + "ab" * 12, "kind": "image", "name": "photo.jpg"}]},
        "old",
    )
    assert d["intent"] == "look_photo"
    assert d["generate_model"] == "claude-opus-4-7"
    assert not any(b.get("type") == "models" for b in d.get("blocks") or [])
    assert "Выберите нейросеть" not in d["text"]


def test_text_reply_next_step_uses_card_actions(make_assistant):
    a = _a(make_assistant)
    a.handle("оживи картинку", session_id="tx")
    d = a.handle("", session_id="tx", action={
        "type": "media_add",
        "value": {"kind": "text", "reply": "Оживи фото. Человек остаётся как на снимке."},
    })
    labels = [c.get("label") for c in d.get("chips") or []]
    assert labels == ["Сделать видео по этому", "Картинку", "Раскадровку"]
    assert "Озвучить" not in labels
    assert "Готово" not in d["text"]
    assert "Ещё слайды инфографики" not in labels
    video = d["chips"][0]["value"]
    assert video["kind"] == "video" and "Человек остаётся" in video["text"]
    again = a.handle("", session_id="tx", action={"type": "make", "value": video})
    assert again["intent"] == "advise"
    assert again.get("models")
    newer = "Второй промпт. Ветер треплет волосы, замедление на пике порыва."
    third = a.handle("", session_id="tx", action={"type": "make", "value": {"kind": "video", "text": newer}})
    assert third["intent"] == "advise" and third.get("models")


def test_finished_video_offers_redo_and_continuation(make_assistant):
    store = MemoryStore()
    a = _a(make_assistant, store)
    a.handle("оживи картинку, женщина у окна", session_id="vid")
    d = a.handle("", session_id="vid", action={"type": "media_add", "value": {"kind": "video", "url": "/w/9", "name": "clip.mp4"}})
    labels = [c.get("label") for c in d.get("chips") or []]
    assert labels[:3] == ["Переделать", "Сделать продолжение", "Новая генерация"]
    assert "Обложка" not in labels
    redone = a.handle("", session_id="vid", action={"type": "flow_next", "value": "redo"})
    assert redone["intent"] == "idea"
    block = next(b for b in redone.get("blocks") or [] if b.get("type") == "prompt")
    assert block.get("extend") is True
    assert "женщина у окна" in block.get("text", "")
    assert any(c.get("action") == "flow_polish" for c in redone.get("chips") or [])
    cont = a.handle("", session_id="vid", action={"type": "flow_next", "value": "continue"})
    assert cont["intent"] == "variants"
    assert "Продолжение" in (cont.get("text") or "")
    assert any(c.get("action") == "flow_polish" for c in cont.get("chips") or [])
    photo = {"has_image": True, "attachments": [{"id": "upl_" + "ab" * 12, "kind": "image", "name": "photo.jpg"}]}
    again = a.handle("", photo, "vid", action={"type": "flow_next", "value": "continue"})
    assert again["intent"] == "variants"
    assert "Формирую промпт" not in (again.get("text") or "")
    labels = [c.get("label") for c in again.get("chips") or []]
    assert "Доработать в Claude или GPT" in labels and "Ещё варианты" in labels and "Назад" in labels
    cards = next(b["items"] for b in again["blocks"] if b["type"] == "variants")
    assert len(cards) >= 2
    items = next(b["items"] for b in cont["blocks"] if b["type"] == "variants")
    assert any("Продолжение предыдущего ролика" in i.get("text", "") for i in items)
    fresh = a.handle("", session_id="vid", action={"type": "flow_next", "value": "fresh"})
    assert fresh["intent"] == "flow_fresh"
    assert "Новая генерация" in fresh["text"]
    assert "памяти" in fresh["text"]
    assert "женщина у окна" in fresh["text"]
    ses = store.get("vid")
    assert ses["prior"] and "женщина у окна" in ses["prior"][-1]["prompt"]
    asked = a.handle("", session_id="vid", action={"type": "choose_type", "value": "image"})
    assert "Что нужно сделать" in asked["text"]
    nxt = a.handle("ночной рынок того же героя", session_id="vid")
    assert nxt["intent"] == "variants"
    ses = store.get("vid")
    assert "Контекст прошлой генерации" in (ses.get("idea") or "")
    assert ses["prior"]


def test_status_names_dialog(make_assistant):
    from assistant.flask_adapter import status
    d = status(_a(make_assistant))
    assert d["dialog_manager"] == "on"
    assert isinstance(d["build"], str) and d["build"]
    assert "session_store" in d
