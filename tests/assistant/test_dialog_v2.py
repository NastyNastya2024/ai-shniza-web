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
    labels = [c.get("label") or "" for c in d.get("chips") or []]
    assert "Раскадровка" not in " ".join(labels) and "Озвучка" not in " ".join(labels)
    assert not any(c.get("action") == "pipe_stage" for c in d.get("chips") or [])
    assert "Опишите" in d["text"] or "Здравствуйте" in d["text"]
    assert labels == ["Изображения", "Видео", "Подготовка к видео", "Звук", "Тексты", "Другое"]


def test_marketplace_asks_product_before_models(make_assistant):
    d = _a(make_assistant).handle("мне нужно сделать карточку для маркетплейса", session_id="m1")
    assert d["intent"] == "variants"
    assert d["dialog"]["story"] == "COM.CARD"
    assert not any(b.get("type") == "models" for b in d.get("blocks") or [])
    assert not any(b.get("type") == "brief" for b in d.get("blocks") or [])
    assert "Собрать или улучшить" not in d["text"]
    assert "одним сообщением" not in d["text"]
    assert "Что за товар" not in d["text"]


def test_marketplace_known_slots_go_to_idea_then_models(make_assistant):
    a = _a(make_assistant)
    d = a.handle("вб, инфографика, кроссовки, белый фон", session_id="m2")
    assert d["intent"] == "variants"
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    assert len(items) >= 2
    assert not any(b.get("type") == "models" for b in d["blocks"])
    d = a.handle("", session_id="m2", action={"type": "use_variant", "value": items[0]["id"]})
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
    assert "Настроение." in items[0]["text"] and "Стиль." in items[0]["text"] and "Композиция." in items[0]["text"]
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
    assert "до 1 минуты" in d["text"]
    assert "Чем точнее формулировка, тем ближе результат к вашей задумке." in d["text"]
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


def test_animate_new_photo_drops_the_previous_prompt_and_file(make_assistant):
    from assistant.session import empty_session

    a = _a(make_assistant)
    old = "upl_" + "11" * 12
    new = "upl_" + "22" * 12
    desert = " ".join(["женщина на пустыне с огнём"] * 12)
    ses = empty_session()
    ses["flow"] = {
        "stage": "card", "kind": "video", "story": "", "slots": {}, "idea": desert,
        "idea_user": desert, "path": "direct", "next": "card", "source": desert,
    }
    ses["prompt"] = ses["prompt_base"] = ses["idea"] = desert
    ses["picked"] = "p-video"
    ses["kind"] = "video"
    ses["files"] = [{"id": old, "kind": "image", "name": "old.jpg"}]
    ses["media"] = [{
        "id": "m1", "source": "upload", "kind": "image", "name": "old.jpg",
        "upload_id": old, "alive": True, "n": 1, "url": "", "work_id": "",
    }]
    a.d.store.set("anim", ses)
    d = a.handle(
        "оживи картинку",
        {"has_image": True, "attachments": [{"id": new, "kind": "image", "name": "horse.jpg"}]},
        "anim",
    )
    assert "Обновила промпт" not in (d.get("text") or "")
    assert d["intent"] == "look_photo"
    assert "женщина на пустыне" not in (d.get("text") or "")
    saved = a.d.store.get("anim")
    alive = [m.get("upload_id") for m in saved.get("media") or [] if m.get("alive")]
    assert alive == [new]


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
    assert d.get("silent") is True and not d.get("chips")
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


def test_cartoon_picture_is_not_a_video(make_assistant):
    from assistant.router import detect_kind
    assert detect_kind("сделай картинку русалки в мультяшном стиле", False) == "image"
    assert detect_kind("сделай мультик про русалку", False) == "video"
    a = _a(make_assistant)
    d = a.handle("сделай картинку русалки в мультяшном стиле", session_id="imgC")
    assert d["intent"] == "variants"
    assert d["dialog"]["task"] == "image"
    blob = " ".join(i.get("text") or "" for b in d["blocks"] if b.get("type") == "variants" for i in b["items"])
    assert "Движение." not in blob and "пролёт" not in blob.lower()
    assert "мультяшный стиль" in blob.lower()
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    nxt = a.handle("", session_id="imgC", action={"type": "use_variant", "value": items[0]["id"]})
    assert nxt["intent"] == "advise"
    assert "Сразу видео" not in nxt["text"]
    a = _a(make_assistant)
    d = a.handle("нарисуй рыжего кота на крыше", session_id="img1")
    assert d["intent"] == "variants"
    assert not any(b.get("type") in ("brief", "models") for b in d.get("blocks") or [])
    assert "Что за товар" not in d["text"] and "нужен промпт" not in d["text"].lower()
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    assert len(items) >= 2
    d = a.handle("", session_id="img1", action={"type": "use_variant", "value": items[0]["id"]})
    assert d["intent"] == "advise"
    assert any(b.get("type") == "models" for b in d["blocks"])


def test_locked_image_skips_model_choice(make_assistant):
    a = _a(make_assistant)
    ctx = {"model_locked": True, "selected_model_id": "gpt-image-2", "selected_model_kind": "image"}
    d = a.handle("сделай картинку русалки в мультяшном стиле", ctx, "imgL")
    assert d["intent"] == "variants"
    assert d["dialog"]["task"] == "image"
    text = d["text"] + " " + " ".join(
        i.get("text") or "" for b in d["blocks"] if b.get("type") == "variants" for i in b.get("items") or [])
    assert "Движение." not in text and "Сразу видео" not in text
    assert "мультяшный стиль" in text.lower() or "мультяшн" in text.lower()
    assert "Композиция." in text
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    d = a.handle("", ctx, "imgL", action={"type": "use_variant", "value": items[0]["id"]})
    assert d["intent"] != "flow_path"
    assert any(b.get("type") == "params" for b in d["blocks"])
    assert any(b.get("type") == "summary" and b.get("allow_file") for b in d["blocks"])
    assert not any(b.get("type") == "models" for b in d["blocks"])
    assert d.get("generate_model") == "gpt-image-2"
    assert "Сразу видео" not in (d.get("text") or "")


def test_locked_video_keeps_prompt_and_storyboard_then_parameters(make_assistant):
    a = _a(make_assistant)
    ctx = {"model_locked": True, "selected_model_id": "wan-3-0", "selected_model_kind": "video"}
    d = a.handle("сделай ролик: девушка танцует на крыше вечером", ctx, "wan1")
    assert d["intent"] in ("variants", "flow_slots")
    assert not any(b.get("type") in ("params", "summary", "models") for b in d.get("blocks") or [])
    while d["intent"] == "flow_slots":
        slot = (d["chips"][0].get("value") or {})
        d = a.handle("", ctx, "wan1", action={"type": "flow_slot", "value": slot})
    assert d["intent"] == "variants"
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    d = a.handle("", ctx, "wan1", action={"type": "use_variant", "value": items[0]["id"]})
    assert d["intent"] == "flow_path"
    actions = {c["action"] for c in d["chips"]}
    assert "path_board" in actions and "path_photos" in actions
    assert "Сразу видео" in d["text"]
    d = a.handle("", ctx, "wan1", action={"type": "path_direct"})
    assert any(b.get("type") == "params" for b in d["blocks"])
    assert any(b.get("type") == "summary" for b in d["blocks"])
    assert not any(b.get("type") == "models" for b in d["blocks"])
    assert d.get("generate_model") == "wan-3-0"


def test_locked_video_with_photo_starts_the_prompt(make_assistant):
    a = _a(make_assistant)
    ctx = {"model_locked": True, "selected_model_id": "wan-3-0", "selected_model_kind": "video",
           "has_image": True, "attachments": [{"id": "upl_" + "ab" * 12, "kind": "image", "name": "model.jpg"}]}
    d = a.handle("оживи картинку сделай так чтобы модель танцевала", ctx, "wan2")
    assert d["intent"] in ("look_photo", "variants", "flow_slots")
    assert not any(b.get("type") in ("params", "summary") for b in d.get("blocks") or [])
    assert d.get("generate_model") != "wan-3-0"


def test_result_next_steps_work_without_an_open_flow(make_assistant):
    a = _a(make_assistant)
    d = a.handle("", session_id="nx", action={"type": "flow_next", "value": {"step": "redo", "prompt": "Девушка танцует на крыше вечером."}})
    assert d["intent"] == "idea"
    assert "Девушка танцует" in str(d.get("blocks"))
    fresh = a.handle("", session_id="nx2", action={"type": "flow_next", "value": {"step": "fresh", "prompt": "Девушка танцует на крыше вечером."}})
    assert fresh["intent"] == "flow_fresh"
    assert "Новая генерация" in fresh["text"]


def test_selected_image_generate_sentence_is_the_prompt(make_assistant):
    a = _a(make_assistant)
    ctx = {"model_locked": True, "selected_model_id": "ideogram-v3-turbo", "selected_model_kind": "image"}
    d = a.handle("сгенерируй картинку девушки на дорогой тачке", ctx, "ig")
    assert "идею промпта" not in (d.get("text") or "").lower()
    assert d["intent"] == "variants"
    assert d["dialog"]["task"] == "image"
    again = a.handle("сгенерируй картинку девушки на дорогой тачке", ctx, "ig")
    assert "идею промпта" not in (again.get("text") or "").lower()


def test_composer_image_skips_the_model_board(make_assistant):
    a = _a(make_assistant)
    ctx = {"selected_model_id": "ideogram-v3-turbo", "selected_model_kind": "image", "model_locked": False}
    d = a.handle("сгенерируй картинку девушки на дорогой тачке", ctx, "ig2")
    assert d["intent"] == "variants"
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    d = a.handle("", ctx, "ig2", action={"type": "use_variant", "value": items[0]["id"]})
    assert d.get("generate_model") == "ideogram-v3-turbo"
    assert any(b.get("type") == "params" for b in d["blocks"])
    assert not any(b.get("type") == "models" for b in d["blocks"])
    back = a.handle("", ctx, "ig2", action={"type": "back"})
    assert back["intent"] == "variants"
    assert not any(b.get("type") == "models" for b in back.get("blocks") or [])


def test_back_from_model_board_returns_to_prompts(make_assistant):
    a = _a(make_assistant)
    d = a.handle("сгенерируй картинку девушки на дорогой тачке", {}, "ig3")
    items = next(b["items"] for b in d["blocks"] if b["type"] == "variants")
    board = a.handle("", {}, "ig3", action={"type": "use_variant", "value": items[0]["id"]})
    assert any(b.get("type") == "models" for b in board.get("blocks") or [])
    back = a.handle("", {}, "ig3", action={"type": "back"})
    assert back["intent"] == "variants"
    assert not any(b.get("type") == "models" for b in back.get("blocks") or [])


def test_finished_image_buttons_redo_video_and_angles(make_assistant):
    a = _a(make_assistant)
    a.handle("сгенерируй картинку девушки на дорогой тачке", {}, "pic")
    done = a.handle("", {}, "pic", action={"type": "media_add", "value": {
        "kind": "image", "url": "/api/works/9/media", "work_id": "9", "prompt": "Девушка за рулём дорогой машины.",
    }})
    assert done.get("silent") is True
    assert not done.get("chips")
    prompt = "Девушка за рулём дорогой машины."
    redo = a.handle("", {}, "pic", action={"type": "flow_next", "value": {"step": "image_redo", "prompt": prompt}})
    assert redo["intent"] == "variants" and redo["dialog"]["task"] == "image"
    video = a.handle("", {}, "picv", action={"type": "flow_next", "value": {"step": "image_video", "prompt": prompt}})
    assert video["intent"] == "variants" and video["dialog"]["task"] == "video"
    assert "видеомодел" in (video.get("text") or "").lower()
    ctx = {"model_locked": True, "selected_model_id": "ideogram-v3-turbo", "selected_model_kind": "image", "has_image": True}
    angles = a.handle("", ctx, "pica", action={"type": "flow_next", "value": {"step": "image_angles", "prompt": prompt}})
    assert angles["intent"] == "variants" and angles["dialog"]["task"] == "image"
    assert "ракурс" in (angles.get("text") or "").lower()
    items = next(b["items"] for b in angles["blocks"] if b["type"] == "variants")
    nxt = a.handle("", ctx, "pica", action={"type": "use_variant", "value": items[0]["id"]})
    assert any(b.get("type") == "models" for b in nxt.get("blocks") or [])
    assert nxt.get("generate_model") != "ideogram-v3-turbo"


def _variant_blob(d):
    parts = [d.get("text") or ""]
    for block in d.get("blocks") or []:
        if block.get("type") != "variants":
            continue
        for item in block.get("items") or []:
            parts.append(item.get("text") or "")
    return "\n".join(parts)


def test_product_card_prompt_is_a_product_photo(make_assistant):
    d = _a(make_assistant).handle("сделай карточку товара утюг", session_id="iron")
    blob = _variant_blob(d)
    assert d["dialog"]["task"] == "image"
    assert "3:4" in blob
    assert "утюг" in blob.lower()
    assert "Спокойное ясное настроение" not in blob
    assert "Движение." not in blob


def test_product_card_offers_a_picture_before_video(make_assistant):
    a = _a(make_assistant)
    a.handle("сделай карточку товара утюг", session_id="iron2")
    d = a.handle("", session_id="iron2", action={
        "type": "media_add",
        "value": {"kind": "text", "reply": "Предметная фотография утюга, кадр 3:4."},
    })
    labels = [c.get("label") for c in d.get("chips") or []]
    assert labels[0] == "Картинку"
    assert "Сделать видео по этому" in labels


def test_asking_for_a_picture_keeps_the_written_prompt(make_assistant):
    a = _a(make_assistant)
    a.handle("сделай карточку товара утюг", session_id="iron3")
    written = (
        "Предметная фотография утюга для карточки товара. Кадр 3:4, вертикальный. "
        "Корпус из глянцевого пластика, подошва из стали, мягкий свет слева. "
        "Фон светло-серый, без надписей. Кадр статичный, без движения. "
    ) * 3
    a.handle("", session_id="iron3", action={"type": "text_note", "value": {"text": written, "name": "Claude"}})
    d = a.handle("нужна картинка", session_id="iron3")
    blob = _variant_blob(d)
    assert "Корпус из глянцевого пластика" in blob
    assert "Спокойное ясное настроение" not in blob
    assert d["dialog"]["task"] == "image"


def test_back_from_a_mistaken_video_returns_to_the_picture(make_assistant):
    a = _a(make_assistant)
    a.handle("сделай карточку товара утюг", session_id="iron4")
    text = (
        "Предметная фотография утюга для карточки товара. Корпус из глянцевого пластика, "
        "подошва из стали, ручка матовая. Свет мягкий слева, фон светло-серый, кадр статичный. "
    ) * 3
    video = a.handle("", session_id="iron4", action={"type": "make", "value": {"kind": "video", "text": text}})
    assert video["dialog"]["task"] == "video"
    back = a.handle("", session_id="iron4", action={"type": "back"})
    assert back["dialog"]["task"] == "image"
    assert "Корпус из глянцевого пластика" in _variant_blob(back)


def test_changed_intent_leaves_the_old_format(make_assistant):
    a = _a(make_assistant)
    a.handle("привет", session_id="swap")
    a.handle("", session_id="swap", action={"type": "format_cat", "value": "prep"})
    a.handle("", session_id="swap", action={"type": "format_sub", "value": "vprompt"})
    switched = a.handle("мне нужно изображения персонажа", session_id="swap")
    blob = _variant_blob(switched) or switched.get("text") or ""
    assert "Это уже не «Промпт для видео»" in blob
    assert "Что в кадре" in blob and "персонажа" in blob
    assert "составь промпт для генерации видео" not in blob.lower()
    assert switched["dialog"]["task"] == "image"


def test_after_the_prompt_a_new_format_switches(make_assistant):
    a = _a(make_assistant)
    a.handle("привет", session_id="later")
    a.handle("", session_id="later", action={"type": "format_cat", "value": "prep"})
    a.handle("", session_id="later", action={"type": "format_sub", "value": "vprompt"})
    a.handle("герой идёт по ночному городу", session_id="later")
    switched = a.handle("нет, нужна картинка персонажа", session_id="later")
    blob = _variant_blob(switched) or switched.get("text") or ""
    assert "Это уже не «Промпт для видео»" in blob
    assert switched["dialog"]["task"] == "image"


def test_same_format_still_takes_the_subject(make_assistant):
    a = _a(make_assistant)
    a.handle("привет", session_id="keep")
    a.handle("", session_id="keep", action={"type": "format_cat", "value": "prep"})
    a.handle("", session_id="keep", action={"type": "format_sub", "value": "vprompt"})
    kept = a.handle("герой идёт по ночному городу", session_id="keep")
    assert kept["intent"] == "format_prompt"
    assert "составь промпт для генерации видео" in (kept.get("text") or "").lower()
    assert "ночному городу" in kept["text"]


def test_hello_category_waits_for_a_subject(make_assistant):
    a = _a(make_assistant)
    a.handle("привет", session_id="hi2")
    asked = a.handle("", session_id="hi2", action={"type": "format_cat", "value": "image"})
    opened = a.handle("", session_id="hi2", action={"type": "format_sub", "value": "photo"})
    assert opened["intent"] == "format_idea"
    assert "Что в кадре" not in (opened.get("text") or "")
    built = a.handle("кофейня у окна", session_id="hi2")
    blob = _variant_blob(built) or built.get("text") or ""
    assert "Что в кадре" in blob and "кофейня у окна" in blob


def test_unclear_request_starts_with_categories(make_assistant):
    a = _a(make_assistant)
    d = a.handle("мне нужны маркетинговые материалы", session_id="mkt")
    assert d["intent"] == "intent_clarify"
    assert [c.get("label") for c in d["chips"]] == [
        "Изображения", "Видео", "Подготовка к видео", "Звук", "Тексты", "Другое",
    ]
    assert not any(b.get("type") == "variants" for b in d.get("blocks") or [])
    subs = a.handle("", session_id="mkt", action={"type": "format_cat", "value": "image"})
    assert [c.get("label") for c in subs["chips"]][:3] == ["Картинка / фото", "Баннер", "Обложка"]
    opened = a.handle("", session_id="mkt", action={"type": "format_sub", "value": "banner"})
    blob = _variant_blob(opened) or opened.get("text") or ""
    assert "Текст на баннере" in blob and "маркетинговые материалы" in blob
    assert opened["dialog"]["task"] == "image"


def test_a_fairy_tale_goes_to_a_text_model(make_assistant):
    d = _a(make_assistant).handle(
        "привет - мне надо сгенерить сказку назидательную про то как лечить травму отвергнутого",
        session_id="tale",
    )
    assert "видео или картинка" not in (d.get("text") or "")
    assert d.get("text_ask")
    assert "сказку" in d["text_ask"]
    assert d.get("generate_model")


def test_status_names_dialog(make_assistant):
    from assistant.flask_adapter import status
    d = status(_a(make_assistant))
    assert d["dialog_manager"] == "on"
    assert isinstance(d["build"], str) and d["build"]
    assert "session_store" in d
