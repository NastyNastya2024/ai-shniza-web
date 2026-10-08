"""Определение языка текста (ru | en).

В студии язык ответа ассистента задаёт интерфейс (ctx.lang); detect_lang —
запасной путь, когда UI-язык не передан.
"""
from __future__ import annotations

import re

_CYR = re.compile(r"[а-яё]", re.I)
_LAT = re.compile(r"[a-z]", re.I)


def detect_lang(text: str, default: str = "ru") -> str:
    t = text or ""
    cyr, lat = len(_CYR.findall(t)), len(_LAT.findall(t))
    if cyr == 0 and lat == 0:
        return default
    # названия моделей латиницей в русской фразе не делают её английской
    return "ru" if cyr >= max(3, lat // 3) else ("en" if lat else default)
