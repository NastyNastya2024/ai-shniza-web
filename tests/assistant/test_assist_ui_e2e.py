"""E2E: настоящий движок + integration/assistant-ui.js в Chromium (Playwright). Пропускается, если Playwright нет."""
import os
import threading

import pytest

pw = pytest.importorskip("playwright.sync_api")
from werkzeug.serving import make_server  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo", "demo_app.py")
if not os.path.isfile(DEMO):  # в репозитории сайта demo/ нет — E2E гоняется из папки пакета
    pytest.skip("demo/ not found (run E2E from the package folder)", allow_module_level=True)


@pytest.fixture(scope="module")
def server():
    import importlib.util
    spec = importlib.util.spec_from_file_location("demo_app", DEMO)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    srv = make_server("127.0.0.1", 0, mod.app, threaded=True)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture()
def page(server):
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # браузер не установлен
            pytest.skip(f"chromium unavailable: {exc}")
        pg = b.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(server)
        yield pg, errors
        b.close()


def say(pg, text):
    n = pg.locator(".aich-row").count()
    pg.fill("#q", text)
    pg.press("#q", "Enter")
    pg.wait_for_function(f"document.querySelectorAll('.aich-row:not(.aich-typing)').length >= {n + 2}")


def test_flow_from_screenshot(page):
    pg, errors = page
    say(pg, "привет")
    assert pg.locator(".aich-row:last-child .aich-chip").count() == 4
    say(pg, "надо сделать коты который жарит иишницу")
    assert "картинку, видео или музыку" in pg.inner_text(".aich-row:last-child")
    say(pg, "карттинку")
    cards = pg.locator(".aich-row:last-child .aich-model")
    assert cards.count() >= 2
    assert "₽" in cards.first.inner_text() and "витрине" in cards.first.inner_text()
    n = pg.locator(".aich-row").count()
    cards.first.click()
    pg.wait_for_function(f"document.querySelectorAll('.aich-row:not(.aich-typing)').length >= {n + 2}")
    last = pg.locator(".aich-row:last-child")
    assert last.locator(".aich-prompt__text").inner_text().startswith("A fluffy ginger cat")
    assert last.locator(".aich-opt.is-on").count() >= 1
    # смена параметра обновляет сообщение на месте, без новых пузырей
    rows = pg.locator(".aich-row").count()
    opt = last.locator(".aich-param").first.locator(".aich-opt:not(.is-on)").first
    label = opt.inner_text()
    opt.click()
    pg.wait_for_function(f"[...document.querySelectorAll('.aich-row:last-child .aich-opt.is-on')].some(b => b.textContent === {label!r})")
    assert pg.locator(".aich-row").count() == rows
    # «Сгенерировать» уходит в onGenerate фронта, не на сервер ассистента
    pg.locator(".aich-row:last-child .aich-chip--primary").click()
    gen = pg.evaluate("window.lastGenerate")
    assert gen["model"] and gen["prompt"].startswith("A fluffy") and gen["params"]
    # старые кнопки погашены
    assert pg.locator(".aich-row.is-old").count() >= 3
    assert errors == []


def test_prompt_edit_in_place_updates_form(page):
    pg, errors = page
    say(pg, "вертикальное видео 5 секунд: кот жарит яичницу")
    n = pg.locator(".aich-row").count()
    pg.locator(".aich-row:last-child .aich-model").first.click()
    pg.wait_for_function(f"document.querySelectorAll('.aich-row:not(.aich-typing)').length >= {n + 2}")
    txt = pg.locator(".aich-row:last-child .aich-prompt__text")
    txt.click()
    pg.keyboard.press("End")
    pg.keyboard.type(", neon lights")
    assert pg.evaluate("chat.form().prompt").endswith(", neon lights")
    assert pg.evaluate("chat.form().params.aspect_ratio") == "9:16"
    assert errors == []
