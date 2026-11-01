#!/usr/bin/env python3
"""Эталонный набор фраз помощника: как понимал раньше (только router.py) и как понимает сейчас (understand.py + режимы).

    python scripts/assistant_eval.py            # таблица и итог
    python scripts/assistant_eval.py --fails    # только ошибки

Набор — GOLDEN в tests/assistant/test_assist_understand.py. Пополняйте его фразами из метрик
(/admin/metrics → assist_reply с intent ask_type / off_topic — это «помощник не понял»).
Прогон без нейросети: проверяет правила. Нейросеть (слой 2) только добавляет понимания сверху.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "assistant"))

from assistant.cards import load_cards  # noqa: E402
from assistant.engine import Assistant, AssistantDeps  # noqa: E402
from assistant.router import route  # noqa: E402
from assistant.session import MemoryStore  # noqa: E402
from test_assist_understand import GOLDEN, category  # noqa: E402

OLD = {"generate_task": "generate_task", "off_topic": "off_topic", "error_help": "error_help", "ui_help": "question",
       "compare": "question"}


def main() -> int:
    only_fails = "--fails" in sys.argv
    cards, nb = load_cards()
    titles = {c.id: c.title for c in cards.values()}
    a = Assistant(AssistantDeps(cards=cards, neighbors=nb, store=MemoryStore(), brief=False))
    old_ok = new_ok = 0
    rows = []
    for i, (phrase, want) in enumerate(GOLDEN):
        old_raw = route(phrase, {}, {}, titles).name
        old = OLD.get(old_raw, f"{old_raw} (меню)" if old_raw in ("ask_type",) else old_raw)
        new = category(a.handle(phrase, {}, f"eval:{i}"))
        old_ok += old == want
        new_ok += new == want
        if not only_fails or new != want:
            rows.append((phrase, want, old, new))
    w = max(len(r[0]) for r in rows) if rows else 10
    print(f"{'фраза':<{w}}  {'нужно':<14} {'было':<18} стало")
    for p, want, old, new in rows:
        print(f"{p:<{w}}  {want:<14} {('✓ ' if old == want else '✗ ') + old:<18} {('✓ ' if new == want else '✗ ') + new}")
    n = len(GOLDEN)
    print(f"\nПонято верно: было {old_ok}/{n} ({old_ok * 100 // n}%), стало {new_ok}/{n} ({new_ok * 100 // n}%)")
    return 0 if new_ok == n else 1


if __name__ == "__main__":
    raise SystemExit(main())
