"""Проверка LLM ассистента вживую — почему промпты «по шаблону» и какого они качества.

    python -m assistant.selfcheck                              # идея по умолчанию, модель seedance-2-5
    python -m assistant.selfcheck "видео с закатом" veo-3-1

Печатает: какие провайдеры настроены, ответ каждого (время, токены, ошибка), вопросы брифа и 3 варианта промпта.
Ключи не печатает. Запускать на сервере из корня репозитория (подхватит .env).
"""
from __future__ import annotations

import json
import os
import sys
import time


def _load_env() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        sys.path.insert(0, root)
        from auth import load_env  # type: ignore

        load_env(root)
    except Exception:
        pass


def main(argv: list[str]) -> int:
    _load_env()
    from . import brief as BR
    from .cards import load_cards
    from .flask_adapter import providers_from_env
    from .llm import LLMChain, LLMUnavailable
    from .prompts import SYSTEM, build_user, validate_output

    idea = argv[1] if len(argv) > 1 else "видео с закатом"
    mid = argv[2] if len(argv) > 2 else "seedance-2-5"
    cards, _ = load_cards()
    card = cards.get(mid) or next(iter(cards.values()))
    provs = providers_from_env()
    print("== Провайдеры (по порядку ASSIST_LLM_ORDER) ==")
    for p in provs:
        print(f"  {p.name:10} model={p.model or '—':32} key={'есть' if p.api_key else 'НЕТ'}  url={p.url}  timeout={p.timeout}s")
    ok = 0
    for p in provs:
        if not (p.api_key and p.model):
            print(f"\n-- {p.name}: пропущен (нет ключа или модели)")
            continue
        chain = LLMChain([p], deadline_sec=float(os.getenv("ASSIST_LLM_DEADLINE_SEC") or 25))
        print(f"\n-- {p.name} / {p.model}")
        for task, system, user, validate, mt, scale in (
            ("brief", BR.BRIEF_SYSTEM, BR.brief_user(card, idea, "ru"), BR.validate_brief, 450, 1.5),
            ("variants", BR.VARIANTS_SYSTEM, BR.variants_user(card, idea, {}, [], {}, "ru"), BR.validate_variants, 1000, 2.5),
            ("one_prompt", SYSTEM, build_user(card, idea, {}, "ru"), validate_output, 300, 1.5),
        ):
            t0 = time.monotonic()
            try:
                res = chain.complete_json(system, user, validate, max_tokens=mt, timeout_scale=scale, task=task)
            except LLMUnavailable as exc:
                print(f"  [{task}] ОШИБКА за {time.monotonic() - t0:.1f} с: {exc.reason}; {exc.attempts}")
                continue
            ok += 1
            print(f"  [{task}] ok за {res.latency_ms / 1000:.1f} с, токены {res.tokens_in}+{res.tokens_out}")
            print("   ", json.dumps(res.data, ensure_ascii=False, indent=1).replace("\n", "\n    ")[:3000])
    print("\nИтог:", "LLM работает" if ok else "LLM НЕ работает → ассистент собирает промпты по шаблону")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
