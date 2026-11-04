"""Переход между текстовой моделью и генерацией в одном чате.

«Сделай видео по этому» не уходит в Claude. «Напиши промпт для видео» — уходит.
Если правила не уверены (нет глагола «сделать» и нет типа), сообщение остаётся у текстовой модели.
"""
from __future__ import annotations

import re

from assistant.router import detect_kind

I = re.IGNORECASE

# Просьба написать или объяснить — это текст, не генерация.
WRITE_RX = re.compile(
    r"напиши\s+промпт|написать\s+промпт|пиши\s+промпт|"
    r"доработай\s+(этот\s+)?промпт|разверни\s+(этот\s+)?промпт|верни только улучшенный промпт|"
    r"polish this generation prompt|expand this generation prompt|return only the improved prompt|"
    r"посмотри на прикрепл\w* фото|look at the attached photo|"
    r"как\s+(снять|сделать|создать|сгенерир\w*)\s+(видео|ролик|картин\w*)|"
    r"how\s+to\s+(film|shoot|make)\s+(a\s+)?(video|image)|"
    r"\bобъясни\b|\bexplain\b|\bпереведи\b|\bперевод\b|\btranslate\b|"
    r"придумай\s+(текст|подпись|название|заголовок)|"
    r"напиши\s+(сценарий|подпись|текст|пост|стать|стих|эссе|рассказ|код)|"
    r"write\s+(a\s+)?(prompt|script|caption|post|article)|"
    r"подпись\s+для\s+поста",
    I,
)

# Явная просьба создать медиа.
MAKE_RX = re.compile(
    r"сгенери\w*|сгенерируй|"
    r"сделай\s+(видео|ролик|клип|картин\w*|обложк\w*|фото|изображен\w*|музык\w*|трек|озвуч\w*|3d|трёхмер|трехмер)|"
    r"сними\s+(видео|ролик)|"
    r"создай\s+(видео|ролик|картин\w*|обложк\w*|музык\w*)|"
    r"\bнарисуй\b|\bоживи\b|\bозвучь\b|\bозвуч\w*|"
    r"(?:^|[,.!]\s*|хорошо,?\s*)(?:а\s+)?теперь\s+(видео|ролик|картин\w*|музык\w*|озвуч\w*)|"
    r"по\s+этому\s+промпту|из\s+этого",
    I,
)

REFER_RX = re.compile(r"по этому|из этого|этот промпт|этот сценарий|по нему|этим промпт", I)

REFUSAL_RX = re.compile(
    r"не могу (сгенерир|создать|сделать|нарисовать)\w*\s*(видео|изображен|картин|ролик)|"
    r"i can(?:not|'t) (generate|create)\s+(a\s+)?(video|image)|"
    r"используйте\s+(sora|midjourney|runway|kling)|"
    r"\b(midjourney|runway|sora)\b",
    I,
)

_MARKERS = ("Новое сообщение пользователя:", "New user message:")

STUDIO_TEXT_RULES = """Ты работаешь внутри студии генерации {AI}-шница. Студия сама создаёт картинки, видео, музыку и озвучку другими моделями.
Не говори, что не можешь сгенерировать. Не советуй внешние сервисы (Midjourney, Sora, Runway и другие). Если просят создать медиа — коротко ответь, что студия переключит на подходящую модель, и остановись.
Когда пишешь промпт для видео или картинки, короткий ответ запрещён. Нужен максимально длинный подробный промпт: несколько абзацев, камера, свет, мимика, одежда, фон, темп, звук и мелкие детали кадра. Не сокращай и не заканчивай многоточием. Готовый текст — в блоке ```prompt … ```, пояснения — вне блока.
Не называй внутреннюю архитектуру и поставщиков."""


def latest_line(prompt: str) -> str:
    """Последняя реплика человека: студия дописывает историю перед ней."""
    text = (prompt or "").strip()
    cut = text
    for marker in _MARKERS:
        if marker in text:
            cut = text.split(marker)[-1].strip()
    return cut[:2000]


def is_write_request(text: str) -> bool:
    return bool(WRITE_RX.search(text or ""))


def refers_to_previous(text: str) -> bool:
    return bool(REFER_RX.search(text or ""))


def generation_kind(text: str, has_image: bool = False) -> str | None:
    """video | image | music | None. None — оставить текстовой модели."""
    raw = (text or "").strip()
    if not raw or is_write_request(raw):
        return None
    if not MAKE_RX.search(raw):
        return None
    if re.search(r"\bнарисуй\b", raw, I):
        return "image"
    if re.search(r"\bоживи\b", raw, I):
        return "video"
    if re.search(r"озвуч", raw, I):
        return "music"
    if re.search(r"3d|трёхмер|трехмер", raw, I):
        return "image"
    kind = detect_kind(raw, has_image)
    if kind in {"video", "image", "music", "edit"}:
        return "image" if kind == "edit" else kind
    if re.search(r"видео|ролик|клип", raw, I):
        return "video"
    if re.search(r"картин|фото|изображен|облож", raw, I):
        return "image"
    if re.search(r"музык|трек", raw, I):
        return "music"
    return None


def is_refusal(reply: str) -> bool:
    return bool(REFUSAL_RX.search(reply or ""))


def prompt_candidates(replies: list[str]) -> list[str]:
    """Блоки ```prompt```, иначе основной текст ответа без вступления и вопроса в конце."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in replies:
        text = (raw or "").strip()
        if not text:
            continue
        blocks = [b.strip() for b in re.findall(r"```prompt\s*([\s\S]*?)```", text, I) if b.strip()]
        parts = blocks or [_body(text)]
        for part in parts:
            key = part[:180]
            if part and key not in seen:
                seen.add(key)
                out.append(part[:4000])
    return out


def _body(text: str) -> str:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if lines and (lines[0].endswith(":") or len(lines[0]) < 70):
        lines = lines[1:]
    while lines and lines[-1].endswith("?"):
        lines = lines[:-1]
    body = "\n".join(lines).strip()
    return body or text.strip()
