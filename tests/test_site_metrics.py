"""Метрики сайта: сбор событий (/api/m) и отчёт для админа (воронка, трудности, уходы, возвраты, страницы)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import site_metrics as SM  # noqa: E402

NOW = datetime(2026, 10, 20, 12, 0, 0)


def ev(t, vid, sid, name, page="/app", uid=None, device="desktop", **props):
    return {"ts": NOW - timedelta(minutes=t), "vid": vid, "sid": sid, "uid": uid, "page": page, "name": name,
            "props": props, "device": device}


def scenario():
    rows = []
    # A: главная → студия → идея → модели → выбор → запуск → ошибка (модерация) → ушёл
    rows += [ev(300, "vidAAAAAAAA", "sidA1aaaaa", "page_view", "/", ref="yandex.ru"),
             ev(299, "vidAAAAAAAA", "sidA1aaaaa", "page_view", "/app"),
             ev(298, "vidAAAAAAAA", "sidA1aaaaa", "prompt_sent", len=20),
             ev(298, "vidAAAAAAAA", "sidA1aaaaa", "assist_reply", intent="generate_task", models=6),
             ev(297, "vidAAAAAAAA", "sidA1aaaaa", "models_shown", n=6),
             ev(296, "vidAAAAAAAA", "sidA1aaaaa", "model_pick", model="seedance-2-5", src="assistant"),
             ev(295, "vidAAAAAAAA", "sidA1aaaaa", "generate_click", model="seedance-2-5"),
             ev(295, "vidAAAAAAAA", "sidA1aaaaa", "gen_start", model="seedance-2-5"),
             ev(293, "vidAAAAAAAA", "sidA1aaaaa", "gen_fail", model="seedance-2-5", code="moderation")]
    # A возвращается через день: сразу в студию, получает результат
    rows += [ev(60, "vidAAAAAAAA", "sidA2aaaaa", "page_view", "/app", uid=7),
             ev(59, "vidAAAAAAAA", "sidA2aaaaa", "prompt_sent", uid=7),
             ev(58, "vidAAAAAAAA", "sidA2aaaaa", "model_pick", uid=7, model="kling-v3-0"),
             ev(58, "vidAAAAAAAA", "sidA2aaaaa", "generate_click", uid=7, model="kling-v3-0"),
             ev(57, "vidAAAAAAAA", "sidA2aaaaa", "gen_start", uid=7, model="kling-v3-0"),
             ev(55, "vidAAAAAAAA", "sidA2aaaaa", "gen_done", uid=7, model="kling-v3-0", ms=120000),
             ev(54, "vidAAAAAAAA", "sidA2aaaaa", "publish", uid=7, work="12")]
    # B: гость — помощник попросил войти, ушёл
    rows += [ev(200, "vidBBBBBBBB", "sidB1bbbbb", "page_view", "/app", device="mobile"),
             ev(199, "vidBBBBBBBB", "sidB1bbbbb", "prompt_sent", device="mobile"),
             ev(199, "vidBBBBBBBB", "sidB1bbbbb", "assist_reply", intent="choose_type", gate="login", device="mobile"),
             ev(199, "vidBBBBBBBB", "sidB1bbbbb", "gate", type="login", src="assistant", device="mobile")]
    # C: отказ на главной
    rows += [ev(100, "vidCCCCCCCC", "sidC1ccccc", "page_view", "/")]
    # D: запустил и закрыл вкладку, не дождавшись; три раза открывал витрину
    rows += [ev(90, "vidDDDDDDDD", "sidD1ddddd", "page_view", "/explore"),
             ev(89, "vidDDDDDDDD", "sidD1ddddd", "page_view", "/explore"),
             ev(88, "vidDDDDDDDD", "sidD1ddddd", "page_view", "/explore"),
             ev(87, "vidDDDDDDDD", "sidD1ddddd", "page_view", "/app"),
             ev(86, "vidDDDDDDDD", "sidD1ddddd", "generate_click", model="veo-3-1"),
             ev(86, "vidDDDDDDDD", "sidD1ddddd", "gen_start", model="veo-3-1"),
             ev(85, "vidDDDDDDDD", "sidD1ddddd", "page_leave", ms=60000, pending=True)]
    # E: помощник не понял
    rows += [ev(40, "vidEEEEEEEE", "sidE1eeeee", "page_view", "/app"),
             ev(39, "vidEEEEEEEE", "sidE1eeeee", "prompt_sent"),
             ev(39, "vidEEEEEEEE", "sidE1eeeee", "assist_reply", intent="junk")]
    return rows


def test_norm_page_and_clean_batch():
    assert SM.norm_page("/app?x=1") == "/app" and SM.norm_page("/w/15") == "/w" and SM.norm_page("/legal/terms.html") == "/legal"
    assert SM.norm_page("/explore#a") == "/explore" and SM.norm_page("/zzz") == "/other" and SM.norm_page("") == "/"
    got = SM.clean_batch({"vid": "abcdefgh12", "sid": "sid0000001", "events": [
        {"n": "gen_fail", "page": "/app", "ago": 99999999, "p": {"code": "moderation", "model": "x" * 300, "secret": "drop"}},
        {"n": "evil_event", "p": {}}, "bad"]})
    vid, sid, evs = got
    assert len(evs) == 1 and evs[0]["ago"] == 600000
    assert evs[0]["p"] == {"code": "moderation", "model": "x" * 120}
    assert SM.clean_batch({"vid": "bad id!", "sid": "sid0000001", "events": []}) is None
    assert SM.clean_batch({"vid": "abcdefgh12", "sid": "sid0000001", "events": []}, ua="Googlebot/2.1") is None
    assert SM.clean_batch({"vid": "abcdefgh12", "sid": "sid0000001", "events": []}, ua="HeadlessChrome/120") is None
    assert SM.clean_batch({"vid": "abcdefgh12", "sid": "sid0000001", "events": []}, ua="HeadlessChrome/120", skip_headless=False)


def test_report_summary_funnel_and_exits():
    r = SM.build_report(scenario(), 7, NOW)
    s = r["summary"]
    assert s["visitors"] == 5 and s["sessions"] == 6 and s["gen_done"] == 1 and s["gen_fail"] == 1
    assert s["gen_success_rate"] == 50.0 and s["mobile_share"] == pytest.approx(16.7)
    f = {x["key"]: x["count"] for x in r["funnel"]["sessions"]}
    # шаг засчитан, если дошли до него или дальше
    assert f["visit"] == 6 and f["studio"] == 5 and f["prompt"] == 5 and f["models"] == 3 and f["pick"] == 3
    assert f["click"] == 3 and f["start"] == 3 and f["done"] == 1 and f["share"] == 1
    drops = [x["drop"] for x in r["funnel"]["sessions"]]
    assert drops == [0, 1, 0, 2, 0, 0, 0, 2, 0]
    fv = {x["key"]: x["count"] for x in r["funnel"]["visitors"]}
    assert fv["done"] == 1 and fv["studio"] == 4
    reasons = {x["reason"]: x["sessions"] for x in r["exits"]["reasons"]}
    assert reasons == {"after_error": 1, "success": 1, "gate_login": 1, "bounce": 1, "left_waiting": 1, "assistant_confused": 1}


def test_report_problems():
    p = SM.build_report(scenario(), 7, NOW)["problems"]
    assert p["fail_codes"][0]["code"] == "moderation" and p["fail_codes"][0]["label"] == "Фильтр контента нейросети"
    m = {x["model"]: x for x in p["models"]}
    assert m["seedance-2-5"]["fail_rate"] == 100.0 and m["kling-v3-0"]["done"] == 1 and m["kling-v3-0"]["median_sec"] == 120.0
    assert p["gates"]["login"] == 1 and p["left_waiting"] == 1
    assert {a["intent"] for a in p["assistant"]} == {"junk"}
    assert p["visitors_never_succeeded"] == 0      # у A ошибка, но потом результат


def test_report_returns_and_pages():
    r = SM.build_report(scenario(), 7, NOW)
    ret = r["returns"]
    assert ret["returns"] == 1 and ret["visits_per_visitor"]["2"] == 1 and ret["visits_per_visitor"]["1"] == 4
    assert ret["gap"][1]["label"] == "1–24 часа" and ret["gap"][1]["count"] == 1
    by_exit = {x["reason"]: x for x in ret["by_exit_reason"]}
    assert by_exit["after_error"]["returned"] == 1 and by_exit["after_error"]["rate"] == 100.0
    assert ret["matrix"][0] == {"from": "Ушли после ошибки генерации", "to": "Опубликовали на витрине", "count": 1}
    assert ret["progressed_share"] == 100.0 and ret["return_landing"][0]["page"] == "/app"
    pages = {p["page"]: p for p in r["pages"]}
    ex = pages["/explore"]
    assert ex["views"] == 3 and ex["visitors"] == 1 and ex["views_per_visitor"] == 3.0 and ex["repeat_dist"]["3–5"] == 1
    assert ex["reload_sessions"] == 1
    assert pages["/app"]["visitors"] == 4
    assert r["sources"]["referrers"][0]["ref"] in ("(прямой заход)", "yandex.ru")
    v = {x["vid"]: x for x in r["visitors"]}
    assert v["vidAAAAAAAA"]["visits"] == 2 and v["vidAAAAAAAA"]["uid"] == 7 and v["vidAAAAAAAA"]["furthest"] == "Опубликовали на витрине"


def test_first_seen_marks_old_visitors_as_returning():
    rows = scenario()
    r = SM.build_report(rows, 7, NOW, first_seen={"vidCCCCCCCC": NOW - timedelta(days=40)})
    assert r["summary"]["new_visitors"] == 4 and r["summary"]["returning_visitors"] == 1


def test_journey():
    j = SM.visitor_journey([x for x in scenario() if x["vid"] == "vidAAAAAAAA"])
    assert len(j["visits"]) == 2 and j["uid"] == 7
    assert j["visits"][0]["reason"] == "Ушли после ошибки генерации" and j["visits"][1]["furthest"] == "Опубликовали на витрине"


# ─────────────────────────────────────────────────────────────── Flask
@pytest.fixture()
def srv(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    monkeypatch.setenv("ADMIN_EMAILS", "boss@t.local")
    import server

    server.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{tmp_path / 'm.db'}"
    server.app.config["TESTING"] = True
    with server.app.app_context():
        server.db.session.remove()
        try:
            server.db.engine.dispose()
        except Exception:
            pass
        server.db.drop_all()
        server.db.create_all()
        yield server
        server.db.session.remove()


def _client(srv, ip):
    c = srv.app.test_client()
    c.environ_base["REMOTE_ADDR"] = ip
    return c


def _login(srv, c, email):
    u = srv.User(email=email, provider="password", name="U")
    srv.db.session.add(u)
    srv.db.session.commit()
    with c.session_transaction() as s:
        s["user_id"] = u.id
    return u


def test_ingest_without_csrf_and_admin_report(srv):
    c = _client(srv, "10.77.0.1")
    body = {"vid": "vidTEST0001", "sid": "sidTEST0001", "events": [
        {"n": "page_view", "page": "/app?utm=x", "ago": 1000, "p": {"ref": "t.me", "utm_source": "tg"}},
        {"n": "generate_click", "page": "/app", "ago": 500, "p": {"model": "seedance-2-5"}},
        {"n": "gen_fail", "page": "/app", "ago": 0, "p": {"model": "seedance-2-5", "code": "insufficient_funds", "prompt": "не храним"}}]}
    r = c.post("/api/m", json=body, headers={"User-Agent": "Mozilla/5.0 (iPhone)"})
    assert r.status_code == 204
    rows = srv.db.session.execute(srv.db.text("select name, page, device, props from site_events order by id")).fetchall()
    assert [x[0] for x in rows] == ["page_view", "generate_click", "gen_fail"]
    assert rows[0][1] == "/app" and rows[0][2] == "mobile" and "prompt" not in rows[2][3]
    # не админ — 403, админ — отчёт
    assert c.get("/api/admin/metrics").status_code == 403
    _login(srv, c, "nobody@t.local")
    assert c.get("/api/admin/metrics").status_code == 403
    a = _client(srv, "10.77.0.2")
    _login(srv, a, "boss@t.local")
    rep = a.get("/api/admin/metrics?days=7").get_json()
    assert rep["summary"]["visitors"] == 1 and rep["problems"]["fail_codes"][0]["code"] == "insufficient_funds"
    assert rep["sources"]["utm"][0]["source"] == "tg"
    j = a.get("/api/admin/metrics/visitor/vidTEST0001").get_json()
    assert len(j["visits"]) == 1 and len(j["visits"][0]["events"]) == 3
    csv = a.get("/api/admin/metrics/events.csv?days=7")
    assert csv.status_code == 200 and "gen_fail" in csv.get_data(as_text=True)
    assert a.get("/admin/metrics").status_code == 200


def test_ingest_drops_bots_and_junk(srv):
    c = _client(srv, "10.77.0.3")
    ok = {"vid": "vidTEST0002", "sid": "sidTEST0002", "events": [{"n": "page_view", "page": "/"}]}
    assert c.post("/api/m", json=ok, headers={"User-Agent": "Googlebot"}).status_code == 204
    assert c.post("/api/m", data="not json", headers={"Content-Type": "application/json"}).status_code == 204
    assert c.post("/api/m", json={"vid": "x", "sid": "y", "events": []}).status_code == 204
    n = srv.db.session.execute(srv.db.text("select count(*) from site_events")).scalar()
    assert n == 0
