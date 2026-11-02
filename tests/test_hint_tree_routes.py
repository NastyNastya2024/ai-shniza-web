"""Дерево подсказок в админке: правки черновика, версии, лог помощника, нехарактерные действия, новые пути."""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import hint_tree_routes as HR  # noqa: E402
from assistant.tree import HintTree  # noqa: E402


@pytest.fixture(scope="module")
def data():
    return HintTree.load_json().data


# ---------------------------------------------------------------- чистые функции
def test_bump():
    assert HR.bump("1.1.0", "patch") == "1.1.1"
    assert HR.bump("1.1.3", "minor") == "1.2.0"
    assert HR.bump("1.4.2", "major") == "2.0.0"


def test_add_hint_and_story(data):
    d, part = HR.apply_op(data, {"op": "add_hint", "story": "DSN.INTER.S01", "step": 1, "label": "Добавить растения"})
    assert part == "minor" and "Добавить растения" in HR.find_story(d, "DSN.INTER.S01")[2]["steps"][1]["hints"]
    assert "Добавить растения" not in HR.find_story(data, "DSN.INTER.S01")[2]["steps"][1]["hints"]   # исходник не тронут
    d2, part2 = HR.apply_op(d, {"op": "add_story", "vector": "VID", "sub": "REELS", "title": "Рилс с сохранением в Dropbox",
                                "steps": [{"step": "«рилс и сразу в дропбокс»", "hints": ["Подключить Dropbox", "Рилс"]}]})
    assert part2 == "minor"
    t = HintTree(d2)
    sid = next(k for k, o in t.stories.items() if o["title"] == "Рилс с сохранением в Dropbox")
    assert sid.startswith("VID.REELS.S")


def test_edit_hints_is_patch_and_validated(data):
    d, part = HR.apply_op(data, {"op": "edit_hints", "story": "DSN.INTER.S01", "step": 0, "hints": ["Фото комнаты", "Стиль"]})
    assert part == "patch"
    with pytest.raises(ValueError):
        HR.apply_op(data, {"op": "edit_hints", "story": "DSN.INTER.S01", "step": 0, "hints": []})
    with pytest.raises(ValueError):
        HR.apply_op(data, {"op": "add_hint", "story": "NOPE", "step": 0, "label": "x"})


def test_internal_kitchen_rejected(data):
    with pytest.raises(ValueError):
        HR.apply_op(data, {"op": "add_hint", "story": "DSN.INTER.S01", "step": 0, "label": "Через Replicate дешевле"})


def test_deprecated_story_leaves_runtime(data):
    d, _ = HR.apply_op(data, {"op": "set_status", "story": "DSN.UI.S01", "status": "deprecated"})
    assert "DSN.UI.S01" not in HintTree(d).stories


def test_atypical_report_flags_over_threshold():
    rows = [{"kind": "run", "story": "S", "step": 1} for _ in range(40)]
    rows += [{"kind": "atypical", "story": "S", "step": 1, "label": "добавь кота"} for _ in range(3)]
    rows += [{"kind": "atypical", "story": "S", "step": 1, "label": "другое"}]
    rep = HR.atypical_report(rows, {"atypical_share": 0.05, "atypical_min_runs": 20})
    assert rep[0]["label"] == "добавь кота" and rep[0]["flag"] is True
    assert next(r for r in rep if r["label"] == "другое")["flag"] is False


def test_new_paths_cluster_by_dialogs():
    rows = [{"kind": "new_path", "sid": f"s{i}", "trail": ["рилс", "музыка", "dropbox"], "profession": "CRE.BLOG"} for i in range(21)]
    rep = HR.new_paths_report(rows, {"cluster_dialogs": 20})
    assert rep[0]["dialogs"] == 21 and rep[0]["flag"] is True


# ---------------------------------------------------------------- Flask + БД
@pytest.fixture()
def client(monkeypatch):
    flask_sqlalchemy = pytest.importorskip("flask_sqlalchemy")
    from flask import Flask, session

    from assistant.cards import load_cards
    from assistant.engine import Assistant, AssistantDeps
    from assistant.session import MemoryStore

    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", SECRET_KEY="t", TESTING=True)
    db = flask_sqlalchemy.SQLAlchemy(app)

    class User(db.Model):
        __tablename__ = "users"
        id = db.Column(db.Integer, primary_key=True)
        email = db.Column(db.String(120))

    cards, nb = load_cards()
    asst = Assistant(AssistantDeps(cards=cards, neighbors=nb, store=MemoryStore(), tree=HintTree.load_json()))
    app.config["ASSISTANT"] = asst
    monkeypatch.setenv("ADMIN_EMAILS", "boss@x.ru")
    models = HR.register_hint_tree(app, db, User, asst)

    @app.route("/_login/<int:uid>")
    def _login(uid):
        session["user_id"] = uid
        return "ok"

    with app.app_context():
        db.create_all()
        db.session.add(User(id=1, email="boss@x.ru"))
        db.session.add(User(id=2, email="user@x.ru"))
        db.session.commit()
    c = app.test_client()
    c.app_, c.asst, c.models, c.db = app, asst, models, db
    return c


def test_admin_only(client):
    assert client.get("/api/admin/hint-tree").status_code == 403
    client.get("/_login/2")
    assert client.get("/api/admin/hint-tree").status_code == 403


def test_assistant_turns_land_in_admin_reports(client):
    with client.app_.test_request_context():
        client.asst.handle("покажи клиенту 3 варианта кухни в разных стилях", {}, "z1")
        client.asst.handle("а можно добавить кота на подоконник", {}, "z1")
    client.get("/_login/1")
    r = client.get("/api/admin/hint-tree").get_json()
    assert r["version"] >= "1.1.0" and r["counters"]["DSN.INTER.S02"]["starts"] == 1
    at = client.get("/api/admin/hint-tree/atypical").get_json()["items"]
    assert any(i["story"] == "DSN.INTER.S02" for i in at)
    with client.app_.app_context():
        ev = client.models["HintTreeEvent"].query.first()
        assert ev.sid and len(ev.sid) == 16 and ev.sid != "z1"                   # sid хэшируется


def test_draft_publish_rollback_swaps_assistant_tree(client):
    client.get("/_login/1")
    r = client.post("/api/admin/hint-tree/draft", json={"op": "add_hint", "story": "DSN.INTER.S01", "step": 0,
                                                        "label": "Пример: Apartment Speed-Ramp", "position": 0})
    assert r.status_code == 200 and r.get_json()["draft"] == "1.2.0"
    r = client.post("/api/admin/hint-tree/draft", json={"op": "edit_hints", "story": "DSN.INTER.S02", "step": 0,
                                                        "hints": ["Загрузить фото кухни", "Стили"]})
    assert r.get_json()["draft"] == "1.2.0"                                    # minor уже есть — patch не меняет номер
    old = client.asst.d.tree.version
    assert client.post("/api/admin/hint-tree/publish", json={}).get_json()["active"] == "1.2.0"
    assert client.asst.d.tree.version == "1.2.0"
    assert client.asst.d.tree.stories["DSN.INTER.S02"]["steps"][0]["hints"][0] == "Загрузить фото кухни"
    vers = client.get("/api/admin/hint-tree/versions").get_json()
    assert vers["active"] == "1.2.0" and vers["items"][0]["status"] == "published"
    # откат на исходную версию: публикуем её копию
    with client.app_.app_context():
        V = client.models["HintTreeVersion"]
        client.db.session.add(V(version=old, status="archived", data=json.dumps(HintTree.load_json().data, ensure_ascii=False)))
        client.db.session.commit()
    assert client.post("/api/admin/hint-tree/rollback", json={"version": old}).get_json()["active"] == old
    assert client.asst.d.tree.version == old
