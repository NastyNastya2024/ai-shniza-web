"""Подсказки по интерфейсу — шаблоны, 0 токенов. Тексты сверить с реальным UI при интеграции."""
from __future__ import annotations

from typing import Any

HELP: dict[str, dict[str, Any]] = {
    "topup": {
        "ru": ["Баланс — в кабинете, вкладка «Баланс», кнопка «Пополнить».", "Списание — только после успешной генерации."],
        "en": ["Balance is in your account → “Balance”, button “Top up”.", "You are charged only after a successful generation."],
        "chips": [("topup", "open_topup")],
    },
    "publish": {
        "ru": ["В кабинете у работы нажмите «Опубликовать на витрине» (или статус «Скрыта»).", "Публикацию можно снять в любой момент."],
        "en": ["In your account, on a work tap “Publish to showcase”.", "You can unpublish any time."],
        "chips": [("vitrina", "open_vitrina")],
    },
    "vitrina": {
        "ru": ["Витрина — лучшие работы пользователей (кнопка «Витрина» в студии или /explore).", "У каждой работы видна модель — можно повторить."],
        "en": ["Showcase — best works by users (studio “Showcase” or /explore).", "Each work shows its model — you can repeat it."],
        "chips": [("vitrina", "open_vitrina")],
    },
    "download": {
        "ru": ["Откройте результат в чате или на странице работы → сохраните файл.", "На телефоне: долгое нажатие → «Сохранить»."],
        "en": ["Open the result in chat or on the work page → save the file.", "On phone: long press → “Save”."],
        "chips": [],
    },
    "history": {
        "ru": ["Все ваши генерации — в кабинете, вкладка «Работы»."],
        "en": ["All your generations are in your account → “Works”."],
        "chips": [],
    },
    "login": {
        "ru": ["Вход — кнопка «Войти»: через Google или код на почту.", "Код приходит за минуту; проверьте «Спам»."],
        "en": ["Sign in via Google or an email code.", "The code arrives within a minute; check Spam."],
        "chips": [("login", "login")],
    },
    "attach": {
        "ru": ["Нажмите «Прикрепить файл» (скрепка слева от поля ввода) и выберите фото.", "Подходят JPG/PNG/WebP."],
        "en": ["Tap “Attach file” (paperclip left of the input) and choose a photo.", "JPG/PNG/WebP are supported."],
        "chips": [("attach", "attach")],
    },
    "models": {
        "ru": ["Модели — кнопка «Сменить модель» под полем ввода (или панель справа).", "Или опишите задачу — я подберу сама."],
        "en": ["Models — “Change model” under the input (or the right panel).", "Or describe the task — I'll pick for you."],
        "chips": [("open_models", "open_models")],
    },
    "profile": {
        "ru": ["Профиль — в кабинете: аватар, имя, описание.", "Другие видят его на витрине у ваших работ."],
        "en": ["Profile is in your account: avatar, name, bio.", "Others see it next to your works in the showcase."],
        "chips": [],
    },
    "mobile": {
        "ru": ["Сайт работает в мобильном браузере.", "Генерация идёт на сервере — экран можно закрыть, результат сохранится."],
        "en": ["The site works in a mobile browser.", "Generation runs on the server — you can close the screen."],
        "chips": [],
    },
}


def ui_help(topic: str, lang: str) -> tuple[list[str], list[tuple[str, str]]]:
    row = HELP.get(topic) or HELP["models"]
    return list(row.get(lang) or row["ru"]), list(row["chips"])
