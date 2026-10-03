"""Step 0 security smoke tests."""
from __future__ import annotations

import os
import sys

import pytest

# Ensure project root on path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-prod")
os.environ.setdefault("ALLOWED_ORIGINS", "http://127.0.0.1:8000")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    # Avoid seed side-effects where possible — import after env
    import server

    server.app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file}"
    server.app.config["TESTING"] = True
    with server.app.app_context():
        server.db.create_all()
    return server.app.test_client()


def test_security_headers_and_csrf_cookie(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Content-Security-Policy" in r.headers
    csrf = client.get("/api/csrf")
    assert csrf.status_code == 200
    assert csrf.get_json().get("csrf_token")
    # cookie may be on jar via get_cookie (Flask 3) or Set-Cookie header
    cookie = None
    if hasattr(client, "get_cookie"):
        cookie = client.get_cookie("csrf_token")
    assert cookie is not None or "csrf_token=" in (r.headers.get("Set-Cookie") or "") or "csrf_token=" in (
        csrf.headers.get("Set-Cookie") or ""
    )


def test_csrf_blocks_post_without_token(client):
    client.get("/api/csrf")
    r = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 403
    assert r.get_json().get("error") == "csrf_failed"


def test_csrf_allows_post_with_token(client):
    csrf = client.get("/api/csrf").get_json()["csrf_token"]
    r = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"X-CSRF-Token": csrf},
    )
    # May fail upstream (not_configured) but must not be CSRF
    assert r.status_code != 403


def test_prod_requires_secret_key(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    from importlib import reload
    import security

    with pytest.raises(RuntimeError):
        from flask import Flask

        app = Flask("x")
        security.configure_security(app)


def test_app_db_not_tracked():
    import subprocess

    out = subprocess.check_output(["git", "ls-files", "app.db"], cwd=ROOT, text=True)
    assert out.strip() == ""
