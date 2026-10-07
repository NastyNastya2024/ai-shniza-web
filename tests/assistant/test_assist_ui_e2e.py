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
def page(server, monkeypatch, request):
    monkeypatch.setenv("DEMO_ACCOUNT", "1" if request.node.get_closest_marker("account") else "0")
    import urllib.request
    urllib.request.urlopen(urllib.request.Request(server + "/demo/reset", method="POST"))
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
    assert "Поняла так" in last.inner_text() and "Какой кот" in last.inner_text()   # уточняет детали под идею
    assert last.locator(".aich-open li").count() == 3                                # кто, где, что — своими словами
    rows = pg.locator(".aich-row").count()
    last.locator(".aich-opt:has-text('Смешная')").click()
    pg.wait_for_function("[...document.querySelectorAll('.aich-row:last-child .aich-opt.is-on')].some(b => b.textContent === 'Смешная')")
    assert pg.locator(".aich-row").count() == rows                                   # обновилось на месте
    n = pg.locator(".aich-row").count()
    say(pg, "рыжий кот в поварском колпаке, деревенская кухня, переворачивает яичницу")   # ответ одним сообщением
    variants = pg.locator(".aich-row:last-child .aich-variant")
    assert variants.count() == 3 and "chef's hat" in variants.first.inner_text()
    n = pg.locator(".aich-row").count()
    variants.nth(1).click()
    pg.wait_for_function(f"document.querySelectorAll('.aich-row:not(.aich-typing)').length >= {n + 2}")
    last = pg.locator(".aich-row:last-child")
    assert "flips an egg" in last.locator(".aich-prompt__text").inner_text()
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
    assert gen["model"] and "flips an egg" in gen["prompt"] and gen["params"]
    # старые кнопки погашены
    assert pg.locator(".aich-row.is-old").count() >= 3
    assert errors == []


def test_prompt_edit_in_place_updates_form(page):
    pg, errors = page
    say(pg, "вертикальное видео 5 секунд: кот жарит яичницу")
    n = pg.locator(".aich-row").count()
    pg.locator(".aich-row:last-child .aich-model").first.click()
    pg.wait_for_function(f"document.querySelectorAll('.aich-row:not(.aich-typing)').length >= {n + 2}")
    n = pg.locator(".aich-row").count()
    pg.locator(".aich-row:last-child .aich-chip--primary").click()
    pg.wait_for_function(f"document.querySelectorAll('.aich-row:not(.aich-typing)').length >= {n + 2}")
    n = pg.locator(".aich-row").count()
    pg.locator(".aich-row:last-child .aich-variant").first.click()
    pg.wait_for_function(f"document.querySelectorAll('.aich-row:not(.aich-typing)').length >= {n + 2}")
    txt = pg.locator(".aich-row:last-child .aich-prompt__text")
    txt.click()
    pg.keyboard.press("Control+End")
    pg.keyboard.type(", neon lights")
    assert pg.evaluate("chat.form().prompt").endswith(", neon lights")
    assert pg.evaluate("chat.form().params.aspect_ratio") == "9:16"
    assert errors == []



@pytest.mark.account
def test_login_then_topup_then_generate(page):
    pg, errors = page
    say(pg, "видео: кот жарит яичницу")
    for sel in (".aich-model", ".aich-chip--primary", ".aich-variant"):          # модель → бриф → вариант
        n = pg.locator(".aich-row").count()
        pg.locator(".aich-row:last-child " + sel).first.click()
        pg.wait_for_function(f"document.querySelectorAll('.aich-row:not(.aich-typing)').length >= {n + 2}")
    last = pg.locator(".aich-row:last-child")
    assert "войдите" in last.inner_text()
    assert last.locator(".aich-chip--primary").inner_text() == "Войти"
    assert last.locator(".aich-chip:has-text('Сгенерировать')").count() == 0

    def click_primary_and_wait():
        k = pg.locator(".aich-row").count()
        pg.locator(".aich-row:last-child .aich-chip--primary").click()
        pg.wait_for_function(f"document.querySelectorAll('.aich-row:not(.aich-typing)').length >= {k + 1}")
        pg.wait_for_timeout(300)

    click_primary_and_wait()                                    # «Войти» → вернулись → проверка баланса
    last = pg.locator(".aich-row:last-child")
    assert "На балансе 0 ₽" in last.inner_text() and last.locator(".aich-chip--primary").inner_text() == "Пополнить"
    click_primary_and_wait()                                    # «Пополнить» → вернулись → можно запускать
    last = pg.locator(".aich-row:last-child")
    assert "спишется" in last.inner_text() and last.locator(".aich-chip--primary").inner_text() == "Сгенерировать"
    last.locator(".aich-chip--primary").click()
    assert pg.evaluate("window.lastGenerate")["model"]
    assert errors == []



def test_empty_idea_and_junk_in_ui(page):
    pg, errors = page
    say(pg, "нужно сделать видео")
    last = pg.locator(".aich-row:last-child")
    assert "Кто в кадре?" in last.inner_text() and last.locator(".aich-chip").count() == 0   # вопросы, без примеров
    say(pg, "ооло")
    assert "Не совсем поняла" in pg.locator(".aich-row:last-child").inner_text()
    say(pg, "рыжий кот жарит яичницу на кухне")
    assert pg.locator(".aich-row:last-child .aich-model").count() >= 2
    assert errors == []
