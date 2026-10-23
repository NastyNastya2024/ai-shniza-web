"""Режим «Раскадровка»: объяснение → сценарий (или идея) → список кадров → лист-сетка или серия картинок."""
import json

from assistant import storyboard as SB
from assistant_testkit import FakeTransport

SID = "u1:sb"
SCRIPT = ("Сцена 1. Белый диван падает с неба на зелёный газон.\n"
          "Сцена 2. Диван ударяется о траву, воздух волной расходится по лужайке.\n"
          "Сцена 3. Вокруг дивана прилетают и соединяются деревянные панели пола.\n"
          "Сцена 4. Поднимаются стены, встают панорамные окна.\n"
          "Сцена 5. Финал: готовая гостиная с видом на сад.")


def act(a, typ, value=None, sid=SID, ctx=None):
    action = {"type": typ}
    if value is not None:
        action["value"] = value
    return a.handle("", ctx or {}, sid, action=action)


def blk(r, typ):
    return next((x for x in r["blocks"] if x["type"] == typ), None)


def actions(r):
    return [c["action"] for c in r["chips"]]


def test_chip_in_types_and_intro_asks_for_script(make_assistant):
    a = make_assistant(llm=False)
    r = a.handle("выв", {}, SID)
    assert r["chips"][-1] == {"label": "🎞 Раскадровка", "action": "sb_start"}
    r = act(a, "sb_start")
    assert r["intent"] == "sb_intro"
    assert "серия картинок" in r["text"] and "Пришлите сценарий" in r["text"] and "одним листом" in r["text"]
    assert actions(r)[0] == "sb_noscript"


def test_script_is_split_into_frames_and_sheet_prompt(make_assistant):
    a = make_assistant(llm=False)
    act(a, "sb_start")
    r = a.handle(SCRIPT, {}, SID)
    fb = blk(r, "sb_frames")
    assert r["intent"] == "sb_frames" and len(fb["frames"]) == 5
    assert fb["frames"][0]["time"] == "0.00–2.00" and fb["frames"][-1]["time"].endswith("10.00")
    assert r["generate_model"] == "nano-banana-pro" and "generate_series" not in r
    p = r["generate_prompt"]
    assert p.startswith("Professional film storyboard sheet: 5 panels") and "01 (0.00–2.00)" in p
    assert "диван падает с неба" in p and fb["sheet"]["cols"] * fb["sheet"]["rows"] >= 5
    assert r["chips"][0]["action"] == "generate" and r["chips"][0]["primary"]


def test_no_script_idea_window_then_frames(make_assistant):
    a = make_assistant(llm=False)
    act(a, "sb_start")
    r = act(a, "sb_noscript")
    ch = blk(r, "choice")
    assert r["intent"] == "sb_idea" and ch["action"] == "sb_answer" and len(ch["options"]) == 3
    assert [o["id"] for o in ch["extra"]["options"]] == ["6", "9", "12", "16", "20"]
    r = act(a, "sb_answer", {"q": "sb_idea", "text": "оранжевые кроссовки на улице", "style": "12"})
    fb = blk(r, "sb_frames")
    assert len(fb["frames"]) == 12 and "оранжевые кроссовки" in fb["frames"][0]["text"]
    assert fb["frames"][0]["title"] == "Хук" and fb["frames"][-1]["title"] == "Финал"


def test_short_text_at_intro_is_an_idea(make_assistant):
    a = make_assistant(llm=False)
    act(a, "sb_start")
    r = a.handle("реклама кофе, 6 кадров, вертикально", {}, SID)
    assert "похоже на идею" in r["text"] and len(blk(r, "sb_frames")["frames"]) == 6
    assert SB.state(a.d.store.get(SID))["aspect"] == "9:16"


def test_text_trigger_with_script(make_assistant):
    a = make_assistant(llm=False)
    r = a.handle("Сделай раскадровку:\n" + SCRIPT, {}, SID)
    assert r["intent"] == "sb_frames" and len(blk(r, "sb_frames")["frames"]) == 5


def test_edits_in_place(make_assistant):
    a = make_assistant(llm=False)
    act(a, "sb_start")
    a.handle(SCRIPT, {}, SID)
    r = act(a, "sb_edit", {"path": "frames.0.title", "value": "Диван с неба"})
    assert r["intent"] == "sb_edit" and blk(r, "sb_frames")["frames"][0]["title"] == "Диван с неба"
    assert "«ДИВАН С НЕБА»" in r["generate_prompt"]
    r = act(a, "sb_edit", {"path": "frames.1.camera", "value": "orbit-cw"})
    assert blk(r, "sb_frames")["frames"][1]["camera"] == "orbit-cw" and "Camera: " in r["generate_prompt"]
    r = act(a, "sb_edit", {"path": "frames.add.5"})
    assert len(blk(r, "sb_frames")["frames"]) == 6
    r = act(a, "sb_edit", {"path": "frames.del.5"})
    assert len(blk(r, "sb_frames")["frames"]) == 5
    r = act(a, "sb_edit", {"path": "set.labels", "value": "none"})
    assert "No text, numbers or captions" in r["generate_prompt"]
    r = act(a, "sb_frame", {"n": 3, "text": "добавь закат"})
    assert "добавь закат" in blk(r, "sb_frames")["frames"][2]["text"]
    r = a.handle("кадр 2: пусть идёт дождь", {}, SID)
    assert r["intent"] == "sb_frame" and "пусть идёт дождь" in blk(r, "sb_frames")["frames"][1]["text"]


def test_series_format_gives_one_prompt_per_frame(make_assistant):
    a = make_assistant(llm=False)
    act(a, "sb_start")
    a.handle(SCRIPT, {}, SID)
    r = act(a, "sb_edit", {"path": "set.format", "value": "series"})
    s = r["generate_series"]
    assert len(s) == 5 and s[0]["n"] == 1 and "Storyboard frame 1 of 5" in s[0]["prompt"]
    assert r["chips"][0]["action"] == "generate_series" and "5 кадров" in r["chips"][0]["label"]
    assert r["generate_model"] == "nano-banana-2" and r["generate_params"]["aspect_ratio"] == "16:9"
    assert "labels" not in [x["key"] for x in blk(r, "sb_frames")["settings"]]


def test_series_is_limited_and_balance_counts_all_frames(make_assistant):
    a = make_assistant(llm=False)
    act(a, "sb_start")
    act(a, "sb_noscript")
    r = act(a, "sb_answer", {"q": "sb_idea", "option": "ad", "style": "16"})
    r = act(a, "sb_edit", {"path": "set.format", "value": "series"})
    assert "до 12 кадров" in r["text"] and "generate_series" not in r          # 16 кадров — остаёмся листом
    act(a, "sb_edit", {"path": "frames.del.0"})
    ctx = {"_account": {"authed": True, "available_kop": 1}}
    for _ in range(3):
        act(a, "sb_edit", {"path": "frames.del.0"}, ctx=ctx)
    r = act(a, "sb_edit", {"path": "set.format", "value": "series"}, ctx=ctx)
    assert len(r["generate_series"]) == 12
    assert r["chips"][0]["action"] == "open_topup" and not r["ready"]
    r = act(a, "sb_start", ctx={"_account": {"authed": False}})
    assert r["gate"] == "login"


def test_back_exit_and_resume(make_assistant):
    a = make_assistant(llm=False)
    act(a, "sb_start")
    a.handle(SCRIPT, {}, SID)
    assert act(a, "sb_back")["intent"] == "sb_intro"
    a.handle(SCRIPT, {}, SID)
    r = act(a, "sb_exit")
    assert "Кадры сохранила" in r["text"] and "sb_start" in actions(r)
    r = a.handle("сделай видео про кота", {}, SID)          # после выхода текст идёт обычным путём
    assert not r["intent"].startswith("sb_")
    r = act(a, "sb_start")
    assert r["intent"] == "sb_frames" and "Продолжаем" in r["text"] and "sb_start" in actions(r)
    assert act(a, "sb_start", "new")["intent"] == "sb_intro"


def test_llm_path(make_assistant):
    board = {"title": "Гостиная из неба", "bible": "A large white designer sofa, green lawn, walnut and travertine interior",
             "frames": [{"title": "Диван с неба", "title_en": "THE SOFA FROM THE SKY", "text": "Белый диван падает на газон.",
                         "shot": "общий план", "camera": "crane-down", "seconds": 1,
                         "prompt": "A large white designer sofa falls vertically from the blue sky toward a green lawn"},
                        {"title": "Удар", "title_en": "THE GRAVITY IMPACT", "text": "Диван ударяется о траву.",
                         "shot": "низкий ракурс", "camera": "", "seconds": 1,
                         "prompt": "The sofa hits the lawn, cushions compress, an air wave spreads across the grass"},
                        {"title": "Финал", "title_en": "THE LIVING ROOM HERO", "text": "Готовая гостиная.",
                         "shot": "общий", "camera": "zzz", "seconds": 2,
                         "prompt": "Wide frontal hero shot of a finished luxury living room with a panoramic garden view"}]}
    tr = FakeTransport(omniroute=[("ok", json.dumps(board, ensure_ascii=False))])
    a = make_assistant(transport=tr)
    act(a, "sb_start")
    r = a.handle(SCRIPT, {}, SID)
    fb = blk(r, "sb_frames")
    assert fb["title"] == "Гостиная из неба" and [f["camera"] for f in fb["frames"]] == ["crane-down", "", ""]
    assert fb["frames"][-1]["time"] == "5.00–10.00"
    p = r["generate_prompt"]
    assert "«THE SOFA FROM THE SKY»" in p and "walnut and travertine" in p


def test_validators_and_grid():
    try:
        SB.v_board({"frames": [{"title": "x", "prompt": "short"}]})
        raise AssertionError("must fail")
    except ValueError:
        pass
    assert SB.grid(20, "1:1", ["1:1", "3:4", "4:3", "9:16", "16:9"], "title")[:2] in ((4, 5), (5, 4))
    c, r, ar = SB.grid(6, "16:9", ["1:1", "3:2", "2:3"], "title")
    assert c * r >= 6 and ar in ("1:1", "3:2", "2:3")
    assert SB.is_script(SCRIPT) and not SB.is_script("реклама кофе")
