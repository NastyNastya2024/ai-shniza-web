"""Подсказки дерева не бывают пустыми, вопросы про MCP идут в подключение."""
import random
import re

import pytest

from assistant.tree import HintTree, chips_for, present_hint


@pytest.fixture(scope="module")
def tree():
    return HintTree.load_json()

FORBIDDEN = re.compile(r"основной путь|финал истории|шаг\s*\d|\(выполнить задачу\)", re.I)


def _blob(r):
    labels = " ".join(c.get("label") or "" for c in r.get("chips") or [])
    return (r.get("text") or "") + " " + labels


def _alive(r):
    return bool((r.get("text") or "").strip() or r.get("blocks") or r.get("chips"))


def test_present_hint_hides_internal_words():
    assert present_hint("↩ Основной путь: Финал истории") is None
    assert present_hint("Дальше: Финал истории") is None
    assert present_hint("Попробовать") is None
    assert present_hint("(выполнить задачу)") is None
    assert present_hint("↩ Настроить интерфейс: шаг 1", "подключение MCP") == "↩ Вернуться к «подключение MCP»"
    nxt = present_hint("↩ Основной путь: Сравнить рядом")
    assert nxt == "↩ Дальше: Сравнить рядом"


def test_every_shown_hint_has_action(make_assistant, tree):
    a = make_assistant(llm=False, tree=tree)
    for sid, story in tree.stories.items():
        if story.get("status", "active") != "active":
            continue
        for i in range(len(story.get("steps") or []) + 1):
            for c in chips_for(a, tree.step_hints(sid, i), {"story": sid, "step": i}, "ru"):
                assert c.get("action") and c.get("label")
                assert not FORBIDDEN.search(c["label"])


def test_mcp_question_asks_task_then_advises_vidiq(make_assistant, tree):
    a = make_assistant(llm=False, tree=tree, dialog_v2=True)
    ctx = {"_account": {"authed": True, "available_kop": 10 ** 7}}
    r = a.handle("какой вид MCP мне выбрать?", ctx, "mcp1")
    assert r["intent"] == "mcp"
    assert "Для какой задачи" in r["text"]
    assert not any(b.get("type") == "models" for b in r.get("blocks") or [])
    assert "Настроить интерфейс" not in _blob(r)
    assert _alive(r)
    r = a.handle("", ctx, "mcp1", action={"type": "mcp_goal", "value": "trends"})
    assert "vidIQ" in r["text"]
    assert any(c.get("action") == "open_mcp" and c.get("value") == "vidiq" for c in r["chips"])
    r = a.handle("", ctx, "mcp1", action={"type": "open_mcp", "value": "vidiq"})
    assert r["intent"] == "mcp_steps"
    assert r["ui_do"]["action"] == "open_mcp" and r["ui_do"]["value"] == "vidiq"
    assert "разрешите доступ" in r["text"].lower()
    assert _alive(r)


def test_mcp_after_reels_skips_the_question(make_assistant, tree):
    a = make_assistant(llm=False, tree=tree, dialog_v2=True)
    ctx = {"_account": {"authed": True, "available_kop": 10 ** 7}}
    a.handle("хочу сделать рилс который залетит про кофейню", ctx, "mcp2")
    r = a.handle("какой вид MCP мне выбрать?", ctx, "mcp2")
    assert r["intent"] == "mcp"
    assert "vidIQ" in r["text"]
    assert "Для какой задачи" not in r["text"]


def test_mcp_phrases_match_connect_not_ui(tree):
    for phrase in ("какой вид MCP мне выбрать?", "как подключить vidIQ", "зачем нужен MCP"):
        sid, _score = tree.match(phrase)
        assert sid and tree.vec_of[sid][1]["id"] == "INT.CONNECT", phrase
    sid, _score = tree.match("смени тему на тёмную")
    assert sid and tree.vec_of[sid][1]["id"] == "HLP.UI"


def test_theme_change_has_no_mcp_hints(make_assistant, tree):
    a = make_assistant(llm=False, tree=tree)
    r = a.handle("смени тему на тёмную", {"_account": {"authed": True, "available_kop": 10 ** 7}}, "th")
    assert r["intent"] == "ui_do"
    assert not any(c.get("action") == "open_mcp" for c in r.get("chips") or [])
    assert "MCP" not in _blob(r)


def test_guest_mcp_asks_login(make_assistant, tree):
    a = make_assistant(llm=False, tree=tree)
    r = a.handle("какой вид MCP мне выбрать?", {"_account": {"authed": False}}, "g")
    assert r["gate"] == "login"
    assert r["chips"][0]["action"] == "login"


def test_claude_not_required_for_mcp(make_assistant, tree):
    a = make_assistant(llm=False, tree=tree)
    r = a.handle("нужно ли подключать Claude для MCP", {"_account": {"authed": True, "available_kop": 1}}, "c")
    assert "не нужно" in r["text"].lower()
    assert not any(c.get("action") == "open_mcp" for c in r.get("chips") or [])


def test_connected_offers_last_result(make_assistant, tree):
    a = make_assistant(llm=False, tree=tree)
    ctx = {"_account": {"authed": True, "available_kop": 10 ** 7}}
    a.handle("", ctx, "ok", action={"type": "media_add", "value": {"kind": "video", "url": "/w/9", "name": "reel.mp4"}})
    r = a.handle("", ctx, "ok", action={"type": "mcp_connected", "value": {"id": "vidiq", "name": "vidIQ"}})
    assert "последн" in r["text"].lower()
    assert _alive(r)


def test_random_story_hints_are_not_empty(make_assistant, tree):
    a = make_assistant(llm=False, tree=tree, brief=False)
    ctx = {"_account": {"authed": True, "available_kop": 10 ** 7}}
    ids = [i for i, o in tree.stories.items() if o.get("status", "active") == "active"]
    for sid in random.Random(1).sample(ids, 30):
        hints = tree.step_hints(sid, 0)
        chips = chips_for(a, hints, {"story": sid, "step": 0}, "ru")
        for c in chips:
            r = a.handle("", ctx, "s-" + sid, action={"type": c["action"], "value": c.get("value")})
            assert _alive(r), (sid, c)
            assert not FORBIDDEN.search(_blob(r)), (sid, c, _blob(r)[:160])


def test_back_hint_shows_the_step(make_assistant, tree):
    a = make_assistant(llm=False, tree=tree, brief=False)
    ctx = {"_account": {"authed": True, "available_kop": 10 ** 7}}
    r = a.handle("покажи клиенту 3 варианта кухни в разных стилях", ctx, "back")
    second = next(c for c in r["chips"] if str(c.get("label") or "").startswith("Стили:"))
    r = a.handle("", ctx, "back", action={"type": "tree_hint", "value": second.get("value")})
    back = next(c for c in r["chips"] if str(c.get("label") or "").startswith("↩"))
    r2 = a.handle("", ctx, "back", action={"type": back["action"], "value": back.get("value")})
    assert "Продолжаем" not in (r2.get("text") or "")
    assert _alive(r2)
    assert not FORBIDDEN.search(_blob(r2))
