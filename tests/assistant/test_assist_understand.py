"""Понимание фраз (understand.py) и режимы «Рилс» / «Сериал» (modes.py).

GOLDEN — эталонный набор: фраза → что помощник должен понять. scripts/assistant_eval.py прогоняет его же
и печатает сравнение «было (только router) / стало»."""
import json

import pytest

from assistant import modes as MD
from assistant import understand as UN
from assistant.router import route

from assistant_testkit import FakeTransport

SID = "u1:modes"

# фраза → ожидаемая категория ответа
GOLDEN = [
    # переключить модель
    ("включи мне клода", "switch_model"), ("хочу поговорить с claude", "switch_model"), ("давай дипсик", "switch_model"),
    ("переключи на gpt", "switch_model"), ("включи гемини", "switch_model"), ("клод", "switch_model"),
    ("давай умного клода", "switch_model"), ("хочу пообщаться с чатгпт", "switch_model"), ("запусти deepseek", "switch_model"),
    ("можно claude?", "switch_model"),
    # вопрос-совет
    ("какая нейросеть лучше для видео", "question"), ("что лучше для картинок", "question"),
    ("чем kling отличается от seedance?", "question"), ("почему так долго генерирует", "error_help"),
    ("как сменить тему", "question"), ("посоветуй модель для музыки", "question"), ("какую выбрать для логотипа", "question"),
    ("что такое раскадровка", "question"), ("можно ли сделать видео со своим голосом", "question"),
    ("в чём разница между haiku и sonnet", "question"), ("какой нейросетью лучше оживить фото", "question"),
    # действие в интерфейсе
    ("сделай тёмную тему", "ui_do"), ("включи светлую тему", "ui_do"), ("хочу чёрный фон", "ui_do"),
    ("открой мои подключения", "ui_do"), ("покажи все нейросети", "ui_do"), ("начнём заново", "ui_do"),
    ("фиолетовая тема", "ui_do"),
    # режимы
    ("сделай сериал про кота-детектива", "start_mode"), ("хочу мини-сериал", "start_mode"), ("рилс по шагам про кофе", "start_mode"),
    ("режим рилс", "start_mode"), ("давай снимем веб-сериал", "start_mode"), ("рилс под ключ для кофейни", "start_mode"),
    # проверочные формулировки (не участвовали в настройке правил; 19/24 с первого раза, промахи закрыты)
    ("поставь мне claude sonnet", "switch_model"), ("переключись на дипсик пожалуйста", "switch_model"),
    ("хочу работать с gpt", "switch_model"), ("а какой генератор картинок самый реалистичный", "question"),
    ("что выбрать для озвучки?", "question"), ("почему видео без звука", "question"), ("seedance или kling для танца?", "question"),
    ("как поменять язык", "question"), ("где посмотреть мои работы", "question"), ("включи ночной режим", "ui_do"),
    ("сделай интерфейс светлым", "ui_do"), ("открой витрину", "ui_do"), ("очисти чат", "ui_do"),
    ("хочу снять сериал про двух роботов", "start_mode"), ("давай сделаем рилс от идеи до публикации", "start_mode"),
    ("нужен эпизод про кота", "start_mode"), ("помоги придумать идею для рилса", "start_mode"),
    ("а можно сделать мультик?", "question"),
    # обычные задачи — как раньше
    ("видео котика в космосе", "generate_task"), ("нарисуй логотип кофейни", "generate_task"),
    ("музыка для рилса 30 секунд", "generate_task"), ("сделай картинку заката над морем", "generate_task"),
    ("сделай видео как кот играет на пианино", "generate_task"), ("анимируй мое фото", "generate_task"),
    ("трек в стиле lo-fi", "generate_task"), ("напиши пост для инстаграма", "generate_task"), ("логотип для пекарни", "generate_task"),
    ("включи музыку", "generate_task"),
    # безопасность и справки — как раньше
    ("какая погода в Москве", "off_topic"), ("сколько стоит видео", "question"),
]


def category(r):
    it = r["intent"]
    if it in ("switch_model",):
        return "switch_model"
    if it in ("question", "question_models", "ui_help"):
        return "question"
    if it == "ui_do":
        return "ui_do"
    if it.startswith("mode_"):
        return "start_mode"
    return it


def act(a, typ, value=None, sid=SID, ctx=None):
    action = {"type": typ}
    if value is not None:
        action["value"] = value
    return a.handle("", ctx or {}, sid, action=action)


def actions(r):
    return [c["action"] for c in r["chips"]]


@pytest.mark.parametrize("phrase,want", GOLDEN)
def test_golden_phrases(make_assistant, phrase, want):
    a = make_assistant(llm=False)
    r = a.handle(phrase, {}, "g:" + phrase)
    assert category(r) == want, (phrase, r["intent"])


def test_golden_accuracy_vs_router_only(make_assistant, cards):
    """Только router (как было): фразы «включи клода», вопросы, тема, режимы — не понимал."""
    c, _ = cards
    titles = {x.id: x.title for x in c.values()}
    old = {"generate_task": "generate_task", "off_topic": "off_topic", "error_help": "error_help", "ui_help": "question", "compare": "question"}
    hits = sum(1 for p, w in GOLDEN if old.get(route(p, {}, {}, titles).name) == w)
    assert hits / len(GOLDEN) < 0.4


def test_switch_model_picks_text_model_and_offers_smarter(make_assistant):
    a = make_assistant(llm=False)
    r = a.handle("включи мне клода", {}, SID)
    assert r["intent"] == "switch_model" and r["generate_model"] == "claude-4-5-haiku"
    assert r["text"].startswith("Включила Claude Haiku 4.5") and "Sonnet" in r["text"]
    assert ("pick_model", "claude-sonnet-5") in [(c["action"], c.get("value")) for c in r["chips"]]
    r = a.handle("давай умного клода", {}, SID + "2")
    assert r["generate_model"] == "claude-sonnet-5"


def test_question_best_for_video_shows_models_not_generation(make_assistant):
    a = make_assistant(llm=False)
    r = a.handle("какая нейросеть лучше для видео", {}, SID)
    assert r["intent"] == "question_models" and r["models"]
    assert "лучше всего" in r["text"]


def test_theme_is_switched_by_the_assistant(make_assistant):
    a = make_assistant(llm=False)
    r = a.handle("сделай тёмную тему", {}, SID)
    assert r["ui_do"] == {"action": "set_theme", "value": "black"}
    assert {c["value"] for c in r["chips"]} == {"white", "violet", "light"}
    r = a.handle("открой мои подключения", {}, SID)
    assert r["ui_do"] == {"action": "open_panel", "value": "mcp"}


def test_reels_mode_full_path_without_llm(make_assistant):
    a = make_assistant(llm=False)
    r = a.handle("рилс по шагам про утро бариста в кофейне", {}, SID)
    assert r["intent"] == "mode_reels_script" and "шаг 2 из 8" in r["text"]
    assert "каркас" in r["text"]                                   # без нейросети — каркас сценария
    script = next(b for b in r["blocks"] if b["type"] == "mode_text")["text"]
    assert "бариста" in script and "Хук" in script
    # правка сценария своими словами — на месте
    r = a.handle("сделай хук смешнее", {}, SID)
    assert r["intent"] == "mode_reels_script" and "Переписала" in r["text"]
    # вопрос посреди режима — ответ и «вернуться к шагу»
    r = a.handle("какая нейросеть лучше для видео", {}, SID)
    assert r["intent"] == "question_models" and "mode_resume" in actions(r)
    r = act(a, "mode_resume")
    assert r["intent"] == "mode_reels_script"
    # дальше — раскадровка: работу делает storyboard.py, режим не теряется
    r = act(a, "mode_next")
    assert r["intent"] == "mode_reels_board" and r["chips"][0]["action"] == "mode_go"
    r = act(a, "mode_go", "board")
    assert r["intent"].startswith("sb_") and "mode_resume" in actions(r)
    # готовый лист раскадровки (pipe_result) — режим сам идёт к шагу «Видео»
    ses = a.d.store.get(SID)
    ses["pipe"]["expect"] = "board"
    a.d.store.set(SID, ses)
    r = act(a, "pipe_result", {"kind": "image", "url": "/m/b1.png", "urls": ["/m/b1.png", "/m/b2.png"], "series": True})
    assert r["intent"] == "mode_reels_video" and "Шаг готов" in r["text"] and "Раскадровка готова" in r["text"]
    # шаги без своей генерации ведут в подключения MCP нужной категории
    act(a, "mode_next")
    r = act(a, "mode_next")
    assert r["intent"] == "mode_reels_edit" and ("open_mcp", "edit") in [(c["action"], c.get("value")) for c in r["chips"]]
    r = act(a, "mode_next")
    assert r["intent"] == "mode_reels_viral" and "Higgsfield" in r["text"]
    r = act(a, "mode_next")
    assert r["intent"] == "mode_reels_publish"
    r = act(a, "mode_exit", "done")
    assert r["intent"] == "mode_exit" and "готово" in r["text"] and a.d.store.get(SID)["mode"] is None


def test_other_task_inside_mode_keeps_resume_chip(make_assistant):
    a = make_assistant(llm=False)
    a.handle("режим рилс", {}, SID)
    r = a.handle("утро бариста в кофейне", {}, SID)                 # шаг «Идея» — текст идёт в режим
    assert r["intent"] == "mode_reels_script"
    act(a, "mode_next")                                             # шаг «Раскадровка» ждёт кнопку
    r = a.handle("нарисуй логотип кофейни", {}, SID)               # другая задача — обычным путём
    assert not r["intent"].startswith("mode_") and "mode_resume" in actions(r)
    assert MD.state(a.d.store.get(SID))["step"] == 2


def test_series_heroes_portraits_and_next_episode(make_assistant):
    a = make_assistant(llm=False)
    r = a.handle("сделай сериал про кота-детектива в дождливом Париже", {}, SID)
    assert r["intent"] == "mode_series_heroes"
    assert [c["value"] for c in r["chips"] if c["action"] == "mode_go"] == ["hero:0"]
    r = act(a, "mode_go", "hero:0")
    assert r["intent"] == "pipe_hero" or r["models"]                # обычный подбор модели под портрет героя
    r = act(a, "pipe_result", {"kind": "image", "url": "/m/hero.png"})
    assert r["intent"] == "mode_series_episode" and "серия 1" in r["text"]
    ses = a.d.store.get(SID)
    assert ses["mode"]["data"]["portraits"] == [0] and any(x["type"] == "hero" for x in ses["arts"])
    act(a, "mode_next"), act(a, "mode_next")
    r = act(a, "mode_next")
    assert r["intent"] == "mode_series_next"
    r = act(a, "mode_episode")
    assert r["intent"] == "mode_series_episode" and "серия 2" in r["text"]
    assert len(a.d.store.get(SID)["mode"]["data"]["episodes"]) == 1


def test_new_mode_while_another_is_running_asks_first(make_assistant):
    a = make_assistant(llm=False)
    a.handle("рилс по шагам про утро бариста в кофейне", {}, SID)
    r = a.handle("сделай сериал про кота-детектива", {}, SID)
    assert r["intent"] == "mode_switch_ask" and actions(r) == ["mode_start", "mode_resume"]
    assert MD.state(a.d.store.get(SID))["id"] == "reels"
    r = act(a, "mode_start", r["chips"][0]["value"])
    assert r["intent"].startswith("mode_series")


def test_mode_needs_login_for_guest(make_assistant):
    a = make_assistant(llm=False)
    r = a.handle("хочу мини-сериал", {"_account": {"authed": False}}, SID)
    assert r["intent"] != "mode_series_world"


def test_llm_layer_understands_what_rules_cannot(make_assistant):
    reply = json.dumps({"intent": "switch_model", "model": "gemini-3-5-flash", "confidence": 0.9})
    a = make_assistant(transport=FakeTransport(omniroute=[("ok", reply)]), understand_llm=True)
    r = a.handle("хочу пообщаться с нейросетью от гугла", {}, SID)
    assert r["intent"] == "switch_model" and r["generate_model"] == "gemini-3-5-flash"


def test_llm_layer_cannot_invent_models(make_assistant):
    reply = json.dumps({"intent": "switch_model", "model": "super-gpt-99", "confidence": 0.95})
    a = make_assistant(transport=FakeTransport(omniroute=[("ok", reply)]), understand_llm=True)
    r = a.handle("хочу пообщаться с нейросетью от гугла", {}, SID)
    assert r["intent"] != "switch_model"


def test_question_answer_from_studio_facts(make_assistant):
    reply = json.dumps({"answer": "Kling плавнее двигает камеру, Seedance дешевле и сразу со звуком.", "models": ["seedance-2-5", "nope"]})
    a = make_assistant(transport=FakeTransport(omniroute=[("ok", reply)]))
    r = a.handle("чем kling отличается от seedance?", {}, SID)
    assert r["intent"] == "question" and "Seedance дешевле" in r["text"]
    assert [c["value"] for c in r["chips"] if c["action"] == "pick_model"] == ["seedance-2-5"]


def test_idea_with_question_mark_on_idea_step_is_an_idea(make_assistant):
    a = make_assistant(llm=False)
    a.handle("режим рилс", {}, SID)
    r = a.handle("Кот учится кататься на скейте?", {}, SID)
    assert r["intent"] == "mode_reels_script"


def test_fast_rules_unit():
    assert UN.fast("включи мне клода", {"claude-4-5-haiku": 1, "claude-sonnet-5": 1})["model"] == "claude-4-5-haiku"
    assert UN.fast("какая нейросеть лучше для видео")["intent"] == "question"
    assert UN.fast("сделай видео котика") is None
    assert UN.fast("сделай тёмную тему")["value"] == "black"
    assert UN.fast("сделай сериал про кота")["mode"] == "series"
