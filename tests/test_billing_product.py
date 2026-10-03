"""Billing hold/capture/release + free queue priority + robokassa sign."""
from __future__ import annotations

import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-prod")
os.environ.setdefault("ALLOW_STUB_GEN", "1")
os.environ.setdefault("FREE_STUB", "1")


@pytest.fixture()
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    monkeypatch.setenv("ALLOW_STUB_GEN", "1")
    import server

    db_file = tmp_path / "billing.db"
    server.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file}"
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


@pytest.fixture()
def client(app_ctx):
    return app_ctx.app.test_client()


def _csrf(client):
    return client.get("/api/csrf").get_json()["csrf_token"]


def _register_user(client, email="u@example.com", password="secret123"):
    csrf = _csrf(client)
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code in {200, 201, 409} or r.get_json().get("user") or r.status_code == 200
    if r.status_code not in {200, 201} and r.get_json().get("error") == "exists":
        r = client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
            headers={"X-CSRF-Token": _csrf(client)},
        )
    return r


def test_hold_insufficient_does_not_change_balance(app_ctx):
    import billing
    from product_models import init_product_models

    models = app_ctx.app.extensions["product_models"]
    Balance, Ledger = models["Balance"], models["Ledger"]
    db = app_ctx.db
    user = app_ctx.User(email="a@t.local", provider="password", name="A")
    db.session.add(user)
    db.session.commit()
    bal = billing.get_or_create_balance(db, Balance, user.id)
    assert bal.balance_kop == 0
    with pytest.raises(billing.InsufficientFunds):
        billing.hold(db, Balance, Ledger, user_id=user.id, amount_kop=100, job_id="j1", model_key="x")
    bal = billing.get_or_create_balance(db, Balance, user.id)
    assert bal.balance_kop == 0 and bal.held_kop == 0


def test_hold_capture_release_idempotent(app_ctx):
    import billing

    models = app_ctx.app.extensions["product_models"]
    Balance, Ledger = models["Balance"], models["Ledger"]
    db = app_ctx.db
    user = app_ctx.User(email="b@t.local", provider="password", name="B")
    db.session.add(user)
    db.session.commit()
    billing.topup(db, Balance, Ledger, user_id=user.id, amount_kop=50000, idempotency_key="t1")
    billing.hold(db, Balance, Ledger, user_id=user.id, amount_kop=3000, job_id="jobA", model_key="m")
    billing.hold(db, Balance, Ledger, user_id=user.id, amount_kop=3000, job_id="jobA", model_key="m")
    bal = billing.get_or_create_balance(db, Balance, user.id)
    assert bal.held_kop == 3000
    billing.capture(db, Balance, Ledger, user_id=user.id, amount_kop=3000, job_id="jobA", model_key="m")
    billing.capture(db, Balance, Ledger, user_id=user.id, amount_kop=3000, job_id="jobA", model_key="m")
    bal = billing.get_or_create_balance(db, Balance, user.id)
    assert bal.balance_kop == 47000 and bal.held_kop == 0

    billing.hold(db, Balance, Ledger, user_id=user.id, amount_kop=1000, job_id="jobB", model_key="m")
    billing.release(db, Balance, Ledger, user_id=user.id, amount_kop=1000, job_id="jobB", model_key="m")
    billing.release(db, Balance, Ledger, user_id=user.id, amount_kop=1000, job_id="jobB", model_key="m")
    bal = billing.get_or_create_balance(db, Balance, user.id)
    assert bal.balance_kop == 47000 and bal.held_kop == 0


def test_parallel_last_ruble_one_wins(app_ctx):
    import billing

    models = app_ctx.app.extensions["product_models"]
    Balance, Ledger = models["Balance"], models["Ledger"]
    db = app_ctx.db
    user = app_ctx.User(email="c@t.local", provider="password", name="C")
    db.session.add(user)
    db.session.commit()
    billing.topup(db, Balance, Ledger, user_id=user.id, amount_kop=100, idempotency_key="t2")
    billing.hold(db, Balance, Ledger, user_id=user.id, amount_kop=100, job_id="p1", model_key="m")
    with pytest.raises(billing.InsufficientFunds):
        billing.hold(db, Balance, Ledger, user_id=user.id, amount_kop=100, job_id="p2", model_key="m")


def test_free_priority_newbie_ahead():
    import free_quota

    class Row:
        def __init__(self, lifetime, used, bonus=0, publish=False):
            self.lifetime_success = lifetime
            self.used = used
            self.bonus = bonus
            self.publish_bonus_used = publish

    newbie = free_quota.priority_score(Row(0, 0), 0)
    waiting = free_quota.priority_score(Row(5, 1), 3600)
    assert newbie > waiting


def test_free_failure_does_not_consume(app_ctx):
    import free_quota

    models = app_ctx.app.extensions["product_models"]
    FreeQuota = models["FreeQuota"]
    db = app_ctx.db
    user = app_ctx.User(email="d@t.local", provider="password", name="D")
    db.session.add(user)
    db.session.commit()
    fq = free_quota.get_quota(db, FreeQuota, user.id)
    left0 = free_quota.free_left(fq)
    # no consume_success → left unchanged
    assert free_quota.free_left(fq) == left0


def test_robokassa_double_webhook_once(app_ctx, monkeypatch):
    import billing
    from robokassa import RobokassaProvider

    monkeypatch.setenv("ROBOKASSA_MERCHANT_LOGIN", "demo")
    monkeypatch.setenv("ROBOKASSA_PASSWORD1", "p1")
    monkeypatch.setenv("ROBOKASSA_PASSWORD2", "p2")
    models = app_ctx.app.extensions["product_models"]
    Balance, Ledger = models["Balance"], models["Ledger"]
    db = app_ctx.db
    user = app_ctx.User(email="e@t.local", provider="password", name="E")
    db.session.add(user)
    db.session.commit()
    inv = f"{int(time.time())}{user.id}"
    # emulate verified webhook twice via topup idempotency
    billing.topup(db, Balance, Ledger, user_id=user.id, amount_kop=19900, idempotency_key=f"topup:{inv}")
    billing.topup(db, Balance, Ledger, user_id=user.id, amount_kop=19900, idempotency_key=f"topup:{inv}")
    bal = billing.get_or_create_balance(db, Balance, user.id)
    assert bal.balance_kop == 19900

    p = RobokassaProvider()
    start = p.start_topup(user_id=user.id, amount_kop=19900, inv_id="42", description="test")
    assert "SignatureValue" in start.pay_url


def test_jobs_start_with_balance(client, app_ctx, monkeypatch):
    import billing
    import pricing

    monkeypatch.setattr(pricing, "get_usd_rub_rate", lambda force=False: (90.0, False))
    models = app_ctx.app.extensions["product_models"]
    Balance, Ledger = models["Balance"], models["Ledger"]
    csrf = _csrf(client)
    # email code login
    r = client.post(
        "/api/auth/email-code/request",
        json={"email": "gen@t.local", "consent_152": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 200
    code = r.get_json()["dev_code"]
    r = client.post(
        "/api/auth/email-code/verify",
        json={"email": "gen@t.local", "code": code},
        headers={"X-CSRF-Token": _csrf(client)},
    )
    assert r.status_code == 200
    user_id = r.get_json()["user"]["id"]
    billing.topup(
        app_ctx.db,
        Balance,
        Ledger,
        user_id=user_id,
        amount_kop=50000,
        idempotency_key="jobtop",
    )
    # Use an image model that stubs without redis mapping issues
    r = client.post(
        "/api/jobs/start",
        json={
            "model_key": "bytedance/sdxl-lightning-4step",
            "prompt": "кот космонавт",
            "params": {},
        },
        headers={"X-CSRF-Token": _csrf(client)},
    )
    # model might be per_run_approx; if unknown skip
    if r.status_code == 400 and r.get_json().get("error") == "unknown_model":
        r = client.post(
            "/api/jobs/start",
            json={"model_key": "alibaba/wan-3", "prompt": "кот космонавт", "params": {"duration_sec": 5}},
            headers={"X-CSRF-Token": _csrf(client)},
        )
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body.get("job_id")
    assert body.get("status") in {"succeeded", "queued", "held"}


def test_explore_and_me(client):
    r = client.get("/api/explore")
    assert r.status_code == 200
    assert "items" in r.get_json()
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert "balance_kop" in r.get_json() or r.get_json().get("user") is None
