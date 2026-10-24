"""Флоу помощника: Промпт → Картинка → Раскадровка → Видео → Озвучка, артефакты только в сессии."""
import json

SID = "u1:pipe"
IMG = {"attachments": [{"kind": "image", "name": "ref.png"}]}
STYLE = {"style_name": "Ретро-плёнка", "palette": ["#E8C9A0", "#6B4F3A", "#2F3B45", "#C2593F", "#F4E9D8"],
         "light": {"type": "мягкий закатный", "direction": "сбоку", "contrast": "средний", "color_temperature": "тёплая"},
         "camera": {"lens": "50mm", "aperture": "f/2", "angle": "на уровне глаз", "depth_of_field": "малая"},
         "composition": "центр", "texture": "зерно плёнки", "mood": "ностальгия", "avoid": ["неон", "пластик"]}


def act(a, typ, value=None, ctx=None, sid=SID):
    action = {"type": typ}
    if value is not None:
        action["value"] = value
    return a.handle("", ctx or {}, sid, action=action)


def blk(r, typ):
    return next((x for x in r["blocks"] if x["type"] == typ), None)


def actions(r):
    return [(c["action"], c.get("value")) for c in r["chips"]]


def arts(a, sid=SID):
    return a.d.store.get(sid).get("arts") or []


def video_prompt(a, idea="черепаха плывёт над коралловым рифом"):
    act(a, "pipe_stage", "prompt")
    act(a, "pipe_sub", "video")
    return a.handle(idea, {}, SID)


def test_main_row_is_the_flow_and_says_artifacts_live_in_session(make_assistant):
    a = make_assistant(llm=False)
    r = a.handle("ну не знаю", {}, SID)
    assert [c["value"] for c in r["chips"]] == ["prompt", "image", "board", "video", "voice", "music"]
    assert "только в этом чате" in r["text"] and "24 час" in r["text"] and "Моих работах" in r["text"]
    r = act(a, "pipe_menu")
    assert r["intent"] == "pipe_menu" and "только в этом чате" in r["text"]


def test_prompt_stage_offers_four_kinds(make_assistant):
    a = make_assistant(llm=False)
    r = act(a, "pipe_stage", "prompt")
    assert [v for k, v in actions(r) if k == "pipe_sub"] == ["video", "speech", "style", "dialog"]
    assert ("pipe_menu", None) in actions(r)


def test_video_prompt_is_saved_and_offers_heroes_video_menu(make_assistant):
    a = make_assistant(llm=False)
    r = video_prompt(a)
    assert r["intent"] == "pipe_video_prompt_done" and r["degraded"]
    assert "черепаха" in blk(r, "prompt")["text"] and "Сохранила в артефакты сессии" in r["text"]
    assert actions(r)[:2] == [("pipe_sub", "hero"), ("pipe_stage", "video")] and actions(r)[-1] == ("pipe_menu", None)
    assert [x["type"] for x in arts(a)] == ["videoPrompt"]
    r = act(a, "pipe_menu")
    groups = {g["stage"]: g["items"] for g in blk(r, "pipe_arts")["groups"]}
    assert len(groups["prompt"]) == 1 and groups["video"] == []
    assert "Новый чат" in blk(r, "pipe_arts")["note"]


def test_speech_prompt_artifact(make_assistant):
    a = make_assistant(llm=False)
    act(a, "pipe_stage", "prompt")
    act(a, "pipe_sub", "speech")
    r = a.handle("Бабушка рассказывает внуку сказку про черепаху", {}, SID)
    assert r["intent"] == "pipe_speech_prompt_done" and arts(a)[-1]["type"] == "speechPrompt"


def test_style_json_explains_method_then_extracts_and_applies(make_assistant):
    a = make_assistant(llm=False)
    act(a, "pipe_stage", "prompt")
    r = act(a, "pipe_sub", "style")
    assert "Сюжет я не копирую" in r["text"] and "другому сюжету" in r["text"]
    assert blk(r, "pipe_method") and ("attach", None) in actions(r)
    r = a.handle("готово", IMG, SID)
    assert r["intent"] == "pipe_style_ready" and r["ready"]
    assert r["generate_model"] == "gpt-5-4" and r["generate_files"] == [{"kind": "image", "name": "ref.png"}]
    assert "JSON" in r["generate_prompt"] and r["pipe_expect"] == "style" and r.get("keep_assistant")
    r = act(a, "pipe_result", {"kind": "text", "model": "gpt-5-4", "reply": "Вот стиль:\n```json\n" + json.dumps(STYLE, ensure_ascii=False) + "\n```"}, ctx=IMG)
    assert r["intent"] == "pipe_style_done"
    assert json.loads(blk(r, "pipe_json")["json"])["palette"][0] == "#E8C9A0"
    assert arts(a)[-1]["type"] == "style"
    # стиль сам добавляется к следующему этапу
    video_prompt(a)
    r = act(a, "pipe_sub", "hero")
    assert "Visual style: Ретро-плёнка" in blk(r, "prompt")["text"] and "Avoid: неон" in blk(r, "prompt")["text"]


def test_style_bad_reply_offers_retry(make_assistant):
    a = make_assistant(llm=False)
    act(a, "pipe_stage", "prompt")
    act(a, "pipe_sub", "style", ctx=IMG)
    r = act(a, "pipe_result", {"kind": "text", "reply": "не могу"}, ctx=IMG)
    assert r["intent"] == "pipe_style_fail" and not any(x["type"] == "style" for x in arts(a))


def test_dialog_then_save_as_prompt(make_assistant):
    a = make_assistant(llm=False)
    act(a, "pipe_stage", "prompt")
    r = act(a, "pipe_sub", "dialog")
    assert r["intent"] == "pipe_dialog"
    r = a.handle("хочу ролик про маяк зимой", {}, SID)
    assert r["intent"] == "pipe_dialog" and ("pipe_dialog_save", None) in actions(r)
    r = a.handle("пусть будет ночь и северное сияние", {}, SID)
    r = act(a, "pipe_dialog_save")
    assert r["intent"] == "pipe_dialog_saved" and "маяк" in arts(a)[-1]["text"]


def test_hero_image_from_prompt_then_result_offers_storyboard(make_assistant):
    a = make_assistant(llm=False)
    video_prompt(a)
    r = act(a, "pipe_sub", "hero")
    assert blk(r, "models") and r["pipe_expect"] == "hero"
    prompts = [b for b in r["blocks"] if b["type"] == "prompt"]
    assert len(prompts) == 1 and prompts[0]["title"] == "Промпт из артефактов"
    assert prompts[0]["text"].startswith("Character portrait") and "черепаха" in prompts[0]["text"]
    assert ("pipe_menu", None) in actions(r)
    r = act(a, "pipe_result", {"kind": "image", "url": "/media/hero.png", "model": "gpt-image-2", "work_id": "w1"})
    assert r["intent"] == "pipe_saved_image" and "первым кадром" in r["text"]
    assert actions(r)[0] == ("pipe_stage", "board") and ("pipe_stage", "video") in actions(r)
    assert arts(a)[-1]["type"] == "hero" and arts(a)[-1]["url"] == "/media/hero.png"


def test_image_without_artifacts_asks_description(make_assistant):
    a = make_assistant(llm=False)
    r = act(a, "pipe_stage", "image")
    assert [v for k, v in actions(r) if k == "pipe_sub"] == ["hero", "scene", "bg", "other"]
    r = act(a, "pipe_sub", "bg")
    assert r["intent"] == "pipe_image_ask"
    r = a.handle("старая библиотека с витражами, вечер", {}, SID)
    assert blk(r, "models") and blk(r, "prompt")["text"].startswith("Environment plate") and r["pipe_expect"] == "image:bg"


def test_storyboard_from_artifacts_keeps_flow_buttons(make_assistant):
    a = make_assistant(llm=False)
    video_prompt(a)
    r = act(a, "pipe_stage", "board")
    assert r["intent"].startswith("sb_") and "Раскадровка из артефактов" in r["text"]
    assert ("pipe_menu", None) in actions(r)
    st = a.d.store.get(SID)
    assert st["pipe"]["expect"] == "board"
    r = act(a, "pipe_result", {"kind": "image", "url": "/media/sheet.png"})
    assert r["intent"] == "pipe_saved_board" and actions(r)[0] == ("pipe_stage", "video")


def test_series_result_keeps_all_frames(make_assistant):
    a = make_assistant(llm=False)
    video_prompt(a)
    act(a, "pipe_stage", "board")
    r = act(a, "pipe_result", {"kind": "image", "url": "/media/f1.png", "urls": ["/media/f1.png", "/media/f2.png", "/media/f3.png"], "series": True})
    assert r["intent"] == "pipe_saved_board" and arts(a)[-1]["frames"] == ["/media/f1.png", "/media/f2.png", "/media/f3.png"]


def test_video_takes_hero_as_first_frame_then_voice(make_assistant):
    a = make_assistant(llm=False)
    video_prompt(a)
    act(a, "pipe_sub", "hero")
    act(a, "pipe_result", {"kind": "image", "url": "/media/hero.png"})
    r = act(a, "pipe_stage", "video")
    assert blk(r, "models") and r["pipe_expect"] == "video"
    assert r["attach_urls"] == [{"src": "/media/hero.png", "name": "first-frame.png"}]
    assert "герой — первый кадр" in r["text"]
    r = act(a, "pipe_result", {"kind": "video", "url": "/media/v.mp4", "model": "seedance-2-5"})
    assert r["intent"] == "pipe_saved_video" and actions(r)[0] == ("pipe_stage", "voice")


def test_video_without_artifacts_is_the_usual_video_path(make_assistant):
    a = make_assistant(llm=False)
    a.handle("котик в космосе", {}, SID)
    r = act(a, "pipe_stage", "video")
    assert blk(r, "models") and r["pipe_expect"] == "video"
    r = act(a, "pipe_result", {"kind": "video", "url": "/media/v.mp4"})
    assert r["intent"] == "pipe_saved_video"


def test_voice_from_speech_prompt_and_summary(make_assistant):
    a = make_assistant(llm=False)
    act(a, "pipe_stage", "prompt")
    act(a, "pipe_sub", "speech")
    a.handle("Диктор рассказывает о черепахах", {}, SID)
    r = act(a, "pipe_stage", "voice")
    assert r["intent"] == "pipe_voice" and r["ready"] and r["generate_model"] == "elevenlabs-v3"
    assert r["generate_prompt"] == arts(a)[-1]["text"] and ("pipe_voice_model", "gemini-3-1-flash-tts") in actions(r)
    r = act(a, "pipe_voice_model", "gemini-3-1-flash-tts")
    assert r["generate_model"] == "gemini-3-1-flash-tts"
    r = act(a, "pipe_result", {"kind": "audio", "url": "/media/voice.mp3"})
    assert r["intent"] == "pipe_saved_voice" and actions(r)[0] == ("pipe_summary", None)
    r = act(a, "pipe_summary")
    groups = {g["stage"]: g["items"] for g in blk(r, "pipe_arts")["groups"]}
    assert len(groups["prompt"]) == 1 and len(groups["voice"]) == 1
    assert "только в этом чате" in r["text"] and ("new_chat", None) in actions(r)


def test_voice_without_text_asks(make_assistant):
    a = make_assistant(llm=False)
    r = act(a, "pipe_stage", "voice")
    assert r["intent"] == "pipe_voice_ask"
    r = a.handle("Добро пожаловать в нашу пекарню", {}, SID)
    assert r["generate_prompt"] == "Добро пожаловать в нашу пекарню"


def test_result_outside_flow_is_silent(make_assistant):
    a = make_assistant(llm=False)
    a.handle("ну не знаю", {}, SID)
    r = act(a, "pipe_result", {"kind": "image", "url": "/media/x.png"})
    assert r.get("silent") and r["chips"] == []
    r = act(a, "pipe_result", {"kind": "image", "url": "javascript:alert(1)"})
    assert r.get("silent")


def test_bad_url_is_not_saved(make_assistant):
    a = make_assistant(llm=False)
    video_prompt(a)
    act(a, "pipe_sub", "hero")
    r = act(a, "pipe_result", {"kind": "image", "url": "javascript:alert(1)"})
    assert r.get("silent") and arts(a)[-1]["type"] == "videoPrompt"


def test_guest_is_asked_to_log_in(make_assistant):
    a = make_assistant(llm=False)
    r = act(a, "pipe_stage", "prompt", ctx={"_account": {"authed": False}})
    assert r["intent"] in ("pipe_stage", "login") or r.get("gate") == "login" or "войд" in r["text"].lower()


def test_junk_reasks_same_step(make_assistant):
    a = make_assistant(llm=False)
    act(a, "pipe_stage", "prompt")
    act(a, "pipe_sub", "video")
    r = a.handle("ооло", {}, SID)
    assert r["intent"] == "pipe_junk" and "Не совсем поняла" in r["text"] and not arts(a)


def test_artifacts_are_capped(make_assistant):
    from assistant import pipeline as PL
    ses = {}
    for i in range(PL.MAX_ARTS + 5):
        PL.save(ses, "prompt", "videoPrompt", "p", text=str(i))
    assert len(ses["arts"]) == PL.MAX_ARTS and ses["arts"][-1]["id"] == PL.MAX_ARTS + 5


def test_english_ui(make_assistant):
    a = make_assistant(llm=False)
    r = act(a, "pipe_menu", ctx={"lang": "en"})
    assert "only in this chat" in r["text"] and r["chips"][0]["label"] == "✍️ Prompt"


def test_pick_after_handoff_keeps_artifact_prompt(make_assistant):
    for brief in (False, True):
        a = make_assistant(llm=False, brief=brief)
        video_prompt(a)
        r = act(a, "pipe_sub", "hero")
        mid = blk(r, "models")["items"][0]["id"]
        r = act(a, "pick_model", mid)
        assert r.get("generate_model") == mid, r["intent"]
        assert "Character portrait" in (r.get("generate_prompt") or a.d.store.get(SID)["prompt"]), r["intent"]
        assert a.d.store.get(SID)["pipe"]["expect"] == "hero"
