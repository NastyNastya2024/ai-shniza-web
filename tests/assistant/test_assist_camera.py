"""Движение камеры: каталог, вставка в промпт, блок на экране запуска видео."""
from assistant import camera as CAM

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
    assert blk(r, "prompt")["text"] == r["generate_prompt"]
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
    r = a.handle("видео: поезд едет по мосту", {}, SID)
    assert r.get("intent") == "brief" or blk(r, "brief") or blk(r, "camera")
    # бриф или сразу варианты — на видео всегда есть блок камеры
    if blk(r, "brief") or r.get("intent") == "brief":
        assert blk(r, "camera")
        assert not any(it["selected"] for it in blk(r, "camera")["items"])
        r2 = a.handle("", {}, SID, action={"type": "pick_camera", "value": "dolly-in"})
        assert r2["intent"] == "pick_camera"
        assert blk(r2, "brief")
        assert next(it for it in blk(r2, "camera")["items"] if it["id"] == "dolly-in")["selected"]
        assert blk(r2, "prompt") is None  # ещё не экран запуска


def test_camera_persists_across_turns_into_prompt(make_assistant):
    """camera/prompt_base должны жить в сессии — иначе выбор движения теряется между ходами."""
    import json
    from tests.assistant.assistant_testkit import FakeTransport, make_chain

    brief = json.dumps({
        "clear": True, "summary": "Поезд",
        "questions": [{"id": "t", "label": "T", "options": [{"value": "a", "label": "A"}]}],
    }, ensure_ascii=False)
    variants = json.dumps({
        "variants": [{"title": "Эпик", "prompt": "A train crosses a steel bridge at noon."}],
    }, ensure_ascii=False)
    a = make_assistant(brief=True, transport=FakeTransport(omniroute=[
        ("ok", brief), ("ok", variants), ("ok", variants), ("ok", variants),
    ]))
    sid = "cam-persist"
    a.handle("видео: поезд едет по мосту", {}, sid)
    a.handle("", {}, sid, action={"type": "pick_camera", "value": "dolly-in"})
    assert a.d.store.get(sid).get("camera") == "dolly-in"
    a.handle("", {}, sid, action={"type": "variants", "value": "skip"})
    assert a.d.store.get(sid).get("camera") == "dolly-in"
    vids = a.d.store.get(sid).get("variants") or []
    assert vids
    a.handle("", {}, sid, action={"type": "use_variant", "value": vids[0]["id"]})
    assert a.d.store.get(sid).get("camera") == "dolly-in"
    assert "dolly in" in (a.d.store.get(sid).get("prompt") or "").lower()
    r = a.handle("", {}, sid, action={"type": "pick_model", "value": "seedance-2-5"})
    assert "dolly in" in (r.get("generate_prompt") or "").lower()
    assert "dolly in" in (blk(r, "prompt")["text"] or "").lower()
