"""Полное дерево подсказок (ai-shnitsa-hint-tree-vX.Y.Z.json, с листьями) → компактный рабочий файл помощника.

    python scripts/build_hint_tree.py ai-shnitsa-hint-tree-v1.1.0.json assistant/data/hint_tree.json

Листья (реакция × контекст) в рабочий файл не кладём: помощник считает их по тем же правилам (assistant/tree.py),
а полный файл листьев (…-leaves-…jsonl) — эталон для тестов. Рабочий файл ~0,3 МБ, грузится при старте.
"""
from __future__ import annotations

import json
import re
import sys

FINISH = {
    'VID': ['Скачать', 'Проверить виральность', 'Ещё ролик в этом стиле'], 'IMG': ['Скачать', 'Апскейл', 'Сохранить стиль'],
    'STO': ['▶ Следующая серия/сцена', 'Скачать', 'На витрину'], 'COM': ['Скачать набор', 'Ещё формат', 'Для всего каталога'],
    'AUD': ['Скачать', 'Наложить на видео', 'Другой вариант'], 'D3': ['Скачать .glb', 'Видео 360°', 'На витрину'],
    'EDT': ['Скачать', 'Субтитры', 'Версия 9:16'], 'PER': ['Скачать', 'Ещё одно', 'Оживить'],
    'INT': ['Попробовать на последнем результате', 'Следующий инструмент', 'Готово'],
    'HLP': ['Попробовать', 'Ещё вопрос', 'Вернуться к задаче'], 'ADM': ['Отметить сделанным', 'Отчёт', 'Задача агенту'],
    'DSN': ['Скачать', 'Варианты для клиента', 'Сохранить стиль'],
    'MKT': ['Скачать пакет', 'Ещё вариант для теста', 'Отчёт по креативам'],
    'ART': ['Скачать в печатном качестве', 'Апскейл', 'На витрину'],
}
WHAT_WRONG = {
    'VID': ['движение', 'лицо', 'длина', 'звук', 'стиль'], 'IMG': ['стиль', 'цвет', 'композиция', 'текст', 'лицо'],
    'STO': ['герой не похож', 'сцена', 'стиль', 'сюжет'], 'COM': ['товар искажён', 'фон', 'текст', 'цвет'],
    'AUD': ['жанр', 'темп', 'голос', 'слова'], 'D3': ['форма', 'текстура', 'свет', 'ракурс'], 'EDT': ['ритм', 'цвет', 'субтитры', 'длина'],
    'PER': ['лицо', 'цвет', 'настроение', 'текст'], 'INT': ['аргументы', 'ответ сервера', 'доступ'], 'HLP': ['не то объяснил', 'другое'],
    'ADM': ['данные', 'период', 'фильтр'], 'DSN': ['стиль', 'пропорции', 'материалы', 'цвет', 'свет'],
    'MKT': ['посыл', 'тон бренда', 'формат', 'текст'], 'ART': ['техника', 'цвет', 'композиция', 'детали'],
}
# пороги для админки (раздел 29 документа)
RULES = {"atypical_share": 0.05, "atypical_min_runs": 20, "new_path_streak": 3, "cluster_dialogs": 20, "cluster_days": 7,
         "new_group_users": 30, "resume_hours": 20, "story_min_score": 3.0}


def signal_words(s: str) -> list[str]:
    s = re.sub(r"вложение-фото \+", "", s or "")
    out = []
    for w in re.split(r"[,;«»]", s):
        w = w.strip().lower()
        if w and len(w) >= 2:
            out.append(w)
    return out


def build(full: dict) -> dict:
    vectors = []
    for v in full["vectors"]:
        subs = []
        for s in v["subs"]:
            stories = []
            for o in s["stories"]:
                steps = [{"step": t["step"], "hints": t.get("shown") or []} for t in o["steps"]]
                stories.append({"id": o["id"], "title": o["title"], "professions": o.get("professions") or [],
                                "priority": o.get("priority") or "normal", "related": o.get("related") or [],
                                "status": o.get("status") or "active", "version_added": o.get("version_added"),
                                "steps": steps})
            subs.append({"id": s["id"], "title": s["title"], "examples": s.get("examples") or [], "stories": stories})
        vectors.append({"id": v["id"], "title": v["title"], "signals": signal_words(v.get("signals") or ""), "subs": subs})
    out_nodes = [{"id": o["leaf"], "group": o["group"], "request": o["request"].strip("«» "), "reaction": o["reaction"]}
                 for o in full.get("out_of_platform") or []]
    return {
        "version": full["version"], "date": full.get("date"), "levels": full.get("levels"),
        "reactions": full["reactions"], "contexts": full["contexts"],
        "finish": FINISH, "what_wrong": WHAT_WRONG, "rules": RULES,
        "vectors": vectors, "professions": full.get("professions") or [], "old_types_map": full.get("old_types_map") or {},
        "out_of_platform": out_nodes, "changelog": full.get("changelog") or [],
    }


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    data = build(json.load(open(src, encoding="utf-8")))
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    n = sum(len(s["stories"]) for v in data["vectors"] for s in v["subs"])
    print(f"{dst}: v{data['version']}, {len(data['vectors'])} векторов, {n} историй")
