"""Маршрутизатор намерений — без LLM (0 токенов).

Порядок проверок важен: безопасность и подмена инструкций — раньше всего остального.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

I = re.IGNORECASE


def _rx(*parts: str) -> re.Pattern:
    return re.compile("|".join(parts), I)


# --- безопасность ---
CRISIS = _rx(r"поконч\w* с собой", r"не хочу жить", r"убить себя", r"суицид", r"самоуб",
             r"kill myself", r"suicid", r"end my life", r"self[- ]?harm")
MINORS_SEXUAL = re.compile(
    r"(?=.*(ребен|ребён|детск|школьниц|школьник|подрост|несовершеннолет|\bchild|\bkid|minor|teen|underage|loli))"
    r"(?=.*(обнаж|голы|голая|секс|эрот|порн|nude|naked|sex|erotic|porn|nsfw))", I | re.S)
VIOLENCE = _rx(r"как (сделать|собрать|изготовить) (бомбу|взрывчатк|оружие)", r"взрывчатк",
               r"how to (make|build) (a )?(bomb|explosive|weapon)", r"терракт|теракт", r"terror attack",
               r"расчленен|расчленён|dismember", r"\bгор(е|ю) крови\b", r"\bgore\b")
EXTREMISM = _rx(r"свастик", r"нацистск\w* пропаганд", r"\bigil\b|\bisis\b", r"вербовк\w* в")
NSFW = _rx(r"\bпорн", r"\bporn", r"\bnsfw\b", r"\bнюдс", r"\bnudes?\b", r"раздень", r"undress", r"обнажённ|обнаженн|\bnaked\b|\bnude\b")
REAL_PERSON = _rx(r"дипфейк", r"deep ?fake", r"(лицо|фото|голос) (известн|знаменит|политик|президент|актёр|актер|певиц|блогер)",
                  r"(face|voice) of (a )?(celebrity|politician|president|famous)", r"сделай .* (путин|трамп|маск|байден)",
                  r"(putin|trump|elon musk|biden|taylor swift)")

# --- подмена инструкций ---
INJECTION = _rx(r"игнорир\w* (все |всё |эти |свои )?(предыдущ|прошл|системн|инструкц|правил)",
                r"забудь (все |всё )?(инструкц|правил)", r"ignore (all |any |the |your )?(previous |prior |above |system )?(instruction|rule|prompt)",
                r"(покажи|выведи|напиши|раскрой) (свой |твой |системн\w* )+(промпт|инструкц)", r"system prompt",
                r"\bты теперь\b", r"\byou are now\b", r"developer mode", r"режим разработчика", r"\bjailbreak\b", r"\bDAN\b")

# --- типы задач ---
TYPE_RULES: list[tuple[str, re.Pattern]] = [
    ("sfx", _rx(r"звуков\w* эффект", r"\bsfx\b", r"\bшум(ы)?\b", r"эмбиент", r"\bлуп\w*", r"звук (дожд|ветр|шаг|моря|город|огня|прибо)",
                r"sound effect", r"ambien", r"\bloop\b")),
    ("music", _rx(r"музык", r"музон", r"\bтрек", r"песенк", r"\bпесн", r"\bбит\b", r"мелоди", r"саундтрек", r"джингл", r"вокал", r"\bспой",
                  r"\bmusic\b", r"\btrack\b", r"\bsong\b", r"\bbeat\b", r"melod", r"jingle", r"soundtrack")),
    ("video", _rx(r"видео", r"видос", r"видяшк", r"\bролик", r"мульт", r"\bгифк", r"\bgif\b", r"\bклип", r"анимац", r"анимир", r"оживи", r"оживить", r"в движени", r"трейлер", r"\breels?\b", r"рилс",
                  r"шортс", r"сторис", r"tiktok", r"тикток", r"\bvideo\b", r"\banimat", r"\bmotion\b", r"\bclip\b", r"bring .* to life")),
    ("image", _rx(r"картин", r"картинк", r"пикч", r"\bфотк", r"изображ", r"\bмем\b", r"\bобои\b", r"wallpaper", r"постер", r"плакат", r"\bфото\b", r"\bарт\b", r"логотип", r"\bлого\b", r"баннер", r"обложк",
                  r"иллюстрац", r"аватар", r"\bпринт", r"открытк", r"рисун", r"нарисуй", r"\bиконк", r"стикер", r"\bimage\b", r"\bpicture\b",
                  r"\bposter\b", r"\blogo\b", r"\bbanner\b", r"illustrat", r"\bavatar\b", r"\bdraw\b", r"\bicon\b", r"\bsticker\b")),
    # после image: «текст на картинке» уже поймает image; иначе — текстовая генерация
    ("text", _rx(r"\bтекст\b", r"стать[яюе]", r"\bпост\b", r"письм[оае]", r"\bстих", r"эссе", r"реферат", r"сценари", r"рассказ",
                 r"копирайт", r"сочинен", r"напиши (код|программ|скрипт|функци|эссе|сочинен|реферат|письмо|пост|стать|стих)",
                 r"\bwrite (code|a program|a script|an essay|a letter|a poem|a post|an article|a story)\b",
                 r"\bessay\b", r"\bpoem\b", r"\barticle\b", r"\bletter\b", r"\bllm\b", r"языков\w* модел",
                 r"\bпереведи\b", r"\bперевод\b", r"\btranslate\b")),
]
EDIT_RX = _rx(r"замени", r"\bубери\b", r"удали\b", r"поменяй", r"\bдобавь\b", r"перекрась", r"отредактир", r"смени фон", r"другой фон",
              r"ретуш", r"сохрани лицо", r"объедини", r"совмести", r"\breplace\b", r"\bremove\b", r"change the background", r"\bretouch\b",
              r"\bedit\b", r"keep the face", r"\bmerge\b")

NEED_RULES: list[tuple[re.Pattern, list[str]]] = [
    (_rx(r"\bзвук", r"\bречь", r"диалог", r"говорит", r"озвуч", r"\bsound\b", r"speech", r"dialog", r"voice"), ["звук", "речь"]),
    (_rx(r"логотип", r"\bлого\b", r"\blogo\b"), ["логотип", "типографика"]),
    (_rx(r"надпис", r"\bтекст\b", r"слоган", r"шрифт", r"\btext\b", r"lettering", r"typograph", r"slogan"), ["текст на картинке"]),
    (_rx(r"\b4k\b", r"\b4к\b", r"высок\w* качеств", r"печат", r"\bprint\b", r"high quality"), ["4k", "детали"]),
    (_rx(r"деш[её]в", r"дёшев", r"бюджет", r"бесплатн", r"недорог", r"\bcheap", r"\bfree\b", r"budget", r"low cost"), ["дешево"]),
    (_rx(r"реклам", r"\bпромо", r"продаж", r"\bads?\b", r"advert", r"promo", r"commercial"), ["реклама", "коммерция"]),
    (_rx(r"оживи", r"оживить", r"анимируй", r"bring .* to life", r"animate (this|my) (photo|image|picture)"), ["оживить фото"]),
    (_rx(r"персонаж", r"герой", r"героин", r"character"), ["персонаж"]),
    (_rx(r"инфограф", r"\bсхем", r"\bмакет", r"infograph", r"mockup", r"layout"), ["инфографика", "макет"]),
    (_rx(r"вокал", r"\bпесн", r"\bспой", r"vocal", r"\bsong\b", r"\bsing\b"), ["вокал"]),
    (_rx(r"инструментал", r"без вокал", r"без слов", r"instrumental", r"no vocals"), ["инструментал"]),
    (_rx(r"реалист", r"как в жизни", r"realistic", r"photoreal"), ["реализм"]),
    (_rx(r"\bкино", r"кинемат", r"фильм", r"cinema", r"cinematic", r"\bfilm\b"), ["кино"]),
    (_rx(r"быстр", r"черновик", r"набросок", r"\bfast\b", r"quick", r"draft"), ["быстро", "черновик"]),
    (_rx(r"динамич", r"экшен", r"погон", r"драк", r"\bспорт", r"action", r"dynamic", r"chase"), ["динамика", "экшен"]),
    (_rx(r"длинн", r"\b(15|20|30) ?(с|сек|секунд|s|sec)", r"\blong\b"), ["длинное"]),
    (_rx(r"плавн", r"smooth"), ["плавность"]),
    (_rx(r"фон\w* музык", r"background music", r"\bфон\b"), ["фон"]),
]

# --- справка UI ---
UI_TOPICS: list[tuple[str, re.Pattern]] = [
    ("topup", _rx(r"пополн", r"баланс", r"оплат", r"\bденьг", r"top ?up", r"balance", r"\bpay")),
    ("publish", _rx(r"опубликов", r"публикац", r"выложи\w* на витрин", r"\bpublish")),
    ("vitrina", _rx(r"витрин", r"showcase", r"gallery", r"галере")),
    ("download", _rx(r"скача", r"сохранить (видео|картинк|результат|файл)", r"download", r"save (the )?(video|image|result)")),
    ("history", _rx(r"истори", r"мои (работы|генерац)", r"где (мои|мой) (работ|результат|генерац)", r"history", r"my (works|generations)")),
    ("login", _rx(r"\bвойти\b", r"\bвход\b", r"авториз", r"регистрац", r"\blog ?in\b", r"sign ?in", r"sign ?up", r"\bgoogle\b")),
    ("attach", _rx(r"(как|куда) (прикреп|загруз|добав)\w* (фото|картинк|файл|аудио)", r"attach", r"upload")),
    ("models", _rx(r"где (модели|выбрать модель)", r"не вижу модел", r"(как|где) выбрать модель", r"список моделей", r"where .*models", r"choose (a )?model")),
    ("profile", _rx(r"профил", r"как видят другие", r"\bprofile\b")),
    ("mobile", _rx(r"(на|с) телефон", r"мобильн", r"на мобиле", r"\bmobile\b", r"on (my )?phone")),
]
UI_QUESTION = _rx(r"\bгде\b", r"\bкак\b", r"\bкуда\b", r"не вижу", r"не могу найти", r"не получается", r"\bwhere\b", r"\bhow\b", r"can't find", r"cannot find")

# --- ошибки / задержки ---
ERROR_WORDS = _rx(r"ошибк", r"не работа", r"не грузит", r"не загруж", r"завис", r"\bдолго\b", r"сломал", r"не генерир", r"не пришл", r"висит",
                  r"\berror\b", r"not working", r"stuck", r"\bslow\b", r"takes (so )?long", r"failed", r"broken", r"why .* (wait|long)")

PRICE = _rx(r"сколько стоит", r"\bцен[аыу]\b", r"стоимост", r"по цене", r"дешевле", r"самая деш[её]в", r"бесплатн\w* модел", r"how much", r"\bprice", r"\bcost", r"cheapest")
COMPARE = _rx(r"\bсравни", r"\bчем\b.*\bлучше\b", r"\bчем\b.*\bотлича", r"\bvs\.?\b", r"\bили\b", r"\bcompare", r"difference between", r"\bversus\b", r"which is better")
GREETING = _rx(r"^\s*(привет|здравствуй\w*|добрый (день|вечер|утро)|хай|hi|hello|hey)\b")
THANKS = _rx(r"^\s*(спасибо|благодар\w*|thanks?|thank you|thx)\b")
WHO = _rx(r"\bкто ты\b", r"\bты кто\b", r"что ты умеешь", r"who are you", r"what can you do")

OFF_TOPIC = _rx(
    r"реши (задач|уравнен|пример)", r"\bуравнени", r"интеграл", r"\bматемат", r"домашк",
    r"погод", r"новост", r"курс (доллар|валют|евро|биткоин)", r"\bрецепт", r"анекдот", r"шутк", r"гороскоп", r"\bкто (такой|такая|был)\b",
    r"столиц", r"\bsolve\b", r"\bequation\b", r"homework",
    r"weather", r"\bnews\b", r"\brecipe\b", r"\bjoke\b", r"horoscope", r"stock price", r"\bcapital of\b",
)

REFINE = _rx(r"^(сделай|сделайте|чуть|немного|ещё|еще|добавь|убери|поменяй|замени|без|больше|меньше|теплее|холоднее|ярче|темнее|светлее|"
             r"make it|more|less|add|remove|without|warmer|colder|brighter|darker)\b",
             r"улучши (промпт|текст)", r"перепиши промпт", r"доработай промпт", r"improve (the |my )?prompt", r"rewrite (the |my )?prompt")
GENERATE_NOW = _rx(r"^(сгенерируй|генерируй|запусти|запускай|давай генерир|поехали|го\b|generate|run it|go ahead|start)")


@dataclass
class Intent:
    name: str
    kind: str | None = None
    needs: list[str] = field(default_factory=list)
    topic: str = ""
    data: dict[str, Any] = field(default_factory=dict)


KIND_WORDS: dict[str, list[str]] = {
    "image": ["картинку", "картинка", "картинки", "картинок", "изображение", "рисунок", "логотип", "постер", "фотографию",
              "иллюстрацию", "image", "picture"],
    "video": ["видео", "видеоролик", "ролик", "анимацию", "мультик", "video", "клип"],
    "music": ["музыку", "музыка", "мелодию", "песню", "песня", "трек", "music", "song"],
    "text": ["текст", "текста", "текстом", "статью", "статья", "пост", "письмо", "стих", "эссе", "text", "essay", "poem"],
    "sfx": ["звуковой", "эффект", "звук"],
}


def lev(a: str, b: str, cap: int = 3) -> int:
    """Расстояние Левенштейна с ранним выходом (для опечаток «карттинку», «видоео»)."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def squeeze(text: str) -> str:
    """Нормализация опечаток: ё→е, удвоенные буквы → одна («карттинку» → «картинку»)."""
    t = (text or "").lower().replace("ё", "е")
    return re.sub(r"([а-яa-z])\1+", r"\1", t)


def fuzzy_kind(text: str) -> str | None:
    words = re.findall(r"[а-яёa-z]+", (text or "").lower())
    best: tuple[int, str] | None = None
    for w in words:
        w2 = squeeze(w)
        if len(w2) < 4:
            continue
        for kind, vocab in KIND_WORDS.items():
            for v in vocab:
                d = lev(w2, squeeze(v), 2)
                limit = 1 if len(v) < 7 else 2
                if d <= limit and w2[:2] == squeeze(v)[:2] and (best is None or d < best[0]):
                    best = (d, kind)
    return best[1] if best else None


def detect_kind(text: str, has_image: bool) -> str | None:
    k = _detect_kind(text, has_image)
    if k:
        return k
    sq = squeeze(text)
    if sq != (text or "").lower():
        k = _detect_kind(sq, has_image)
        if k:
            return k
    return fuzzy_kind(text)


def _detect_kind(text: str, has_image: bool) -> str | None:
    if has_image and EDIT_RX.search(text):
        return "edit"
    for k, rx in TYPE_RULES:
        if rx.search(text):
            if k == "image" and has_image and EDIT_RX.search(text):
                return "edit"
            return k
    if has_image:
        return "edit" if EDIT_RX.search(text) else None
    return None


def detect_needs(text: str) -> list[str]:
    out: list[str] = []
    for rx, needs in NEED_RULES:
        if rx.search(text):
            out += [n for n in needs if n not in out]
    return out


_STOP = re.compile(
    r"^(сделай|сделайте|сделать|создай|создайте|нужно|нужен|нужна|хочу|пожалуйста|мне|для|про|как|чтобы|видео|картинку|картинка|ролик|"
    r"музыку|трек|фото|изображение|с|в|на|и|из|по|очень|красивый|красивую|красивое|секунд|сек|make|create|a|an|the|of|for|with|in|on|"
    r"надо|нужно|сделать|сделай|давай|который|которая|которое|которые|котором|это|эту|этот|эта|где|чтоб|чтобы|можно|"
    r"картинку|картинка|картинки|видос|видосик|музыку|песню|ролик|звуком|звука|вертикально|горизонтально|"
    r"please|video|image|picture|music|track|i|want|need|my)$", I)
_STOP_PREFIX = re.compile(r"^(вертикальн|горизонтальн|квадратн|реклам|секунд|минут|качеств|формат|бесплатн|деш[её]в|быстр|коротк|длинн|высок|"
                          r"vertical|horizontal|square|second|minute|free|cheap|quick|short|long)", I)


def topic_of(text: str, max_words: int = 3) -> str:
    words = re.sub(r"[^\w\s-]", " ", (text or "").lower()).split()
    keep = [w for w in words if len(w) > 2 and not _STOP.match(w) and not _STOP_PREFIX.match(w) and not w[0].isdigit()]
    return " ".join(keep[:max_words])


def route(text: str, context: dict[str, Any] | None = None, session: dict[str, Any] | None = None,
          model_titles: dict[str, str] | None = None) -> Intent:
    """text — последнее сообщение пользователя; context — состояние UI; session — память диалога."""
    ctx = context or {}
    ses = session or {}
    t = (text or "").strip()
    has_image = bool(ctx.get("has_image"))

    if CRISIS.search(t):
        return Intent("crisis")
    if MINORS_SEXUAL.search(t) or VIOLENCE.search(t) or EXTREMISM.search(t) or NSFW.search(t):
        return Intent("safety")
    if REAL_PERSON.search(t):
        return Intent("safety_person")
    if INJECTION.search(t):
        return Intent("injection")

    # ошибки и задержки: явный контекст ошибки от UI или жалоба
    if ctx.get("last_error") or (ctx.get("job_status") in {"queued", "dispatched", "running", "requeued"} and ERROR_WORDS.search(t)):
        if not t or ERROR_WORDS.search(t) or len(t.split()) <= 6:
            return Intent("error_help")
    if ERROR_WORDS.search(t) and not detect_kind(t, has_image):
        return Intent("error_help")

    if not t:
        return Intent("smalltalk", data={"kind": "hello"})

    # подсказки по интерфейсу: вопрос «где/как» + тема UI, без описания задачи
    for topic, rx in UI_TOPICS:
        if rx.search(t) and (UI_QUESTION.search(t) or len(t.split()) <= 4) and not (topic == "attach" and detect_kind(t, False) and not UI_QUESTION.search(t)):
            return Intent("ui_help", data={"topic": topic})

    # запуск генерации выбранной моделью
    if GENERATE_NOW.search(t) and (ctx.get("selected_model_id") or ses.get("picked")):
        return Intent("generate_now")

    # правка уже готового промпта
    if ses.get("prompt") and REFINE.search(t) and not (len(t.split()) > 12 and detect_kind(t, has_image)):
        return Intent("prompt_improve", data={"change": t})
    if re.search(r"улучши|перепиши|доработай|improve|rewrite", t, I) and ctx.get("selected_model_id"):
        return Intent("prompt_improve", data={"change": "", "text": t})

    # сравнение моделей по названиям
    titles = model_titles or {}
    tl = t.lower()
    hits = {mid: title.lower() for mid, title in titles.items() if title.lower() in tl}
    # «Veo 3.1 Fast» не должен засчитываться ещё и как «Veo 3.1»
    mentioned = [mid for mid, tt in hits.items() if not any(tt != o and tt in o for o in hits.values())]
    if len(mentioned) >= 2 and COMPARE.search(t):
        return Intent("compare", data={"models": mentioned[:3]})

    kind = detect_kind(t, has_image)
    needs = detect_needs(t)

    if PRICE.search(t) and not kind:
        return Intent("price", needs=needs)

    if OFF_TOPIC.search(t) and not kind:
        return Intent("off_topic")

    short = len(t.split()) <= 4
    if GREETING.search(t) and short and not kind:
        return Intent("smalltalk", data={"kind": "hello"})
    if THANKS.search(t) and short and not kind:
        return Intent("smalltalk", data={"kind": "thanks"})
    if WHO.search(t) and not kind:
        return Intent("smalltalk", data={"kind": "who"})

    if kind:
        return Intent("generate_task", kind=kind, needs=needs, topic=topic_of(t))
    # описание без типа («котик в космосе») — спросим тип кнопками, без LLM
    if len(t.split()) >= 2 and re.search(r"[a-zа-яё]{3,}", t, I):
        return Intent("ask_type", needs=needs, topic=topic_of(t))
    return Intent("off_topic")
