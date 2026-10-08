"""Подсказки по интерфейсу — шаблоны, 0 токенов. Тексты сверить с реальным UI при интеграции."""
from __future__ import annotations

from typing import Any

HELP: dict[str, dict[str, Any]] = {
    "topup": {
        "ru": ["Баланс — в кабинете, кнопка «Пополнить».", "Списание — только после успешной генерации."],
        "en": ["Balance is in your account, button “Top up”.", "You are charged only after a successful generation."],
        "chips": [("topup", "open_topup")],
    },
    "publish": {
        "ru": ["Откройте готовую работу → «Опубликовать на витрине».", "Публикацию можно снять в любой момент."],
        "en": ["Open a finished work → “Publish to showcase”.", "You can unpublish any time."],
        "chips": [("vitrina", "open_vitrina")],
    },
    "vitrina": {
        "ru": ["Витрина — лучшие работы пользователей.", "У каждой работы видна модель и промпт — можно повторить."],
        "en": ["Showcase — best works by users.", "Each work shows its model and prompt — you can repeat it."],
        "chips": [("vitrina", "open_vitrina")],
    },
    "download": {
        "ru": ["Наведите на результат → значок «Скачать».", "На телефоне: долгое нажатие → «Сохранить»."],
        "en": ["Hover the result → “Download” icon.", "On phone: long press → “Save”."],
        "chips": [],
    },
    "history": {
        "ru": ["Генерации — в кабинете, раздел «Мои работы». Неопубликованные хранятся 24 часа, опубликованные на витрине — пока вы их не удалите. Переписка с помощником — 30 дней."],
        "en": ["Generations are in your account → “My works”. Unpublished ones are kept for 24 hours, published ones until you delete them. Chats are kept for 30 days."],
        "chips": [],
    },
    "login": {
        "ru": ["Вход — кнопка «Войти»: через Google или код на почту.", "Код приходит за минуту; проверьте «Спам»."],
        "en": ["Sign in via Google or an email code.", "The code arrives within a minute; check Spam."],
        "chips": [("login", "login")],
    },
    "attach": {
        "ru": ["Нажмите скрепку слева от поля ввода и выберите фото.", "Подходят JPG/PNG/WebP."],
        "en": ["Tap the paperclip left of the input and choose a photo.", "JPG/PNG/WebP are supported."],
        "chips": [("attach", "attach")],
    },
    "models": {
        "ru": ["Модели — кнопка «Модели» над полем ввода.", "Или опишите задачу — я подберу сама."],
        "en": ["Models — the “Models” button above the input.", "Or describe the task — I'll pick for you."],
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
