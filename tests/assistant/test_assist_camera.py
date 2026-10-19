"""Движение камеры: каталог, вставка в промпт, блок на экране запуска видео."""
from assistant import camera as CAM
from assistant_testkit import answer_open_brief, pick_want_prompt, to_variants

SID = "cam1"


def blk(r, typ):
    return next((b for b in r["blocks"] if b["type"] == typ), None)


def test_catalog_matches_download_script():
    assert len(CAM.MOVES) == 46
    assert CAM.get("dolly-in")["file"] == "08-dolly-in-hq.mp4"
    assert "dolly in" in CAM.get("dolly-in")["prompt"].lower()


def test_compose_and_strip_roundtrip():
    base = "A ginger cat fries eggs in a cozy kitchen"
    full = CAM.compose(base, "orbit-cw")
    assert full.startswith(base) and "clockwise orbit" in full
    assert CAM.strip(full) == base
    assert CAM.compose(full, "orbit-cw") == full  # не дублируем


def test_pick_camera_appends_prompt(make_assistant):
    a = make_assistant(brief=False)
    a.handle("видео: кот жарит яичницу", {}, SID)
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "seedance-2-5"})
    cam = blk(r, "camera")
    assert cam and len(cam["items"]) == 46
    assert cam.get("groups") and len(cam["groups"]) == 7
    assert not any(it["selected"] for it in cam["items"])  # по умолчанию — без движения
    assert "locked-off static" not in (r.get("generate_prompt") or "").lower()
    before = CAM.strip(r["generate_prompt"] or "")
    r = a.handle("", {}, SID, action={"type": "pick_camera", "value": "dolly-in"})
    assert r["intent"] == "pick_camera"
    assert "dolly in" in r["generate_prompt"].lower()
    assert before in r["generate_prompt"] or CAM.strip(r["generate_prompt"]) == before
    assert next(it for it in blk(r, "camera")["items"] if it["id"] == "dolly-in")["selected"]
    assert blk(r, "prompt") is None  # видео: промпт не показываем, только настройки + камера
    # смена движения не копит старые фразы
    r = a.handle("", {}, SID, action={"type": "pick_camera", "value": "pan-right"})
    assert "pan right" in r["generate_prompt"].lower()
    assert "dolly in" not in r["generate_prompt"].lower()
    r = a.handle("", {}, SID, action={"type": "pick_camera", "value": "none"})
    assert "pan right" not in r["generate_prompt"].lower()
    assert r["generate_prompt"] == before
    assert not any(it["selected"] for it in blk(r, "camera")["items"])


def test_camera_block_only_for_video(make_assistant):
    a = make_assistant(brief=False)
    a.handle("картинка: логотип кофейни", {}, SID)
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "seedream-5-pro"})
    assert blk(r, "camera") is None


def test_camera_in_video_brief(make_assistant):
    a = make_assistant(brief=True)
    a.handle("видео: поезд едет по мосту", {}, SID)
    r = pick_want_prompt(a, SID, "seedance-2-5")
    assert r.get("intent") == "brief" and blk(r, "brief") and blk(r, "camera") is None  # этап 1 без камеры
    r = answer_open_brief(a, SID, "поезд едет по стальному мосту днём")
    assert r.get("intent") == "brief" and blk(r, "brief") and blk(r, "camera")
    assert not any(it["selected"] for it in blk(r, "camera")["items"])
    r2 = a.handle("", {}, SID, action={"type": "pick_camera", "value": "dolly-in"})
    assert r2["intent"] == "pick_camera"
    assert blk(r2, "brief")
    assert next(it for it in blk(r2, "camera")["items"] if it["id"] == "dolly-in")["selected"]
    assert blk(r2, "prompt") is None  # ещё не экран запуска
    r3 = a.handle("", {}, SID, action={"type": "variants"})
    assert r3["intent"] == "variants" and blk(r3, "variants")
    assert blk(r3, "camera") is None  # на вариантах пикер камеры не показываем


def test_variants_never_include_camera_block(make_assistant):
    """После генерации вариантов вопрос про камеру не повторяется — даже если на брифе не выбирали."""
    a = make_assistant(brief=True)
    a.handle("видео: машина в пустыне на закате", {}, SID)
    pick_want_prompt(a, SID, "seedance-2-5")
    r = to_variants(a, SID)
    assert r["intent"] == "variants" and blk(r, "variants")
    assert blk(r, "camera") is None


def test_camera_persists_across_turns_into_prompt(make_assistant):
    """camera/prompt_base должны жить в сессии — иначе выбор движения теряется между ходами."""
    import json
    from tests.assistant.assistant_testkit import FakeTransport

    variants = json.dumps({
        "variants": [{"title": "Эпик", "prompt": "A train crosses a steel bridge at noon."}],
    }, ensure_ascii=False)
    a = make_assistant(brief=True, transport=FakeTransport(omniroute=[
        ("ok", variants), ("ok", variants), ("ok", variants),
    ]))
    sid = "cam-persist"
    a.handle("видео: поезд едет по мосту", {}, sid)
    pick_want_prompt(a, sid, "seedance-2-5")
    answer_open_brief(a, sid, "поезд едет по стальному мосту днём")
    a.handle("", {}, sid, action={"type": "pick_camera", "value": "dolly-in"})
    assert a.d.store.get(sid).get("camera") == "dolly-in"
    a.handle("", {}, sid, action={"type": "variants", "value": "skip"})
    assert a.d.store.get(sid).get("camera") == "dolly-in"
    vids = a.d.store.get(sid).get("variants") or []
    assert vids
    a.handle("", {}, sid, action={"type": "use_variant", "value": vids[0]["id"]})
    assert a.d.store.get(sid).get("camera") == "dolly-in"
    assert "dolly in" in (a.d.store.get(sid).get("prompt") or "").lower()
    a.handle("", {}, sid, action={"type": "skip_polish"})
    r = a.handle("", {}, sid, action={"type": "pick_model", "value": "seedance-2-5"})
    assert "dolly in" in (r.get("generate_prompt") or "").lower()
    assert blk(r, "prompt") is None and blk(r, "camera")
