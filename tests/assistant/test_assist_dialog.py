"""Помощник без стартового меню: память диалога, карточка промпта, реестр файлов."""
from __future__ import annotations

import os

from assistant.tree import HintTree

SID = "u1:dialog"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _stage_buttons(r):
    return [c for c in r.get("chips") or [] if c.get("action") in ("pipe_stage", "choose_type")]


def _summary(r):
    return next((b for b in r.get("blocks") or [] if b.get("type") == "summary"), None)


def test_no_start_menu(make_assistant):
    a = make_assistant(llm=False)
    for text in ("", "привет", "аааа", "что ты умеешь"):
        r = a.handle(text, {}, SID + text)
        assert len(_stage_buttons(r)) < 3
        assert "pipe_stage" not in {c.get("action") for c in r.get("chips") or []}


def test_vague_asks_without_menu(make_assistant):
    a = make_assistant(llm=False)
    r = a.handle("сделай что-нибудь красивое", {}, SID)
    assert r["intent"] == "need_subject"
    assert len(_stage_buttons(r)) < 3
    assert "уточн" in r["text"].lower() or "кто" in r["text"].lower()


def test_kitchen_gets_tree_hints(make_assistant):
    tree = HintTree.load_json(os.path.join(ROOT, "assistant", "data", "hint_tree.json"))
    a = make_assistant(llm=False, tree=tree)
    r = a.handle("покажи клиенту 3 варианта кухни в разных стилях", {}, SID)
    assert r.get("tree") and r["tree"].get("story")
    assert any(c.get("action") == "tree_hint" for c in r.get("chips") or [])


def test_two_processes_share_dialog(make_assistant):
    a = make_assistant(llm=False)
    b = make_assistant(llm=False)
    b.d.store = a.d.store
    a.handle("сделай видео кота на кухне", {}, SID)
    ses = b.d.store.get(SID)
    assert "кот" in (ses.get("idea") or "")
    r = b.handle("а теперь ночью", {}, SID)
    assert "ноч" in (r.get("generate_prompt") or b.d.store.get(SID).get("prompt") or "").lower() or "ноч" in (b.d.store.get(SID).get("idea") or "").lower()


def test_night_keeps_model_and_params(make_assistant):
    a = make_assistant(llm=False)
    a.handle("сделай видео кота на кухне", {}, SID)
    a.handle("", {}, SID, action={"type": "pick_model", "value": "seedance-2-5"})
    before = a.d.store.get(SID)
    params = dict(before.get("params") or {})
    r = a.handle("а теперь ночью", {}, SID)
    ses = a.d.store.get(SID)
    assert ses.get("picked") == "seedance-2-5"
    assert ses.get("params") == params or set(params).issubset(set(ses.get("params") or {}))
    assert "ноч" in (r.get("generate_prompt") or ses.get("prompt") or "").lower()
    assert _summary(r) and "ноч" in (_summary(r).get("prompt") or "").lower()


def test_guest_becomes_user_keeps_context(make_assistant):
    a = make_assistant(llm=False)
    a.handle("видео кот на крыше", {}, SID)
    a.handle("", {"_uid": "42"}, SID)
    ses = a.d.store.get(SID)
    assert ses.get("owner") == "42"
    assert "кот" in (ses.get("idea") or "")


def test_ready_has_summary_and_edit_prompt(make_assistant):
    a = make_assistant(llm=False)
    a.handle("видео: кот на крыше ночью", {}, SID)
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "seedance-2-5"})
    if not r.get("ready"):
        r = a.handle("", {}, SID, action={"type": "has_prompt", "value": "no"})
    assert r.get("ready") is True
    sm = _summary(r)
    assert sm and sm.get("prompt") and sm["prompt"] == r.get("generate_prompt")
    edited = sm["prompt"] + " без людей"
    r2 = a.handle("", {}, SID, action={"type": "edit_prompt", "value": {"text": edited}})
    assert r2.get("generate_prompt", "").endswith("без людей") or "без людей" in (r2.get("generate_prompt") or "")
    assert a.d.store.get(SID).get("picked") == "seedance-2-5"
    cam = a.d.store.get(SID).get("camera")
    r3 = a.handle("", {}, SID, action={"type": "edit_prompt", "value": {"text": "кот на крыше, вечер"}})
    assert a.d.store.get(SID).get("camera") == cam
    assert "вечер" in (r3.get("generate_prompt") or "")
    r4 = a.handle("сделай вечер теплее", {}, SID)
    assert _summary(r4) and r4.get("generate_prompt")


def test_media_same_video_then_two_then_second_image(make_assistant):
    a = make_assistant(llm=False, inputs_fn=lambda mid: ["text", "image"] if "image" in mid or mid.startswith("seedream") or mid.startswith("gpt-image") else ["text", "image", "video"])
    ctx = {"attachments": [{"id": "upl_v1", "kind": "video", "name": "cat.mp4"}]}
    a.handle("вот видео", ctx, SID)
    a.handle("", {}, SID, action={"type": "media_add", "value": {"kind": "image", "url": "http://img/1.jpg", "model": "seedream", "prompt": "кот на кухне", "work_id": "w1"}})
    r = a.handle("с этим же видео сделай рилс", {}, SID)
    assert "видео №1" in r["text"].lower() or "видео №1" in (a.d.store.get(SID).get("focus_note") or "").lower() or a.d.store.get(SID).get("focus") == ["upl_v1"]
    ctx2 = {"attachments": [{"id": "upl_v2", "kind": "video", "name": "dog.mp4"}]}
    a.handle("ещё ролик", ctx2, SID)
    r2 = a.handle("с этим видео сделай вертикальный рилс", {}, SID)
    assert r2["intent"] == "ask_file"
    assert len(r2["chips"]) >= 2
    a.handle("", {}, SID, action={"type": "media_add", "value": {"kind": "image", "url": "http://img/2.jpg", "prompt": "собака", "model": "seedream"}})
    r3 = a.handle("вторую картинку в стиле аниме", {}, SID)
    focus = a.d.store.get(SID).get("focus") or []
    media = a.d.store.get(SID).get("media") or []
    second = [m for m in media if m.get("kind") == "image" and m.get("n") == 2]
    assert second and focus == [second[0]["id"]]


def test_model_rejects_video_offers_others(make_assistant):
    def inputs(mid):
        if mid.startswith("seedream") or mid.startswith("gpt-image") or "image" in mid:
            return ["text", "image"]
        return ["text", "video"]
    a = make_assistant(llm=False, inputs_fn=inputs)
    a.handle("видео кот", {"attachments": [{"id": "upl_v", "kind": "video", "name": "cat.mp4"}]}, SID)
    a.handle("с этим видео", {}, SID)
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "seedream-5-pro"})
    assert r["intent"] == "need_file"
    assert r.get("models")


def test_files_confirm_only_checked(make_assistant):
    a = make_assistant(llm=False)
    ctx = {"attachments": [
        {"id": "a", "kind": "image", "name": "one.png"},
        {"id": "b", "kind": "image", "name": "two.png"},
        {"id": "c", "kind": "image", "name": "three.png"},
    ]}
    a.handle("сделай картинку", ctx, SID)
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "seedream-5-pro"})
    if r.get("intent") == "has_prompt":
        r = a.handle("", {}, SID, action={"type": "has_prompt", "value": "no"})
    fb = next((b for b in r.get("blocks") or [] if b.get("type") == "files"), None)
    assert fb and fb.get("need_confirm") and not any(it.get("checked") for it in fb["items"])
    assert not any(c.get("action") == "generate" for c in r.get("chips") or [])
    r2 = a.handle("", {}, SID, action={"type": "files_confirm", "value": {"items": [{"id": "b", "role": "референс стиля"}]}})
    ids = [f.get("id") for f in r2.get("generate_files") or []]
    assert ids == ["b"]


def test_two_videos_ask_which_to_keep(make_assistant):
    a = make_assistant(llm=False, inputs_fn=lambda mid: ["text", "video", "image"])
    ctx = {"attachments": [
        {"id": "v1", "kind": "video", "name": "a.mp4"},
        {"id": "v2", "kind": "video", "name": "b.mp4"},
    ]}
    a.handle("сделай видео", ctx, SID)
    a.handle("", {}, SID, action={"type": "pick_model", "value": "seedance-2-5"})
    r = a.handle("", {}, SID, action={"type": "files_confirm", "value": {"items": [{"id": "v1", "role": "основа"}, {"id": "v2", "role": "основа"}]}})
    assert r["intent"] == "ask_file" and "1 видео" in r["text"]


def test_one_file_no_question(make_assistant):
    a = make_assistant(llm=False)
    a.handle("сделай картинку кота", {"attachments": [{"id": "only", "kind": "image", "name": "cat.png"}]}, SID)
    r = a.handle("", {}, SID, action={"type": "pick_model", "value": "seedream-5-pro"})
    if r.get("intent") == "has_prompt":
        r = a.handle("", {}, SID, action={"type": "has_prompt", "value": "no"})
    fb = next((b for b in r.get("blocks") or [] if b.get("type") == "files"), None)
    assert fb and not fb.get("need_confirm") and fb["items"][0]["checked"]
    assert any(c.get("action") == "generate" for c in r.get("chips") or []) or r.get("ready")
