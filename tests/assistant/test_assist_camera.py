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
    assert blk(r, "camera") and len(blk(r, "camera")["items"]) == 46
    assert not any(it["selected"] for it in blk(r, "camera")["items"])
    before = r["generate_prompt"]
    r = a.handle("", {}, SID, action={"type": "pick_camera", "value": "dolly-in"})
    assert r["intent"] == "pick_camera"
    assert "dolly in" in r["generate_prompt"].lower()
    assert before in r["generate_prompt"] or CAM.strip(r["generate_prompt"])
    assert next(it for it in blk(r, "camera")["items"] if it["id"] == "dolly-in")["selected"]
    assert blk(r, "prompt")["text"] == r["generate_prompt"]
    # смена движения не копит старые фразы
    r = a.handle("", {}, SID, action={"type": "pick_camera", "value": "pan-right"})
    assert "pan right" in r["generate_prompt"].lower()
    assert "dolly in" not in r["generate_prompt"].lower()
    r = a.handle("", {}, SID, action={"type": "pick_camera", "value": "none"})
    assert "pan right" not in r["generate_prompt"].lower()
    assert r["generate_prompt"] == before or r["generate_prompt"] == CAM.strip(before)


def test_camera_block_only_for_video(make_assistant):
    a = make_assistant(brief=False)
    a.handle("картинка: логотип кофейни", {}, SID)
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "seedream-5-pro"})
    assert blk(r, "camera") is None
