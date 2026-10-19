"""Режим «Рилс» снят: кнопка и вход по тексту больше не открывают пошаговый флоу."""


SID = "u1:reels-off"


def test_no_reel_chip_on_type_offer(make_assistant):
    a = make_assistant()
    r = a.handle("привет", {}, SID)
    assert "reel_start" not in {c["action"] for c in r.get("chips") or []}


def test_reel_start_falls_back_to_ask_type(make_assistant):
    a = make_assistant()
    r = a.handle("", {}, SID, action={"type": "reel_start"})
    assert r["intent"] == "ask_type"
    assert "reel_start" not in {c["action"] for c in r.get("chips") or []}


def test_reel_text_does_not_enter_mode(make_assistant):
    a = make_assistant()
    r = a.handle("сделай вирусный рилс про кота", {}, SID)
    assert r.get("intent") != "reel_idea"
    assert (a.d.store.get(SID) or {}).get("assist_mode") != "reel"
