#!/usr/bin/env python3
"""Merge per-model prompt profiles (clarify / structure / example / prompt_style) into model_cards.json."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "assistant" / "data" / "model_cards.json"

# clarify/structure: bilingual. prompt_example: as provided. prompt_style: EN instruction for LLM.
PROFILES: dict[str, dict] = {
    "seedance-2-5": {
        "prompt_style": (
            "English. Complex scenes with action sequence and visual consistency. "
            "Structure: main subject → place/setting → action sequence → camera → lighting/style → "
            "consistency requirements (keep appearance of key elements unchanged). "
            "1 coherent scene, 2-5 sentences. Mention sound/speech only if needed."
        ),
        "clarify": {
            "ru": ["Что происходит?", "Кто или что участвует?", "Какая последовательность действий?",
                   "Какое движение камеры?", "Какой стиль?", "Нужен ли звук или речь?", "Есть ли референсы?"],
            "en": ["What happens?", "Who or what is involved?", "What is the action sequence?",
                   "What camera move?", "What style?", "Do you need sound or speech?", "Any references?"],
        },
        "structure": {
            "ru": "главный объект → место и обстановка → последовательность действий → камера → освещение и стиль → требования к согласованности сцены",
            "en": "main subject → place and setting → action sequence → camera → lighting and style → scene consistency requirements",
        },
        "prompt_example": (
            "Сними кинематографичную рекламную сцену: молодая бариста готовит эспрессо в современной кофейне ранним утром. "
            "Она измельчает зёрна, фиксирует портафильтр и запускает кофемашину; тонкая струя кофе наполняет керамическую чашку. "
            "Камера плавно движется от общего плана стойки к крупному плану экстракции. Мягкий солнечный свет, естественные движения рук, "
            "реалистичный пар, тёплая палитра, сдержанная рекламная эстетика. Сохраняй неизменными внешний вид бариста, чашки и кофемашины на протяжении сцены."
        ),
    },
    "wan-3-0": {
        "prompt_style": (
            "English. Clear scene and motion; respect text-to-video vs image-to-video. "
            "Structure: subject and environment → action and physical motion → camera → lighting → style → "
            "source-image constraints if an image is used. One coherent scene, concise."
        ),
        "clarify": {
            "ru": ["Текст или изображение на входе?", "Кто или что — субъект?", "Какое действие?",
                   "Какой фон?", "Какое движение камеры?", "Какой визуальный стиль?",
                   "Что должно сохраниться из исходника?"],
            "en": ["Text or image as input?", "Who or what is the subject?", "What action?",
                   "What background?", "What camera move?", "What visual style?",
                   "What must stay from the source?"],
        },
        "structure": {
            "ru": "объект и окружение → действие и физическое движение → камера → освещение → стиль → ограничения для исходного изображения, если оно есть",
            "en": "subject and environment → action and physical motion → camera → lighting → style → source-image constraints if any",
        },
        "prompt_example": (
            "На узкой городской улице после дождя рыжий кот медленно идёт по мокрой брусчатке и останавливается у витрины с тёплым светом. "
            "В лужах отражаются окна и фонари. Камера движется параллельно коту на уровне его глаз, затем плавно приближается к морде. "
            "Естественная походка, реалистичная шерсть, мягкий вечерний свет, спокойная кинематографичная атмосфера. "
            "Сохраняй непрерывность движения и естественную анатомию кота."
        ),
    },
    "veo-3-1": {
        "prompt_style": (
            "English. Cinematic staging; include dialogue and soundscape when relevant. "
            "Structure: scene and characters → action → camera direction → lighting/visual aesthetic → "
            "spoken lines → sound environment. One coherent scene unless multi-shot is explicitly needed."
        ),
        "clarify": {
            "ru": ["Какой тип сцены?", "Какое действие?", "Какие планы и движение камеры?",
                   "Нужна ли речь и на каком языке?", "Какие фоновые звуки?", "Какое настроение?",
                   "Нужны ли начальный и конечный кадры?"],
            "en": ["What type of scene?", "What action?", "What shots and camera moves?",
                   "Any speech, and in which language?", "What background sounds?", "What mood?",
                   "Any first/last frame constraints?"],
        },
        "structure": {
            "ru": "сцена и персонажи → действие → операторская постановка → освещение и визуальная эстетика → реплики → звуковая среда",
            "en": "scene and characters → action → camera direction → lighting and visual aesthetic → dialogue → soundscape",
        },
        "prompt_example": (
            "Кинематографичная сцена в маленькой пекарне Парижа на рассвете. Пекарь вынимает золотистый круассан из печи и осторожно "
            "кладёт его на деревянную доску. Камера начинает с крупного плана выпечки, затем плавно отъезжает, открывая тёплую пекарню. "
            "Естественный свет из окна, лёгкий пар, реалистичные текстуры. Звук: мягкий звон противней, шелест бумаги, приглушённый городской "
            "шум за окном. Пекарь тихо говорит по-французски: «C'est prêt». Голос естественный, синхронизирован с движением губ."
        ),
    },
    "veo-3-1-fast": {
        "prompt_style": (
            "English. Clear staging, no fluff. "
            "Structure: subject + action + environment + camera + light/style + essential sounds only. "
            "Drop secondary details that do not affect the result. One short scene."
        ),
        "clarify": {
            "ru": ["Кто или что — главный объект?", "Какое одно основное действие?", "Какая камера?",
                   "Какой визуальный стиль?", "Нужен ли звук?"],
            "en": ["What is the main subject?", "What single main action?", "What camera?",
                   "What visual style?", "Is sound needed?"],
        },
        "structure": {
            "ru": "субъект + действие + окружение + камера + свет и стиль + обязательные звуки",
            "en": "subject + action + environment + camera + light and style + essential sounds",
        },
        "prompt_example": (
            "Фотореалистичный крупный план стеклянного стакана с холодным кофе на солнечной террасе. "
            "Капли конденсата медленно стекают по стеклу, лёд слегка движется при наливании молока. "
            "Камера плавно приближается сбоку. Яркий естественный свет, чёткие отражения, мягкий фон. "
            "Звук льда и жидкости, без музыки и речи."
        ),
    },
    "kling-v2-5-turbo-pro": {
        "prompt_style": (
            "English. One clear action, expressive camera, realistic motion physics. "
            "Structure: subject and scene → one main action → camera path → environment dynamics → "
            "style and physical plausibility. Avoid jump cuts and multi-scene scripts."
        ),
        "clarify": {
            "ru": ["Исходный кадр или текстовый запрос?", "Какое движение субъекта?",
                   "Какая траектория камеры?", "Какая скорость движения?", "Какое настроение?", "Какой формат кадра?"],
            "en": ["Source frame or text prompt?", "What subject motion?",
                   "What camera path?", "What motion speed?", "What mood?", "What frame format?"],
        },
        "structure": {
            "ru": "субъект и сцена → одно основное действие → движение камеры → динамика окружения → стиль и физическая правдоподобность",
            "en": "subject and scene → one main action → camera motion → environment dynamics → style and physical plausibility",
        },
        "prompt_example": (
            "Чёрный спортивный автомобиль быстро проезжает по мокрой дороге в ночном мегаполисе. "
            "Вода разлетается из-под колёс, неоновые вывески отражаются на кузове. "
            "Камера низко расположена сбоку и плавно отслеживает автомобиль, сохраняя его в центре кадра. "
            "Реалистичная физика движения, естественный motion blur, контрастный кинематографичный свет, без резких скачков камеры."
        ),
    },
    "kling-v3-0-hf": {
        "prompt_style": (
            "English. More detailed direction, character interaction, scene continuity. "
            "Structure: place and characters → event sequence → interactions → camera/editing → "
            "dialogue and sound → appearance continuity. Prefer one scene unless interaction needs short beats."
        ),
        "clarify": {
            "ru": ["Сколько персонажей?", "Что делает каждый?", "Какой порядок событий?",
                   "Нужны ли диалоги?", "Какие движения камеры?", "Есть ли визуальные референсы?", "Какой желаемый финал?"],
            "en": ["How many characters?", "What does each do?", "What event order?",
                   "Any dialogue?", "What camera moves?", "Any visual references?", "Desired ending?"],
        },
        "structure": {
            "ru": "место и персонажи → последовательность событий → взаимодействия → камера и монтаж → диалоги и звук → непрерывность внешности",
            "en": "place and characters → event sequence → interactions → camera and editing → dialogue and sound → appearance continuity",
        },
        "prompt_example": (
            "Вечер в небольшой цветочной студии. Флористка выбирает белую розу из букета, а затем передаёт её покупателю через стойку. "
            "Покупатель улыбается и благодарно кивает. Средний план переходит в крупный план рук, передающих цветок, затем возвращается к лицам. "
            "Мягкое тёплое освещение, естественная мимика, реалистичные жесты, спокойный темп монтажа. "
            "Сохраняй внешность обоих персонажей и положение букета между планами."
        ),
    },
    "pixverse-v6": {
        "prompt_style": (
            "English. Expressive action, visual effect, dynamics, stylistic unity. "
            "Structure: main subject → notable action → dynamics and effects → camera → visual style → "
            "frame cleanliness (no random elements). One coherent beat."
        ),
        "clarify": {
            "ru": ["Какой жанр видео?", "Какой объект?", "Какое действие?", "Какая скорость?",
                   "Какой визуальный эффект?", "Какая камера?", "Какой стиль?", "Есть ли референс или начальное изображение?"],
            "en": ["What video genre?", "What subject?", "What action?", "What speed?",
                   "What visual effect?", "What camera?", "What style?", "Any reference or start image?"],
        },
        "structure": {
            "ru": "главный объект → заметное действие → динамика и эффекты → камера → визуальная стилистика → требования к чистоте кадра",
            "en": "main subject → notable action → dynamics and effects → camera → visual style → frame cleanliness requirements",
        },
        "prompt_example": (
            "Стилизованная трёхмерная сцена: прозрачная стеклянная бабочка раскрывает крылья на ладони персонажа, после чего взлетает "
            "и оставляет за собой тонкий след светящихся частиц. Камера плавно следует за бабочкой, делая небольшой круговой пролёт. "
            "Иридесцентные поверхности, мягкий контровой свет, глубокий синий фон, плавная анимация, цельный дизайн объекта и отсутствие случайных элементов."
        ),
    },
    "p-video": {
        "prompt_style": (
            "English. Preliminary profile — keep prompts generic and reliable. "
            "Structure: brief scene → motion → camera → lighting → style → constraints. "
            "Do not invent unsupported special tags."
        ),
        "clarify": {
            "ru": ["Какой тип генерации?", "Какие входные материалы?", "Кто или что — субъект?",
                   "Какое действие?", "Какое окружение?", "Какая камера?", "Какой стиль?", "Какие обязательные ограничения?"],
            "en": ["What generation type?", "What input materials?", "Who or what is the subject?",
                   "What action?", "What environment?", "What camera?", "What style?", "What hard constraints?"],
        },
        "structure": {
            "ru": "краткое описание сцены → движение → камера → освещение → стиль → ограничения",
            "en": "brief scene → motion → camera → lighting → style → constraints",
        },
        "prompt_example": (
            "Небольшой бумажный кораблик плывёт по тихому ручью в весеннем лесу. Вода мягко обтекает корпус, рядом проплывают опавшие лепестки. "
            "Камера движется на уровне воды вслед за корабликом. Рассеянный солнечный свет проходит сквозь листья, натуральные текстуры воды и бумаги, "
            "спокойная кинематографичная композиция, непрерывное реалистичное движение."
        ),
    },
    "hailuo-02": {
        "prompt_style": (
            "English. Concrete motion dynamics, expressive subject, plausible physics. "
            "Structure: subject → dynamic action → environment reaction → camera → light and texture → "
            "smoothness requirements. One continuous action."
        ),
        "clarify": {
            "ru": ["Какой объект?", "Какое основное движение?", "Какая эмоция или состояние?",
                   "Какая камера?", "Какая скорость?", "Какое окружение?", "Есть ли исходный кадр?"],
            "en": ["What subject?", "What main motion?", "What emotion or state?",
                   "What camera?", "What speed?", "What environment?", "Is there a source frame?"],
        },
        "structure": {
            "ru": "субъект → динамическое действие → реакция окружения → камера → свет и фактура → требования к плавности",
            "en": "subject → dynamic action → environment reaction → camera → light and texture → smoothness requirements",
        },
        "prompt_example": (
            "Крупный план золотистого ретривера, бегущего по мелководью на пляже. Собака радостно встряхивает головой, "
            "капли воды разлетаются в воздухе, у лап образуются небольшие брызги. Камера плавно движется рядом на уровне собаки. "
            "Мягкий утренний свет, естественная шерсть, реалистичная физика воды, живая, но плавная динамика."
        ),
    },
    "gemini-omni-flash": {
        "prompt_style": (
            "English. Multimodal context — reconcile multiple inputs when present. "
            "Structure: task → how to use references → action → visual staging → sound → what must stay unchanged."
        ),
        "clarify": {
            "ru": ["Текст или референсы на входе?", "Что взять из каждого входа?", "Какое желаемое действие?",
                   "Какая камера?", "Нужен ли звук?", "Какие детали должны остаться неизменными?"],
            "en": ["Text or references as input?", "What to take from each input?", "Desired action?",
                   "What camera?", "Any sound?", "What details must stay unchanged?"],
        },
        "structure": {
            "ru": "задача → интерпретация референсов → действие → визуальная постановка → звук → ограничения",
            "en": "task → reference interpretation → action → visual staging → sound → constraints",
        },
        "prompt_example": (
            "Используй загруженное изображение кофейни как основной визуальный референс: сохрани оформление стойки, мебель и цветовую палитру. "
            "Покажи, как бариста ставит чашку капучино на стойку перед посетителем. Камера плавно приближается к чашке, затем переводит фокус на руки бариста. "
            "Естественное движение, мягкий дневной свет, реалистичная пена на кофе. Фоновый звук кофемашины и негромкие разговоры, без отчётливой чужой речи."
        ),
    },
    "minimax-h3": {
        "prompt_style": (
            "English. Preliminary profile. "
            "Structure: subject → action and its development → camera → environment → visual aesthetic → continuity. "
            "One continuous scene."
        ),
        "clarify": {
            "ru": ["Какой режим генерации?", "Какой объект?", "Какое действие?", "Какая длительность действия?",
                   "Какое движение камеры?", "Какой стиль?", "Есть ли исходный материал?"],
            "en": ["What generation mode?", "What subject?", "What action?", "How long is the action?",
                   "What camera move?", "What style?", "Any source material?"],
        },
        "structure": {
            "ru": "субъект → действие и его развитие → камера → окружение → визуальная эстетика → требования к непрерывности",
            "en": "subject → action and its development → camera → environment → visual aesthetic → continuity requirements",
        },
        "prompt_example": (
            "На открытой террасе девушка медленно раскрывает красный зонт под лёгким летним дождём. "
            "Капли собираются на ткани и скатываются по краям. Камера плавно приближается от среднего плана к крупному, затем немного смещается в сторону. "
            "Натуральная кожа и ткань, мягкий пасмурный свет, реалистичные капли, спокойная кинематографичная атмосфера."
        ),
    },
    "grok-imagine-video-1-5": {
        "prompt_style": (
            "English. Short, expressive action and visual situation. "
            "Structure: subject and context → action → reaction or effect → camera → style and constraints. "
            "Keep it punchy."
        ),
        "clarify": {
            "ru": ["Кто или что — субъект?", "Какое действие?", "Какой стиль: комедия, реализм или художественный?",
                   "Какая камера?", "Какой желаемый эффект?", "Есть ли исходное изображение?"],
            "en": ["Who or what is the subject?", "What action?", "Style: comedy, realism, or artistic?",
                   "What camera?", "Desired effect?", "Any source image?"],
        },
        "structure": {
            "ru": "субъект и контекст → действие → реакция или эффект → камера → стиль и ограничения",
            "en": "subject and context → action → reaction or effect → camera → style and constraints",
        },
        "prompt_example": (
            "Маленький корги в oversized солнечных очках уверенно входит в современное кафе, запрыгивает на свободный диван и поворачивает голову к камере. "
            "Камера слегка отъезжает, подчёркивая комичную серьёзность собаки. Естественная анимация, реалистичная шерсть, тёплый свет, "
            "чистая композиция, игривый рекламный стиль."
        ),
    },
    "gen4-turbo": {
        "prompt_style": (
            "English. Camera motion, scene transformation, preserve source image style when present. "
            "Structure: source scene → specific subject motion → camera path → environment changes → "
            "composition/style preservation constraints."
        ),
        "clarify": {
            "ru": ["Используется ли исходное изображение?", "Что должно двигаться?", "Что остаётся неподвижным?",
                   "Какая траектория камеры?", "Какая интенсивность движения?"],
            "en": ["Is a source image used?", "What should move?", "What stays still?",
                   "What camera path?", "How intense is the motion?"],
        },
        "structure": {
            "ru": "описание исходной сцены → конкретное движение субъекта → движение камеры → изменения в окружении → ограничения на сохранение композиции",
            "en": "source scene → specific subject motion → camera motion → environment changes → composition preservation constraints",
        },
        "prompt_example": (
            "Используй исходное изображение архитектурного дворика. Камера медленно движется вперёд по центральной дорожке, "
            "слегка поворачивая вправо и открывая вид на фонтан. Вода непрерывно струится, листья деревьев едва колышутся на ветру, "
            "солнечные блики мягко перемещаются по каменной поверхности. Сохраняй геометрию зданий, архитектурные детали, цветовую палитру и реалистичные пропорции."
        ),
    },
    "soul-cinema": {
        "prompt_style": (
            "English. Cinematic still: story, mood, composition, light, color grade, texture. "
            "Structure: story and main subject → composition → cinematic light → color grade → texture and visual genre."
        ),
        "clarify": {
            "ru": ["Какой сюжет?", "Кто персонажи?", "Какой жанр и настроение?", "Какая композиция?",
                   "Какое освещение?", "Какая цветовая палитра?", "Какая степень реализма?"],
            "en": ["What story?", "Who are the characters?", "What genre and mood?", "What composition?",
                   "What lighting?", "What color palette?", "How realistic?"],
        },
        "structure": {
            "ru": "сюжет и главный объект → композиция → кинематографический свет → цветокоррекция → фактура и визуальный жанр",
            "en": "story and main subject → composition → cinematic light → color grade → texture and visual genre",
        },
        "prompt_example": (
            "Кинематографичный портрет молодой женщины у окна старого парижского кафе в дождливый вечер. "
            "Она смотрит на отражения огней на стекле, её лицо освещено мягким тёплым светом лампы. "
            "Крупный план, небольшая глубина резкости, отражения города на переднем плане, приглушённые янтарные и синие тона, "
            "естественная текстура кожи, тонкое плёночное зерно, меланхоличная атмосфера авторского кино."
        ),
    },
    "seedream-5-pro": {
        "prompt_style": (
            "English. Complex composition, references, precise visual brief. "
            "Structure: image purpose → objects and layout → materials and details → lighting and style → "
            "text/reference requirements. Ask purpose (ad, product, poster, etc.) shapes composition."
        ),
        "clarify": {
            "ru": ["Какое назначение изображения?", "Какой главный объект?", "Какая композиция?",
                   "Какой стиль?", "Нужен ли текст на изображении?", "Есть ли референсы?",
                   "Какие элементы должны совпадать или сочетаться?"],
            "en": ["What is the image for?", "What is the main subject?", "What composition?",
                   "What style?", "Any on-image text?", "Any references?",
                   "Which elements must match or combine?"],
        },
        "structure": {
            "ru": "цель изображения → объекты и их взаимное расположение → материалы и детали → освещение и стиль → требования к тексту и референсам",
            "en": "image purpose → objects and layout → materials and details → lighting and style → text and reference requirements",
        },
        "prompt_example": (
            "Создай премиальную рекламную фотографию флакона парфюма из прозрачного стекла с матовой чёрной крышкой. "
            "Флакон расположен в центре на светлом каменном постаменте, рядом лежит одна веточка белого жасмина. "
            "Боковой мягкий свет подчёркивает толщину стекла и реалистичные отражения. Фон молочно-бежевый, композиция минималистичная, "
            "с большим количеством свободного пространства сверху. Фотореализм, дорогая журнальная эстетика, без дополнительных предметов и надписей."
        ),
    },
    "gpt-image-2": {
        "prompt_style": (
            "English. Detailed natural-language brief with spatial relations and exact constraints. "
            "Structure: result and purpose → main subject → composition/placement → style and light → "
            "verbatim text if needed → constraints."
        ),
        "clarify": {
            "ru": ["Что создать?", "Для чего?", "Кто или что — субъект?", "Какая композиция?",
                   "Какой текст и язык надписей?", "Какой стиль?", "Какие размеры и соотношение сторон?", "Есть ли референсы?"],
            "en": ["What to create?", "What is it for?", "Who or what is the subject?", "What composition?",
                   "What text and language?", "What style?", "What size and aspect ratio?", "Any references?"],
        },
        "structure": {
            "ru": "результат и его назначение → главный объект → композиция и расположение → стиль и свет → текст дословно, если нужен → ограничения",
            "en": "result and purpose → main subject → composition and placement → style and light → verbatim text if needed → constraints",
        },
        "prompt_example": (
            "Создай квадратную рекламную иллюстрацию для бренда specialty coffee. В центре — керамическая чашка с капучино на небольшом столике из светлого дуба. "
            "Рядом лежит раскрытая книга и одна веточка оливы. Мягкий утренний свет падает слева, создавая естественные тени. "
            "Палитра: кремовый, тёплый коричневый и приглушённый оливковый. Современная редакционная фотография, реалистичные материалы, спокойная композиция. "
            "Не добавляй логотипы, текст или лишние предметы."
        ),
    },
    "gpt-image-2-5-flare": {
        "prompt_style": (
            "English. Clear brief, prioritize essential details, keep it short. "
            "Structure: short task core → main subject → 2-4 key details → style and lighting → constraints."
        ),
        "clarify": {
            "ru": ["Какой главный объект?", "Какая цель?", "Какие ключевые визуальные характеристики?",
                   "Какая композиция?", "Какой стиль?", "Какие надписи нужны?", "Какие обязательные ограничения?"],
            "en": ["What is the main subject?", "What purpose?", "Which key visual traits?",
                   "What composition?", "What style?", "Any required text?", "Hard constraints?"],
        },
        "structure": {
            "ru": "короткое ядро задачи → главный объект → 2–4 ключевые детали → стиль и освещение → ограничения",
            "en": "short task core → main subject → 2–4 key details → style and lighting → constraints",
        },
        "prompt_example": (
            "Создай минималистичный рекламный кадр беспроводных наушников цвета графит на светло-сером фоне. "
            "Наушники расположены под углом на матовой поверхности, мягкий направленный свет подчёркивает форму и фактуру корпуса. "
            "Современная технологичная эстетика, чистые края, реалистичные тени, много свободного пространства справа. Без текста и логотипов."
        ),
    },
    "gpt-image-2-5-sunburst": {
        "prompt_style": (
            "English. High-quality complex composition, fine details, strict constraints. "
            "Structure: artistic task → composition hierarchy → main-object details → lighting and materials → "
            "secondary elements → hard constraints."
        ),
        "clarify": {
            "ru": ["Какая цель изображения?", "Какая иерархия объектов?", "Какая композиция?",
                   "Какие материалы?", "Нужен ли текст?", "Есть ли референсы?", "Какие важные мелкие детали?"],
            "en": ["What is the image for?", "What object hierarchy?", "What composition?",
                   "What materials?", "Any text?", "Any references?", "Which fine details matter?"],
        },
        "structure": {
            "ru": "художественная задача → композиционная иерархия → подробности главного объекта → освещение и материалы → второстепенные элементы → строгие ограничения",
            "en": "artistic task → composition hierarchy → main-object details → lighting and materials → secondary elements → hard constraints",
        },
        "prompt_example": (
            "Создай высокодетализированный журнальный натюрморт для осеннего выпуска о дизайне. "
            "На тёмном ореховом столе расположены скульптурная керамическая ваза, три сухих листа и раскрытый журнал с пустыми страницами. "
            "Ваза — главный визуальный акцент; её матовая поверхность имеет тонкую фактуру. Косой луч золотистого света создаёт длинные мягкие тени. "
            "Глубокие коричневые, терракотовые и кремовые оттенки, изысканная редакционная фотография, реалистичные материалы. "
            "Не добавляй лишние предметы, декоративные надписи или логотипы."
        ),
    },
    "ideogram-v3-turbo": {
        "prompt_style": (
            "English. Typography, posters, ad graphics, readable text. "
            "Structure: graphic type → verbatim copy → text hierarchy → fonts and placement → visual elements → "
            "background and palette. Put required text in quotes exactly."
        ),
        "clarify": {
            "ru": ["Какое назначение макета?", "Какой точный текст?", "На каком языке?",
                   "Какая иерархия заголовка и подзаголовка?", "Какой характер шрифта?",
                   "Какая композиция?", "Какая палитра?", "Какой формат?"],
            "en": ["What is the layout for?", "What exact text?", "Which language?",
                   "Headline vs subtitle hierarchy?", "What font character?",
                   "What composition?", "What palette?", "What format?"],
        },
        "structure": {
            "ru": "тип графического материала → дословные надписи → иерархия текста → шрифты и расположение → визуальные элементы → фон и палитра",
            "en": "graphic type → verbatim copy → text hierarchy → fonts and placement → visual elements → background and palette",
        },
        "prompt_example": (
            "Создай вертикальный минималистичный постер для кофейного фестиваля. Главный заголовок должен быть написан точно: «КОФЕ И ГОРОД». "
            "Подзаголовок: «Фестиваль независимых обжарщиков». Размести заголовок в верхней трети постера крупным геометрическим гротеском. "
            "В нижней части — лаконичная иллюстрация чашки кофе и стилизованных городских зданий. Палитра: чёрный, молочный и оранжевый. "
            "Чёткая типографическая иерархия, высокий контраст, много свободного пространства. Не добавляй никаких других надписей."
        ),
    },
    "nano-banana-pro": {
        "prompt_style": (
            "English. Complex edit: state what changes AND what stays. "
            "Structure: identify source → specific changes → placement of new elements → preserved traits → "
            "realistic integration (perspective, light, shadows)."
        ),
        "clarify": {
            "ru": ["Какое изображение редактируем?", "Что изменить?", "Что оставить без изменений?",
                   "Какой желаемый результат?", "Какие референсы использовать?"],
            "en": ["Which image are we editing?", "What to change?", "What to keep unchanged?",
                   "Desired result?", "Which references to use?"],
        },
        "structure": {
            "ru": "идентификация исходника → конкретные изменения → точное расположение новых элементов → сохраняемые характеристики → реалистичность интеграции",
            "en": "identify source → specific changes → exact placement of new elements → preserved traits → realistic integration",
        },
        "prompt_example": (
            "Отредактируй загруженную фотографию интерьера. Замени серый диван на диван из светло-бежевого букле с округлыми подлокотниками. "
            "Сохрани исходное расположение мебели, ракурс камеры, геометрию комнаты, цвет стен и положение окна. "
            "Новый диван должен соответствовать перспективе и масштабу исходного изображения. "
            "Согласуй освещение, контактные тени и отражения с существующим дневным светом. Не меняй другие предметы интерьера."
        ),
    },
    "nano-banana-2": {
        "prompt_style": (
            "English. Point edits and concrete instructions. "
            "Structure: operation → object → desired change → preserved details → natural look."
        ),
        "clarify": {
            "ru": ["Какой объект меняем?", "Какое новое состояние?", "Что нельзя менять?",
                   "Нужна замена, удаление или добавление объекта?"],
            "en": ["What object to change?", "What new state?", "What must not change?",
                   "Replace, remove, or add?"],
        },
        "structure": {
            "ru": "операция → объект → желаемое изменение → сохраняемые детали → требования к естественности",
            "en": "operation → object → desired change → preserved details → naturalness requirements",
        },
        "prompt_example": (
            "На загруженной фотографии замени красную кружку на матовую белую керамическую кружку простой формы. "
            "Сохрани её размер, положение на столе, перспективу и направление ручки. "
            "Повтори существующие освещение и тень от кружки. Не изменяй руки человека, стол, фон, цветокоррекцию и кадрирование фотографии."
        ),
    },
    "ace-step": {
        "prompt_style": (
            "English music prompt. Genre, instruments, mood, vocals, structure. "
            "Structure: genre/subgenre → mood and energy → instruments and rhythm → vocals → arrangement development → production. "
            "Do not mix lyrics into caption if API has separate fields."
        ),
        "clarify": {
            "ru": ["Песня или инструментал?", "Какой жанр?", "Какое настроение?", "Вокал и язык?",
                   "Какой темп?", "Какие инструменты?", "Какая структура?", "Нужен ли текст песни?"],
            "en": ["Song or instrumental?", "What genre?", "What mood?", "Vocals and language?",
                   "What tempo?", "What instruments?", "What structure?", "Any lyrics?"],
        },
        "structure": {
            "ru": "жанр и поджанр → настроение и энергия → инструменты и ритм → вокал → развитие композиции → продакшен",
            "en": "genre and subgenre → mood and energy → instruments and rhythm → vocals → arrangement development → production",
        },
        "prompt_example": (
            "Dreamy indie pop with warm analog synthesizers, delicate electric piano, muted guitar, soft live drums and a rounded bassline. "
            "Intimate female vocals in English, gentle and breathy delivery, nostalgic but hopeful mood, medium tempo around 100 BPM. "
            "Begin with a sparse instrumental intro, gradually introduce the drums and bass, build toward a memorable melodic chorus, "
            "then finish with a soft instrumental outro. Warm analog production, subtle tape saturation, polished but organic mix."
        ),
    },
    "elevenlabs-music": {
        "prompt_style": (
            "English natural-language music concept. "
            "Structure: concept and use case → genre → key instruments → vocals → dynamics/development → mix character."
        ),
        "clarify": {
            "ru": ["Какой жанр?", "Для чего трек?", "Какая эмоция?", "Какой темп?",
                   "Какие инструменты?", "Нужен ли вокал?", "Какая длительность?", "Какая структура?",
                   "Есть ли референсное аудио?"],
            "en": ["What genre?", "What is the track for?", "What emotion?", "What tempo?",
                   "What instruments?", "Any vocals?", "What length?", "What structure?",
                   "Any reference audio?"],
        },
        "structure": {
            "ru": "концепция и применение → жанр → ключевые инструменты → вокал → динамика и развитие → характер сведения",
            "en": "concept and use → genre → key instruments → vocals → dynamics and development → mix character",
        },
        "prompt_example": (
            "Create a sophisticated instrumental electronic track for a premium fashion film. Minimal deep house at 118 BPM, "
            "with a warm analog bassline, restrained four-on-the-floor drums, shimmering synth arpeggios and airy atmospheric pads. "
            "Begin with a spacious, understated intro, gradually introduce a pulsing groove, build tension through layered textures, "
            "then resolve into an elegant, hypnotic outro. Modern, refined, slightly mysterious mood. Clean low end, wide stereo image, "
            "subtle reverb, no vocals and no abrupt transitions."
        ),
    },
    "stable-audio-2-5": {
        "prompt_style": (
            "English sound-effect language (timbre, attack, decay, reverb, acoustic space) — describe what is heard, not a visual scene. "
            "Structure: sound type → source → acoustic properties → time sequence → environment → no extra sounds."
        ),
        "clarify": {
            "ru": ["Какой звук нужен?", "Что его производит?", "Какой характер и интенсивность?",
                   "Какая длительность?", "Какое окружение?", "Какая перспектива и расстояние?",
                   "Нужен ли музыкальный фон?"],
            "en": ["What sound is needed?", "What produces it?", "Character and intensity?",
                   "What duration?", "What environment?", "Perspective and distance?",
                   "Any musical bed?"],
        },
        "structure": {
            "ru": "тип звука → источник → акустические свойства → временная последовательность → окружение → ограничения на дополнительные звуки",
            "en": "sound type → source → acoustic properties → time sequence → environment → no extra sounds",
        },
        "prompt_example": (
            "A realistic close-up sound effect of a heavy metal door slowly opening in an abandoned industrial building. "
            "Low mechanical creaking, resonant metal friction, a short deep hinge groan and a final hollow metallic clunk as the door stops. "
            "Spacious empty-room reverberation, dark cinematic atmosphere, natural acoustic detail. No music, no voices, no additional sound events."
        ),
    },
}


def main() -> None:
    data = json.loads(CARDS.read_text(encoding="utf-8"))
    models = data["models"]
    missing = [mid for mid in PROFILES if mid not in models]
    if missing:
        raise SystemExit(f"unknown model ids: {missing}")
    for mid, prof in PROFILES.items():
        models[mid].update(prof)
    data["_prompt_profile"] = (
        "clarify — уточняющие вопросы под модель; structure — порядок блоков в промпте; "
        "prompt_example — образец; prompt_style — инструкция LLM. Видео: одна сцена по умолчанию."
    )
    CARDS.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"updated {len(PROFILES)} models in {CARDS}")


if __name__ == "__main__":
    main()
