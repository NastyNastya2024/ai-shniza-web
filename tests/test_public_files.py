"""Публичные файлы: отдаём только вёрстку и медиа; секреты, база, git и код — 404."""
from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-for-prod")
    import server

    server.app.config["TESTING"] = True
    return server.app.test_client()


@pytest.mark.parametrize("path", ["/.env", "/app.db", "/.git/config", "/.git/HEAD", "/server.py", "/auth.py",
                                  "/requirements.txt", "/env.example", "/.gitignore", "/tests/test_public_files.py",
                                  "/deploy/gunicorn.conf.py", "/assistant/engine.py", "/models.json", "/all_models.json",
                                  "/AI_shniza_website.code-workspace", "/assets/../server.py", "/assets/.hidden.png",
                                  "/OmniRoute-release-v3.8.51/README.md", "/scripts/x.js", "/prompts/a.html"])
def test_private_files_hidden(client, path):
    assert client.get(path).status_code == 404


def test_public_assets_still_served(client):
    for path in ("/aish-style.js", "/assistant-ui.css", "/legal/privacy.html"):
        assert client.get(path).status_code == 200, path
    import server

    assert server._public_file_ok("assets/bg-light.jpg") and server._public_file_ok("img/a/b.webp")
    assert server._public_file_ok("robots.txt") and not server._public_file_ok("notes.txt")
