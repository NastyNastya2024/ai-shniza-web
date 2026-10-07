"""Все тексты ассистента RU/EN. Здесь — единственное место, где правится тон.

Правила тона: на «вы», вежливо, без восторгов и без давления; 1 мысль — 1 строка.
"""
from __future__ import annotations

T: dict[str, dict[str, str]] = {
    # --- подбор ---
    "picked": {"ru": "Подобрала {n} модели для «{topic}»:", "en": "{n} models for “{topic}”:"},
    "picked_notopic": {"ru": "Подобрала {n} модели:", "en": "{n} models for you:"},
    "closest": {"ru": "Точной модели под это нет — ближе всего:", "en": "No exact match — closest options:"},
    "vitrina": {"ru": "Примеры на витрине", "en": "Examples in showcase"},
    "prompt_for": {"ru": "Промпт под {title}:", "en": "Prompt for {title}:"},
    "prompt_simple": {"ru": "Промпт под {title} (упрощённый режим):", "en": "Prompt for {title} (simple mode):"},
    "ask_type": {"ru": "Что создаём?", "en": "What shall we create?"},
    "more": {"ru": "Ещё варианты:", "en": "More options:"},
    "no_more": {"ru": "Других подходящих моделей сейчас нет.", "en": "No other suitable models right now."},
    "none_available": {
        "ru": "Сейчас нет доступных моделей для этой задачи.\nПопробуйте через пару минут.",
        "en": "No models are available for this task right now.\nPlease try again in a few minutes.",
    },
    "param_saved": {"ru": "Записала: {label}.", "en": "Saved: {label}."},
    "ready": {"ru": "Всё готово — можно запускать.", "en": "All set — ready to generate."},
    "needs_image": {"ru": "Этой модели нужно фото — прикрепите его, пожалуйста.", "en": "This model needs a photo — please attach one."},
    "kept_text": {"ru": "Оставила ваш текст без изменений.", "en": "Kept your text as is."},
    "params_adjusted": {"ru": "Длительность {asked} с недоступна — поставила {got} с.", "en": "{asked}s isn't available — set {got}s."},
    "ask_aspect_ratio": {"ru": "Какой формат кадра?", "en": "Which aspect ratio?"},
    "ask_duration": {"ru": "Какая длительность?", "en": "Which duration?"},
    "ask_resolution": {"ru": "Какое качество?", "en": "Which quality?"},
    "ask_param": {"ru": "Уточните: {name}", "en": "Please choose: {name}"},
    "what_change": {"ru": "Напишите, что поменять в промпте.", "en": "Tell me what to change in the prompt."},
    "rephrase_ask": {"ru": "Опишите идею другими словами — я подберу безопасный вариант.", "en": "Describe the idea in other words — I'll make a safe version."},
    "describe_idea": {"ru": "Опишите идею одной фразой — и я подготовлю промпт.", "en": "Describe the idea in one sentence — I'll prepare the prompt."},
    "confirm_generate": {"ru": "Проверьте и нажмите «Сгенерировать».", "en": "Check and press “Generate”."},
    "unknown_model": {"ru": "Не нашла такую модель. Вот что могу предложить:", "en": "Couldn't find that model. Here's what I can offer:"},
    "alternatives": {"ru": "Похожие модели:", "en": "Similar models:"},
    "model_down": {"ru": "{title} сейчас недоступна.", "en": "{title} is unavailable right now."},
    "cheapest_head": {"ru": "Самые доступные сейчас:", "en": "Most affordable right now:"},
    "ask_type_idea": {"ru": "Что сделать по идее «{topic}» — картинку, видео или музыку?", "en": "What should I make for “{topic}” — image, video or music?"},
    "ask_type_plain": {"ru": "Что создаём — картинку, видео или музыку?", "en": "What shall we create — image, video or music?"},
    "ask_type_again": {"ru": "Не поняла 🙂 Выберите кнопкой: картинка, видео или музыка.", "en": "Sorry, didn't get that 🙂 Pick a button: image, video or music."},
    "models_head": {"ru": "Подобрала {n} модели для «{topic}». Нажмите на карточку:", "en": "{n} models for “{topic}”. Tap a card:"},
    "models_head_plain": {"ru": "Подобрала {n} модели. Нажмите на карточку:", "en": "{n} models for you. Tap a card:"},
    "prompt_ready": {"ru": "Переписала промпт под {title}. Проверьте настройки и запускайте:", "en": "Adapted the prompt for {title}. Check settings and run:"},
    "prompt_ready_simple": {"ru": "Промпт для {title}. Проверьте настройки и запускайте:", "en": "Prompt for {title}. Check settings and run:"},
    "prompt_changed": {"ru": "Обновила промпт:", "en": "Updated the prompt:"},
    "what_improve": {"ru": "Что улучшить в промпте? Выберите или напишите своими словами.", "en": "What to improve? Pick one or type your own."},
    "settings_saved": {"ru": "Готово: {label}.", "en": "Done: {label}."},
    "summary_head": {"ru": "Проверьте и запускайте:", "en": "Check and run:"},
    "for_sec": {"ru": "за {sec} с", "en": "for {sec}s"},
    # --- сравнение / цены ---
    "compare_head": {"ru": "Сравнение:", "en": "Comparison:"},
    "price_head": {"ru": "Цены сейчас:", "en": "Current prices:"},
    "price_unknown": {"ru": "цена уточняется", "en": "price TBD"},
    "free": {"ru": "бесплатно", "en": "free"},
    # --- служебные ответы ---
    "hello": {
        "ru": "Здравствуйте! Помогу выбрать модель и написать промпт.\nЧто создаём?",
        "en": "Hello! I'll help you pick a model and write the prompt.\nWhat shall we create?",
    },
    "thanks": {"ru": "Пожалуйста! Что ещё создадим?", "en": "You're welcome! What else shall we create?"},
    "who": {
        "ru": "Я Яишенка — помощник студии.\nПодбираю модель, пишу промпт, подсказываю по интерфейсу.",
        "en": "I'm Eggy, the studio assistant.\nI pick models, write prompts and help with the interface.",
    },
    "off_topic": {
        "ru": "Я помогаю только с генерациями: видео, картинки, музыка, правка фото.\nЧто создадим?",
        "en": "I can only help with generations: video, images, music, photo edits.\nWhat shall we create?",
    },
    "injection": {
        "ru": "Я помогаю только с генерациями в студии.\nЧто создаём?",
        "en": "I only help with generations in the studio.\nWhat shall we create?",
    },
    "safety": {
        "ru": "С этим помочь не могу — это против правил площадки.\nМогу предложить безопасный вариант: опишите идею иначе.",
        "en": "I can't help with that — it's against the platform rules.\nI can suggest a safe alternative: describe the idea differently.",
    },
    "safety_person": {
        "ru": "Не создаю изображения реальных людей без их согласия.\nМогу сделать вымышленного персонажа в похожем образе.",
        "en": "I don't create images of real people without consent.\nI can make a fictional character with a similar look.",
    },
    "crisis": {
        "ru": "Мне жаль, что вам сейчас тяжело. Вы не одни.\nБесплатная линия помощи: 8-800-2000-122\nhttps://www.iasp.info/suicidalthoughts/",
        "en": "I'm sorry you're going through this. You're not alone.\nFind a helpline: https://www.iasp.info/suicidalthoughts/",
    },
    "degraded": {"ru": "(помощник по промптам сейчас перегружен — дала базовый вариант)", "en": "(prompt helper is busy — basic version)"},
}

# подписи кнопок
B: dict[str, dict[str, str]] = {
    "pick": {"ru": "Выбрать {title}", "en": "Choose {title}"},
    "more": {"ru": "Ещё варианты", "en": "More options"},
    "edit_prompt": {"ru": "Изменить промпт", "en": "Edit prompt"},
    "generate": {"ru": "Сгенерировать", "en": "Generate"},
    "use_mine": {"ru": "Вернуть мой текст", "en": "Use my text"},
    "other_model": {"ru": "Другая модель", "en": "Another model"},
    "open_models": {"ru": "Открыть модели", "en": "Open models"},
    "topup": {"ru": "Пополнить", "en": "Top up"},
    "login": {"ru": "Войти", "en": "Sign in"},
    "retry": {"ru": "Повторить", "en": "Retry"},
    "wait": {"ru": "Подождать", "en": "Wait"},
    "attach": {"ru": "Прикрепить фото", "en": "Attach photo"},
    "vitrina": {"ru": "Открыть витрину", "en": "Open showcase"},
    "support": {"ru": "Написать в поддержку", "en": "Contact support"},
    "cheaper": {"ru": "Модель дешевле", "en": "Cheaper model"},
    "faster": {"ru": "Модель быстрее", "en": "Faster model"},
    "similar": {"ru": "Похожая модель", "en": "Similar model"},
    "no_photo_model": {"ru": "Модель без фото", "en": "Model without photo"},
    "rephrase": {"ru": "Переформулировать", "en": "Rephrase"},
    "improve": {"ru": "Улучшить промпт", "en": "Improve prompt"},
    "mine": {"ru": "Мой текст", "en": "My text"},
    "type_video": {"ru": "Видео", "en": "Video"},
    "type_image": {"ru": "Картинка", "en": "Image"},
    "type_edit": {"ru": "Правка фото", "en": "Photo edit"},
    "type_music": {"ru": "Музыка", "en": "Music"},
    "type_sfx": {"ru": "Звук", "en": "Sound"},
    "ex_video": {"ru": "Видео: яичница танцует", "en": "Video: dancing fried egg"},
    "ex_image": {"ru": "Логотип кофейни", "en": "Coffee shop logo"},
    "ex_music": {"ru": "Трек для рилса", "en": "Track for a reel"},
}

REFINE_SUGGEST = {
    "image": {"ru": ["Больше деталей", "Ярче цвета", "Как настоящее фото", "Мультяшный стиль"],
              "en": ["More detail", "Brighter colors", "Photorealistic", "Cartoon style"]},
    "edit": {"ru": ["Аккуратнее", "Сохранить лицо", "Ярче цвета", "Другой фон"],
             "en": ["More subtle", "Keep the face", "Brighter colors", "Different background"]},
    "video": {"ru": ["Кинематографично", "Больше движения", "Плавная камера", "Ночная сцена"],
              "en": ["Cinematic", "More motion", "Smooth camera", "Night scene"]},
    "music": {"ru": ["Энергичнее", "Спокойнее", "Добавить вокал", "Больше баса"],
              "en": ["More energetic", "Calmer", "Add vocals", "More bass"]},
    "sfx": {"ru": ["Громче", "Тише и дальше", "Добавить эхо", "Короче"],
            "en": ["Louder", "Softer, distant", "Add echo", "Shorter"]},
}

EXAMPLES = {
    "ex_video": {"ru": "Вертикальное видео 5 секунд: яичница танцует на сковородке", "en": "Vertical 5-second video: a fried egg dancing in a pan"},
    "ex_image": {"ru": "Логотип кофейни «Утро» с яйцом", "en": "Logo for a coffee shop “Morning” with an egg"},
    "ex_music": {"ru": "Весёлый трек 30 секунд для рилса", "en": "Upbeat 30-second track for a reel"},
}


def t(key: str, lang: str, **kw) -> str:
    row = T[key]
    s = row.get(lang) or row["ru"]
    return s.format(**kw) if kw else s


def b(key: str, lang: str, **kw) -> str:
    row = B[key]
    s = row.get(lang) or row["ru"]
    return s.format(**kw) if kw else s
