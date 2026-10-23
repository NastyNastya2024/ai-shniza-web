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


def test_chip_in_types_and_window_right_away(make_assistant):
    a = make_assistant(llm=False)
    r = a.handle("выв", {}, SID)
    assert r["chips"][-1] == {"label": "🎞 Раскадровка", "action": "sb_start"}
    r = act(a, "sb_start")                      # без вопроса «пришлите сценарий» — сразу окно
    ch = blk(r, "choice")
    assert r["intent"] == "sb_idea" and ch and ch["custom_first"] and "сценарий" in ch["custom_label"]
    assert "Раскадровка" in r["text"] and "sb_exit" in actions(r) and "sb_noscript" not in actions(r)
    r = act(a, "sb_answer", {"q": "sb_idea", "text": SCRIPT, "style": "9"})   # в окно вставили сценарий
    assert r["intent"] == "sb_frames" and len(blk(r, "sb_frames")["frames"]) == 5 and "Сценарий получила" in r["text"]


def test_script_is_split_into_frames_and_sheet_prompt(make_assistant):
    a = make_assistant(llm=False)
    act(a, "sb_start")
    r = a.handle(SCRIPT, {}, SID)
    fb = blk(r, "sb_frames")
    assert r["intent"] == "sb_frames" and len(fb["frames"]) == 5
    assert fb["frames"][0]["time"] == "0.00–2.00" and fb["frames"][-1]["time"].endswith("10.00")
    # шаг 1 — только текст кадров: без настроек, цены и запуска картинок
    assert fb["settings"] == [] and "sheet" not in fb and "sb_setup" in actions(r)
    assert r.get("generate_model") != "nano-banana-pro"
    # без сценариста — кнопка «Расписать нейросетью» (текстовая модель студии)
    assert r["chips"][0]["action"] == "generate" and r["chips"][0]["primary"] and r["keep_assistant"]
    assert r["pipe_expect"] == "sb_frames" and '"frames"' in r["generate_prompt"]
    r = act(a, "sb_setup")                           # шаг 2 — оформление и запуск
    fb = blk(r, "sb_frames")
    assert r["intent"] == "sb_setup" and fb["frames"] == [] and fb["settings"] and "5 кадров" in fb["summary"]
    assert r["generate_model"] == "nano-banana-pro" and "generate_series" not in r and r["pipe_expect"] is None
    p = r["generate_prompt"]
    assert p.startswith("Professional film storyboard sheet: 5 panels") and "01 (0.00–2.00)" in p
    assert "диван падает с неба" in p and fb["sheet"]["cols"] * fb["sheet"]["rows"] >= 5
    assert r["chips"][0]["action"] == "generate" and r["chips"][0]["primary"]
    assert act(a, "sb_frames_view")["intent"] == "sb_frames"
    act(a, "sb_setup")
    assert act(a, "sb_back")["intent"] == "sb_frames"


def test_no_script_idea_window_then_frames(make_assistant):
    a = make_assistant(llm=False)
    act(a, "sb_start")
    r = act(a, "sb_noscript")
    ch = blk(r, "choice")
    assert r["intent"] == "sb_idea" and ch["action"] == "sb_answer" and len(ch["options"]) == 3
    assert [o["id"] for o in ch["extra"]["options"]] == ["6", "9", "12", "16", "20"]
    assert ch["custom_first"] and ch["custom_label"] == "Своя идея или сценарий"
    r = act(a, "sb_answer", {"q": "sb_idea", "text": "оранжевые кроссовки на улице", "style": "12"})
    fb = blk(r, "sb_frames")
    assert len(fb["frames"]) == 12 and any("оранжевые кроссовки" in f["text"] for f in fb["frames"])
    assert fb["frames"][0]["title"] == "Место действия" and fb["frames"][-1]["title"] == "Финал"
    assert len({f["text"] for f in fb["frames"]}) == 12


def test_short_text_at_intro_is_an_idea(make_assistant):
    a = make_assistant(llm=False)
    act(a, "sb_start")
    r = a.handle("реклама кофе, 6 кадров, вертикально", {}, SID)
    assert "по идее" in r["text"] and len(blk(r, "sb_frames")["frames"]) == 6
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
    assert "«ДИВАН С НЕБА»" in act(a, "sb_setup")["generate_prompt"]
    r = act(a, "sb_edit", {"path": "frames.1.camera", "value": "orbit-cw"})
    assert blk(r, "sb_frames")["frames"][1]["camera"] == "orbit-cw" and "Camera: " in act(a, "sb_setup")["generate_prompt"]
    r = act(a, "sb_edit", {"path": "frames.add.5"})
    assert len(blk(r, "sb_frames")["frames"]) == 6
    r = act(a, "sb_edit", {"path": "frames.del.5"})
    assert len(blk(r, "sb_frames")["frames"]) == 5
    r = act(a, "sb_edit", {"path": "set.labels", "value": "none"})
    assert r["intent"] == "sb_edit" and "No text, numbers or captions" in r["generate_prompt"]
    # «Переписать» без сценариста: новый текст вместо старого
    r = act(a, "sb_frame", {"n": 3, "text": "Закат над лужайкой, тёплый свет"})
    assert blk(r, "sb_frames")["frames"][2]["text"] == "Закат над лужайкой, тёплый свет" and "вашим" in r["text"]
    r = a.handle("кадр 2: пусть идёт дождь", {}, SID)
    assert r["intent"] == "sb_frame" and blk(r, "sb_frames")["frames"][1]["text"] == "пусть идёт дождь"


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
    assert act(a, "sb_back")["intent"] == "sb_idea"
    a.handle(SCRIPT, {}, SID)
    r = act(a, "sb_exit")
    assert "Кадры сохранила" in r["text"] and "sb_start" in actions(r)
    r = a.handle("сделай видео про кота", {}, SID)          # после выхода текст идёт обычным путём
    assert not r["intent"].startswith("sb_")
    r = act(a, "sb_start")
    assert r["intent"] == "sb_frames" and "Продолжаем" in r["text"] and "sb_start" in actions(r)
    assert act(a, "sb_start", "new")["intent"] == "sb_idea"


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
    assert fb["frames"][-1]["time"] == "5.00–10.00" and not r["degraded"] and "generate_model" not in r
    p = act(a, "sb_setup")["generate_prompt"]
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


def test_story_frames_without_llm_are_different_moments():
    idea = "романтичная история парень с девушкой встречаются на улице и парень врезается в девушку и у нее падают книги"
    assert SB.idea_beats(idea)[1:] == ["парень врезается в девушку", "у нее падают книги"]
    fr = SB.story_frames(idea, 12, 10, "ru")
    texts = [f["text"] for f in fr]
    assert len(fr) == 12 and len(set(texts)) == 12
    assert fr[0]["title"] == "Место действия" and "на улице" in fr[0]["text"] and "романтичное настроение" in fr[0]["text"]
    assert sum(1 for t in texts if idea in t) == 0
    assert any("падают книги" in t for t in texts) and any("Знакомство: девушка" in t for t in texts)
    assert abs(sum(f["seconds"] for f in fr) - 10) < 0.1
    assert len(SB.story_frames("кот жарит яичницу", 6, 10, "ru")) == 6


def test_model_writes_frames_via_studio_text_model(make_assistant):
    a = make_assistant(llm=False)
    act(a, "sb_start")
    act(a, "sb_noscript")
    r = act(a, "sb_answer", {"q": "sb_idea", "text": "кот жарит яичницу на рассвете", "style": "6"})
    assert r["pipe_expect"] == "sb_frames" and r.get("quiet_reply")
    reply = json.dumps({"title": "Кот-повар", "frames": [
        {"title": "Кухня на рассвете", "text": "Солнце заливает кухню, кот в фартуке у плиты.", "shot": "общий"},
        {"title": "Яйцо", "text": "Лапа разбивает яйцо о край сковороды.", "shot": "деталь"},
        {"title": "Шкворчит", "text": "Яичница шкворчит, кот довольно щурится.", "shot": "крупный"},
        {"title": "Подача", "text": "Кот ставит тарелку на стол и кланяется.", "shot": "средний"}]}, ensure_ascii=False)
    r = act(a, "pipe_result", {"kind": "text", "model": "deepseek-v3-1", "reply": "```json\n" + reply + "\n```"})
    fb = blk(r, "sb_frames")
    assert r["intent"] == "sb_frames" and [f["title"] for f in fb["frames"]][:2] == ["Кухня на рассвете", "Яйцо"]
    assert fb["title"] == "Кот-повар" and "расписала кадры" in r["text"]
    r = act(a, "pipe_result", {"kind": "text", "reply": "не json"})
    assert r.get("silent")


def test_rebuild_without_llm_extends_the_idea(make_assistant):
    a = make_assistant(llm=False)
    act(a, "sb_start")
    act(a, "sb_noscript")
    act(a, "sb_answer", {"q": "sb_idea", "text": "кот жарит яичницу", "style": "6"})
    r = a.handle("потом приходит собака и отбирает яичницу", {}, SID)
    texts = [f["text"] for f in blk(r, "sb_frames")["frames"]]
    assert any("собака" in t for t in texts) and not all(t.endswith("отбирает яичницу.") for t in texts)


def test_window_asks_for_hero_references(make_assistant):
    a = make_assistant(llm=False)
    r = act(a, "sb_start")
    refs = blk(r, "choice")["refs"]
    assert refs["items"] == [] and "прикрепите их фото" in refs["note"] and refs["attach"] == "📎 Прикрепить фото героя"
    ses = a.d.store.get(SID)
    ses["arts"] = [{"id": 1, "type": "hero", "title": "Портрет героя", "url": "/media/hero.png"},
                   {"id": 2, "type": "image", "title": "Сцена", "url": "/media/scene.png"},
                   {"id": 3, "type": "board", "title": "Лист", "url": "/media/board.png"}]
    a.d.store.set(SID, ses)
    r = act(a, "sb_start", "new")
    refs = blk(r, "choice")["refs"]
    assert [x["id"] for x in refs["items"]] == ["2", "1"] and "уже есть картинки" in refs["note"]
    act(a, "sb_answer", {"q": "sb_idea", "text": "парень с девушкой встречаются на улице", "style": "6", "refs": ["1", "99"]})
    r = act(a, "sb_setup")
    assert r["attach_urls"] == [{"src": "/media/hero.png", "name": "hero-1.png"}] and "Референсы героев из чата (1)" in r["text"]
