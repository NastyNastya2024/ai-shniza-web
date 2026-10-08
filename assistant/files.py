"""Прикреплённые файлы (скрепка) глазами ассистента: имена, роли, что модель возьмёт.

Фронт кладёт в context.attachments готовые файлы: [{"kind": "image"|"audio"|"video", "name": "cat.png"}].
Ассистент называет их по имени:
  • при подборе моделей — «Вижу фото «cat.png» — показываю модели, которые умеют работать с фото»;
  • в сводке перед запуском — «Фото «cat.png» — первый кадр видео»;
  • если модель файл не возьмёт — «Аудио «voice.wav» Seedream не примет — уйдёт только текст».
Сами файлы ассистенту не нужны: номера upl_… фронт отдаёт прямо в /api/generate.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

KINDS = ("image", "audio", "video")
MAX_FILES = 12
MAX_NAME = 60

KIND_WORD = {
    "ru": {"image": "фото", "audio": "аудио", "video": "видео"},
    "en": {"image": "photo", "audio": "audio", "video": "video"},
}

# Роль файла в генерации: (тип файла, тип модели) → подпись
ROLE = {
    "ru": {
        ("image", "video"): "первый кадр видео",
        ("image", "image"): "референс для картинки",
        ("image", "edit"): "фото для правки",
        ("audio", "video"): "звук для видео",
        ("video", "video"): "исходное видео",
    },
    "en": {
        ("image", "video"): "first frame of the video",
        ("image", "image"): "reference for the image",
        ("image", "edit"): "photo to edit",
        ("audio", "video"): "soundtrack for the video",
        ("video", "video"): "source video",
    },
}

T = {
    "seen_photo": {
        "ru": "Вижу {files} — показываю модели, которые умеют работать с фото.",
        "en": "I see {files} — showing models that can work with a photo.",
    },
    "seen": {"ru": "Вижу {files}.", "en": "I see {files}."},
    "all_take": {"ru": "{Kind} «{name}» примут все эти модели.", "en": "All of these models can use the {kind} “{name}”."},
    "only_take": {"ru": "{Kind} «{name}» из них примет только {models}.", "en": "Only {models} can use the {kind} “{name}”."},
    "none_take": {
        "ru": "{Kind} «{name}» эти модели не примут — уйдёт только текст.",
        "en": "None of these models can use the {kind} “{name}” — only the text will be sent.",
    },
    "used": {"ru": "{Kind} «{name}» — {role}.", "en": "{Kind} “{name}” — {role}."},
    "unused": {
        "ru": "{Kind} «{name}» {model} не примет — в генерацию уйдёт только текст.",
        "en": "{model} can't use the {kind} “{name}” — only the text will be sent.",
    },
    "summary": {"ru": "Файлы", "en": "Files"},
}


def _clean_name(name: Any) -> str:
    s = str(name or "").strip()
    s = re.sub(r"[\x00-\x1f\x7f<>\"«»“”\\]", "", s)
    s = s.rsplit("/", 1)[-1]
    if len(s) > MAX_NAME:
        stem, dot, ext = s.rpartition(".")
        s = (stem[: MAX_NAME - len(ext) - 2] + "…." + ext) if dot and len(ext) <= 6 else s[: MAX_NAME - 1] + "…"
    return s or "файл"


def clean_attachments(raw: Any) -> list[dict[str, str]]:
    """Список с фронта → до MAX_FILES файлов (можно несколько одного типа), безопасные имена."""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for item in raw[: MAX_FILES * 2]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        if kind not in KINDS:
            continue
        out.append({"kind": kind, "name": _clean_name(item.get("name"))})
        if len(out) >= MAX_FILES:
            break
    return out


def accepts(card: Any, kind: str, inputs_fn: Optional[Callable[[str], list]] = None) -> bool:
    """Возьмёт ли модель файл этого типа. Сначала — inputs из INTEGRATED_MODELS, иначе — режимы карточки."""
    if inputs_fn is not None:
        try:
            ins = inputs_fn(card.id)
        except Exception:  # noqa: BLE001
            ins = None
        if ins:
            return kind in ins
    if kind == "image":
        return any(m in {"i2v", "i2i"} for m in (card.modes or []))
    return False


def describe(files: list[dict[str, str]], lang: str) -> str:
    """«фото «cat.png» и аудио «voice.wav»»"""
    words = KIND_WORD.get(lang) or KIND_WORD["ru"]
    q = ("«", "»") if lang != "en" else ("“", "”")
    parts = [f"{words[f['kind']]} {q[0]}{f['name']}{q[1]}" for f in files]
    if len(parts) <= 1:
        return "".join(parts)
    joiner = " и " if lang != "en" else " and "
    return ", ".join(parts[:-1]) + joiner + parts[-1]


def plan(card: Any, files: list[dict[str, str]], lang: str,
         inputs_fn: Optional[Callable[[str], list]] = None) -> list[dict[str, Any]]:
    """Что произойдёт с каждым файлом при генерации на этой модели."""
    words = KIND_WORD.get(lang) or KIND_WORD["ru"]
    roles = ROLE.get(lang) or ROLE["ru"]
    out = []
    for f in files:
        used = accepts(card, f["kind"], inputs_fn)
        role = roles.get((f["kind"], card.kind)) or ("используется в генерации" if lang != "en" else "used in generation")
        out.append({"kind": f["kind"], "name": f["name"], "used": used, "role": role if used else "",
                    "kind_label": words[f["kind"]]})
    return out


def lines(card: Any, items: list[dict[str, Any]], lang: str) -> list[str]:
    """Строки ответа: какой файл чем станет; какой модель не возьмёт."""
    L = "en" if lang == "en" else "ru"
    out = []
    for it in items:
        kw = {"kind": it["kind_label"], "Kind": it["kind_label"].capitalize(), "name": it["name"], "model": card.title,
              "role": it["role"]}
        out.append(T["used" if it["used"] else "unused"][L].format(**kw))
    return out


def summary_labels(items: list[dict[str, Any]], lang: str) -> list[str]:
    """Для блока summary: «фото «cat.png» — первый кадр видео»; неиспользуемые — с пометкой."""
    q = ("«", "»") if lang != "en" else ("“", "”")
    out = []
    for it in items:
        base = f"{it['kind_label']} {q[0]}{it['name']}{q[1]}"
        out.append(f"{base} — {it['role']}" if it["used"] else base + (" — не используется" if lang != "en" else " — not used"))
    return out


def seen_lines(files: list[dict[str, str]], cards: list, lang: str,
               inputs_fn: Optional[Callable[[str], list]] = None) -> list[str]:
    """Над карточками моделей: «Вижу фото «cat.png» — …», и кто из показанных возьмёт аудио/видео."""
    L = "en" if lang == "en" else "ru"
    words = KIND_WORD[L]
    has_photo = any(f["kind"] == "image" for f in files)
    out = [T["seen_photo" if has_photo else "seen"][L].format(files=describe(files, lang))]
    for f in files:
        if f["kind"] == "image" or not cards:
            continue
        take = [c.title for c in cards if accepts(c, f["kind"], inputs_fn)]
        kw = {"kind": words[f["kind"]], "Kind": words[f["kind"]].capitalize(), "name": f["name"],
              "models": (" и " if L == "ru" else " and ").join(take)}
        key = "all_take" if len(take) == len(cards) else ("only_take" if take else "none_take")
        out.append(T[key][L].format(**kw))
    return out


def summary_title(lang: str) -> str:
    return T["summary"]["en" if lang == "en" else "ru"]
