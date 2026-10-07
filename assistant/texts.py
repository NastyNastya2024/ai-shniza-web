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
    "ask_type_idea": {"ru": "По идее «{topic}» нейросеть может сделать картинку, видео или музыку — что выберем?", "en": "For “{topic}” AI can make an image, a video or music — which one?"},
    "ask_type_plain": {"ru": "Нейросеть сделает это картинкой, видео или музыкой — что выберем?", "en": "AI can make it an image, a video or music — which one?"},
    "ask_type_again": {"ru": "Не поняла 🙂 Выберите кнопкой: картинка, видео или музыка.", "en": "Sorry, didn't get that 🙂 Pick a button: image, video or music."},
    "models_head": {"ru": "Подобрала {n} модели для «{topic}». Нажмите на карточку:", "en": "{n} models for “{topic}”. Tap a card:"},
    "models_head_plain": {"ru": "Подобрала {n} модели. Нажмите на карточку:", "en": "{n} models for you. Tap a card:"},
    "prompt_ready": {"ru": "Переписала промпт под {title}. Проверьте настройки:", "en": "Adapted the prompt for {title}. Check the settings:"},
    "prompt_ready_simple": {"ru": "Промпт для {title}. Проверьте настройки:", "en": "Prompt for {title}. Check the settings:"},
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
        "ru": "Здравствуйте! Здесь нейросети делают видео, картинки и музыку по вашему описанию.\nОпишите идею — подберу модель, напишу промпт и покажу цену. С чего начнём?",
        "en": "Hello! Here AI models make videos, images and music from your description.\nDescribe the idea — I'll pick a model, write the prompt and show the price. Where do we start?",
    },
    "thanks": {"ru": "Пожалуйста! Что ещё создадим?", "en": "You're welcome! What else shall we create?"},
    "who": {
        "ru": "Я Яишенка — помощник студии, где нейросети делают видео, картинки и музыку.\nПодбираю модель под задачу, пишу промпт и показываю цену до запуска.",
        "en": "I'm Eggy, the assistant of a studio where AI makes videos, images and music.\nI pick the model, write the prompt and show the price before you run it.",
    },
    "off_topic": {
        "ru": "Здесь нейросети делают видео, картинки и музыку — с этим и помогаю.\nОпишите, что создать, или выберите пример:",
        "en": "Here AI makes videos, images and music — that's what I help with.\nDescribe what to create or pick an example:",
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
    "degraded": {"ru": "Промпт собран по шаблону: нейросеть-редактор сейчас не отвечает. Текст можно поправить прямо в карточке.",
                 "en": "The prompt is built from a template: the AI editor isn't responding right now. You can edit the text in the card."},
    # --- бриф: понять суть, уточнить, дать варианты ---
    "need_subject_video": {"ru": "Расскажите подробнее о видео:\n• Кто в кадре?\n• Где это происходит?\n• Что происходит — какое действие?\n• Какая атмосфера?\n• Нюансы: время суток, цвета, стиль, звук?",
                           "en": "Tell me more about the video:\n• Who is in the frame?\n• Where does it happen?\n• What happens — what action?\n• What atmosphere?\n• Nuances: time of day, colors, style, sound?"},
    "need_subject_image": {"ru": "Расскажите подробнее о картинке:\n• Кто или что изображено?\n• Где, какой фон?\n• В каком стиле?\n• Какая атмосфера?\n• Нюансы: цвета, свет, детали, текст на картинке?",
                           "en": "Tell me more about the image:\n• Who or what is shown?\n• Where, what background?\n• What style?\n• What atmosphere?\n• Nuances: colors, light, details, text in the image?"},
    "need_subject_edit": {"ru": "Что сделать с фото?\n• Что изменить или убрать?\n• Что оставить как есть?\n• Какой нужен результат: аккуратно или заметно?",
                          "en": "What to do with the photo?\n• What to change or remove?\n• What to keep as is?\n• Result: subtle or noticeable?"},
    "need_subject_music": {"ru": "Расскажите подробнее о треке:\n• Для чего он: ролик, фон, песня?\n• Жанр?\n• Настроение и темп?\n• С вокалом или без?\n• Нюансы: инструменты, длительность?",
                           "en": "Tell me more about the track:\n• What is it for: video, background, song?\n• Genre?\n• Mood and tempo?\n• Vocals or instrumental?\n• Nuances: instruments, length?"},
    "need_subject_sfx": {"ru": "Расскажите подробнее о звуке:\n• Что звучит?\n• Где — в помещении, на улице?\n• Какой характер: мягкий, резкий, ритмичный?",
                         "en": "Tell me more about the sound:\n• What makes the sound?\n• Where — indoors, outdoors?\n• Character: soft, sharp, rhythmic?"},
    "junk": {"ru": "Не совсем поняла 🙂 Опишите словами: кто в кадре, где и что происходит.", "en": "Sorry, I didn't get that 🙂 Please describe in words: who, where and what happens."},
    "brief_head": {"ru": "Уточню детали — так промпт получится точнее. Ответьте одним сообщением или выберите кнопки:", "en": "Let me clarify a few details. Answer in one message or use the buttons:"},
    "brief_head_summary": {"ru": "Поняла так: {summary}. Уточню детали — ответьте одним сообщением или выберите кнопки:", "en": "Got it: {summary}. A few details — answer in one message or use the buttons:"},
    "brief_saved": {"ru": "Добавила: {detail}.", "en": "Added: {detail}."},
    "variants_head": {"ru": "Собрала варианты промпта под {title} — выберите один, потом его можно поправить:", "en": "Prompt options for {title} — pick one, you can edit it later:"},
    "variants_simple": {"ru": "Варианты промпта под {title} (по шаблону) — выберите один:", "en": "Prompt options for {title} (template) — pick one:"},
    "variant_chosen": {"ru": "Беру вариант «{title}». Проверьте настройки:", "en": "Taking “{title}”. Check the settings:"},
    "refine_unclear": {"ru": "Не поняла, что поменять 🙂 Выберите подсказку или опишите подробнее:", "en": "Not sure what to change 🙂 Pick a hint or describe it in more detail:"},
    # --- перед запуском: сначала вход, потом баланс ---
    "gate_login": {"ru": "Всё настроено. Чтобы запустить генерацию, войдите в аккаунт — это пара секунд. После входа продолжим с этого места.",
                   "en": "All set. To run the generation, please sign in — it takes a few seconds. We'll continue right here after that."},
    "gate_topup": {"ru": "На балансе {have}, для запуска нужно ≈ {need}. Пополните баланс — и сразу запустим.",
                   "en": "Your balance is {have}, this run needs ≈ {need}. Top up and we'll start right away."},
    "gate_free": {"ru": "Всё готово: эта генерация бесплатная. Жмите «Сгенерировать».",
                  "en": "All set: this generation is free. Press “Generate”."},
    "gate_ready_cost": {"ru": "Всё готово: спишется ≈ {cost}. Жмите «Сгенерировать».",
                        "en": "All set: about {cost} will be charged. Press “Generate”."},
    "gate_ready": {"ru": "Всё готово — жмите «Сгенерировать».", "en": "All set — press “Generate”."},
    "resumed": {"ru": "Продолжаем с того же места:", "en": "Picking up where we left off:"},
    "nothing_to_resume": {"ru": "Опишите идею — нейросеть сделает видео, картинку или музыку.", "en": "Describe your idea — AI will make a video, image or music."},
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
    "resume_topup": {"ru": "Баланс пополнен — продолжить", "en": "Topped up — continue"},
    "build_variants": {"ru": "Собрать промпт", "en": "Build prompt"},
    "skip_brief": {"ru": "Пропустить", "en": "Skip"},
    "more_variants": {"ru": "Ещё варианты", "en": "More options"},
    "back_brief": {"ru": "Уточнить детали", "en": "Adjust details"},
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
    "video": {"ru": ["Рыжий кот жарит яичницу на кухне", "Космонавт гуляет по Марсу на закате", "Капли дождя на окне ночного города"],
              "en": ["A ginger cat frying eggs in a kitchen", "An astronaut walking on Mars at sunset", "Raindrops on a window of a night city"]},
    "image": {"ru": ["Логотип кофейни с яйцом", "Уютная кухня в стиле аниме", "Портрет лисы в очках"],
              "en": ["Coffee shop logo with an egg", "Cozy anime-style kitchen", "Portrait of a fox in glasses"]},
    "edit": {"ru": ["Заменить фон на пляж", "Убрать людей на заднем плане", "Сделать фото ярче"],
             "en": ["Replace background with a beach", "Remove people in the background", "Make the photo brighter"]},
    "music": {"ru": ["Весёлый трек для рилса про лето", "Спокойный лоу-фай для учёбы", "Эпичная музыка для трейлера"],
              "en": ["Upbeat summer track for a reel", "Calm lo-fi for studying", "Epic trailer music"]},
    "sfx": {"ru": ["Дождь по крыше", "Шаги по снегу", "Шум прибоя"], "en": ["Rain on a roof", "Steps in snow", "Ocean waves"]},
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
