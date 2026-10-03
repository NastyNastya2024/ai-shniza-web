import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SECRET_KEY", "test")
os.environ.setdefault("FLASK_ENV", "development")

def test_video_cat_no_llm(monkeypatch):
    import pricing
    monkeypatch.setattr(pricing, "get_usd_rub_rate", lambda force=False: (90.0, False))
    from assistant_rules import recommend
    r = recommend("видео кот-космонавт 5 секунд", free_left=1, region="RU")
    assert r["used_llm"] is False
    assert r["clarify"] is None
    assert 1 <= len(r["options"]) <= 3
    assert any(o.get("is_free") or o.get("price_rub") is not None for o in r["options"])
