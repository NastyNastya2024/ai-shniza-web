"""cards / params / recommend / render / errors / ui_help — чистые функции без LLM."""
import pytest

from assistant import params as P
from assistant.cards import Card, CardError, load_cards, validate
from assistant.errors import classify, explain
from assistant.recommend import price_value, recommend
from assistant.render import MAX_CHARS, MAX_LINES, limit, response
from assistant.ui_help import HELP


# ---------------- cards
def test_cards_load_and_valid(cards):
    c, nb = cards
    assert len(c) == 19
    assert validate(c.values()) == []
    assert all(k in nb for k in ("image", "edit", "music", "sfx", "video"))


def test_cards_warn_on_unknown_ids(cards):
    c, _ = cards
    warns = validate(c.values(), integrated_ids=["veo-3-1"])
    assert len(warns) == 18


def test_card_validation_errors():
    good = dict(id="x", title="X", kind="image", modes=["t2i"], tags=[], strengths={"ru": "a"}, limits={"ru": "b"},
                speed={"ru": "c"}, rank=1, params={}, ask_first=[], prompt_style="s")
    validate([Card(**good)])
    for bad in ({"kind": "3d"}, {"modes": ["zzz"]}, {"strengths": {"en": "a"}}, {"ask_first": ["aspect_ratio"]},
                {"params": {"aspect_ratio": ["1:1"]}}, {"prompt_style": ""}):
        with pytest.raises(CardError):
            validate([Card(**{**good, **bad})])


# ---------------- params
@pytest.mark.parametrize("text,key,val", [
    ("вертикальное видео", "aspect_ratio", "9:16"), ("для рилс", "aspect_ratio", "9:16"), ("16:9 ролик", "aspect_ratio", "16:9"),
    ("квадратная картинка", "aspect_ratio", "1:1"), ("10 секунд", "duration", 10), ("5с", "duration", 5),
    ("2 минуты музыки", "duration", 120), ("в 4к", "resolution", "4k"), ("1080p", "resolution", "1080p"),
    ("без звука", "generate_audio", False), ("со звуком", "generate_audio", True), ("инструментал", "instrumental", True),
    ("vertical 8 sec", "aspect_ratio", "9:16"),
])
def test_extract(text, key, val):
    assert P.extract(text)[key] == val


def test_fit_only_whitelisted(cards):
    c, _ = cards
    veo = c["veo-3-1"]
    params, adj = P.fit({"aspect_ratio": "1:1", "duration": 10, "resolution": "4k"}, veo)
    assert params == {}  # у Veo в карточке 1:1 нет, duration/resolution не выбираются
    params, _ = P.fit({"aspect_ratio": "9:16"}, veo)
    assert params == {"aspect_ratio": "9:16"}
    assert P.missing(veo, {}) == ["aspect_ratio"]
    assert P.missing(veo, params) == []


def test_fit_nearest_duration():
    card = Card(id="x", title="X", kind="video", modes=["t2v"], tags=[], strengths={"ru": "a"}, limits={"ru": "b"},
                speed={"ru": "c"}, rank=1, params={"duration": [5, 10]}, ask_first=[], prompt_style="s")
    params, adj = P.fit({"duration": 8}, card)
    assert params == {"duration": 10} and adj == [{"param": "duration", "asked": 8, "got": 10}]
    assert P.validate(card, {"duration": 7, "evil": "x"}) == {}
    assert P.validate(card, {"duration": 5}) == {"duration": 5}


# ---------------- recommend
def test_price_value():
    assert price_value("45 ₽") == 45 and price_value("бесплатно") == 0 and price_value(None) is None
    assert price_value("1 200,5 ₽") == 1200.5


def test_recommend_at_least_two_each_kind(cards, price_fn):
    c, nb = cards
    for kind in ("video", "image", "edit", "music", "sfx"):
        pick = recommend(c, kind, [], False, None, price_fn, nb)
        assert len(pick.cards) >= 2, kind
        assert len({x.id for x in pick.cards}) == len(pick.cards)


def test_recommend_neighbors_mark_not_exact(cards, price_fn):
    c, nb = cards
    pick = recommend(c, "sfx", ["звуковые эффекты"], False, None, price_fn, nb)
    assert pick.cards[0].id == "stable-audio-2-5"
    assert pick.cards[1].kind == "music"


def test_recommend_needs_tags(cards, price_fn):
    c, nb = cards
    assert recommend(c, "image", ["логотип", "типографика"], False, None, price_fn, nb).cards[0].id == "ideogram-v3-turbo"
    assert recommend(c, "video", ["кино", "речь"], False, None, price_fn, nb).cards[0].id == "veo-3-1"


def test_recommend_health_filter(cards, price_fn):
    c, nb = cards
    down = {"veo-3-1", "veo-3-1-fast"}
    pick = recommend(c, "video", ["кино", "речь"], False, lambda m: m not in down, price_fn, nb)
    assert not down & {x.id for x in pick.cards}
    assert len(pick.cards) >= 2


def test_recommend_image_modes(cards, price_fn):
    c, nb = cards
    no_img = recommend(c, "video", ["оживить фото"], False, None, price_fn, nb, n=10, with_cheap=False)
    assert not {"gen4-turbo", "grok-imagine-video-1-5"} & {x.id for x in no_img.cards}
    with_img = recommend(c, "video", ["оживить фото"], True, None, price_fn, nb)
    assert all("i2v" in x.modes for x in with_img.cards)


def test_recommend_adds_cheap_third(cards, price_fn):
    c, nb = cards
    pick = recommend(c, "video", ["кино"], False, None, price_fn, nb)
    assert len(pick.cards) == 3 and pick.cards[2].id == "p-video"


def test_recommend_health_fn_crash_does_not_hide_catalog(cards, price_fn):
    c, nb = cards

    def boom(_):
        raise RuntimeError("redis down")

    assert len(recommend(c, "image", [], False, boom, price_fn, nb).cards) >= 2


# ---------------- render
def test_render_limits():
    lines = [f"строка {i} " + "x" * 50 for i in range(40)]
    out = limit(lines)
    assert len([x for x in out.splitlines() if x.strip()]) <= MAX_LINES
    assert len(out) <= MAX_CHARS
    big = limit(["y" * 900, "z" * 900])
    assert big == "y" * 900


def test_response_dedupes_and_caps_chips():
    chips = [{"label": "a", "action": "more"}] * 3 + [{"label": str(i), "action": "pick_model", "value": i} for i in range(9)]
    r = response(["x"], chips)
    assert len(r["chips"]) == 5 and [c["action"] for c in r["chips"]].count("more") == 1


# ---------------- errors
@pytest.mark.parametrize("ctx,code", [
    ({"last_error": "insufficient_funds"}, "insufficient_funds"), ({"last_http_status": 402}, "insufficient_funds"),
    ({"last_http_status": 401}, "auth_required"), ({"last_http_status": 429}, "rate_limited"),
    ({"last_error": "channel_unavailable"}, "channel_unavailable"), ({"last_error": "not_configured"}, "channel_unavailable"),
    ({"last_error": "timeout"}, "timeout"), ({"last_error": "moderation"}, "moderation"),
    ({"last_error": "free_limit"}, "free_limit"), ({"last_error": "free_queue_full"}, "queued_free"),
    ({"job_status": "queued"}, "queued"), ({"job_status": "requeued"}, "failover"),
    ({"last_http_status": 502}, "upstream"), ({"last_error": "weird_thing"}, "unknown"), ({}, "unknown"),
])
def test_error_classify(ctx, code):
    assert classify(ctx) == code


def test_running_slow_vs_ok():
    assert explain({"job_status": "running", "job_age_sec": 30}, "ru", "video")[0] == "running_ok"
    assert explain({"job_status": "running", "job_age_sec": 900}, "ru", "video")[0] == "running_slow"
    code, lines, _ = explain({"job_status": "running", "job_age_sec": 10}, "en", "image")
    assert "image" in lines[0]


def test_failed_generation_never_claims_charge():
    for err in ("timeout", "channel_unavailable", "upstream", "queue_unavailable", "unknown"):
        _, lines, _ = explain({"last_error": err}, "ru")
        assert "не списан" in " ".join(lines) or "не списываются" in " ".join(lines)


def test_ui_help_all_topics_short():
    for topic, row in HELP.items():
        assert 1 <= len(row["ru"]) <= 4 and len(row["en"]) == len(row["ru"]), topic


def test_recommend_family_diversity(cards, price_fn):
    c, nb = cards
    pick = recommend(c, "video", ["кино", "речь"], False, None, price_fn, nb, with_cheap=False)
    assert {x.title.split()[0] for x in pick.cards} != {"Veo"} and pick.cards[0].id == "veo-3-1"


def test_vitrina_link_short_and_safe():
    from assistant.render import vitrina_link
    assert vitrina_link("/vitrina.html", "veo-3-1", "кот в снегу") == "/vitrina.html?model=veo-3-1&q=кот+в+снегу"
    assert vitrina_link("/v", "x", 'a")<script>&b') == "/v?model=x&q=a+script+b"
