"""Общие фейки для тестов ассистента (без сети)."""
from __future__ import annotations

import json
import os
import sys

def _find_root(start: str) -> str:
    """Корень, где лежит пакет assistant/ — работает и в tests/, и в tests/assistant/ репозитория."""
    d = start
    while d != os.path.dirname(d):
        if os.path.isfile(os.path.join(d, "assistant", "engine.py")):
            return d
        d = os.path.dirname(d)
    raise RuntimeError("assistant/ package not found")


ROOT = _find_root(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from assistant.cards import load_cards  # noqa: E402
from assistant.engine import Assistant, AssistantDeps  # noqa: E402
from assistant.llm import CircuitBreaker, LLMChain, LLMProvider, TransportTimeout  # noqa: E402
from assistant.session import MemoryStore  # noqa: E402

PRICES = {
    "seedance-2-5": "45 ₽", "wan-3-0": "20 ₽", "veo-3-1": "120 ₽", "veo-3-1-fast": "60 ₽",
    "kling-v2-5-turbo-pro": "50 ₽", "pixverse-v6": "35 ₽", "p-video": "8 ₽", "hailuo-02": "40 ₽",
    "grok-imagine-video-1-5": "30 ₽", "gen4-turbo": "35 ₽", "seedream-5-pro": "6 ₽", "gpt-image-2": "4 ₽",
    "gpt-image-2-5-flare": "9 ₽", "gpt-image-2-5-sunburst": "9 ₽", "nano-banana-2": "7 ₽",
    "ideogram-v3-turbo": "бесплатно", "ace-step": "3 ₽", "elevenlabs-music": "25 ₽", "stable-audio-2-5": "5 ₽",
    "omni-auto-free": "бесплатно", "deepseek-v3-1": "≈ 0,2 ₽ за ответ", "claude-sonnet-5": "≈ 0,78 ₽ за ответ",
    "claude-4-5-haiku": "≈ 0,3 ₽ за ответ", "gemini-3-5-flash": "≈ 0,4 ₽ за ответ", "gpt-5-4": "≈ 1 ₽ за ответ",
}


class FakeClock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class FakeTransport:
    """Скриптованный OpenAI-совместимый транспорт. script[provider] = список шагов.

    Шаг: ("ok", content, usage?) | ("http", status) | ("timeout",) | ("slow", seconds, content)
    """

    def __init__(self, clock: FakeClock | None = None, **script):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[dict] = []
        self.clock = clock

    def __call__(self, url, headers, payload, timeout):
        name = "omniroute" if "20128" in url or "omni" in url else ("groq" if "groq" in url else url)
        self.calls.append({"provider": name, "payload": payload, "timeout": timeout, "headers": headers})
        steps = self.script.get(name) or [("http", 500)]
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        kind = step[0]
        if kind == "timeout":
            if self.clock:
                self.clock.advance(timeout)
            raise TransportTimeout("t/o")
        if kind == "http":
            return step[1], {"error": {"message": step[2] if len(step) > 2 else "err"}}
        if kind == "slow":
            if self.clock:
                self.clock.advance(step[1])
            return 200, _body(step[2])
        usage = step[2] if len(step) > 2 else {"prompt_tokens": 300, "completion_tokens": 60}
        return 200, _body(step[1], usage)


def _body(content, usage=None):
    return {"choices": [{"message": {"role": "assistant", "content": content}}], "usage": usage or {}}


def ok_json(prompt="A fried egg dancing in a cast-iron pan, cinematic close-up", note="акцент на движении"):
    return json.dumps({"prompt": prompt, "note": note}, ensure_ascii=False)


OMNI = LLMProvider("omniroute", "http://127.0.0.1:20128/v1", "k-omni", "free/llama", timeout=7)
GROQ = LLMProvider("groq", "https://api.groq.com/openai/v1", "k-groq", "llama-3.1-8b-instant", timeout=5)


def make_chain(transport, clock=None, **kw):
    clock = clock or FakeClock()
    return LLMChain([LLMProvider(**OMNI.__dict__), LLMProvider(**GROQ.__dict__)], transport=transport,
                    clock=clock, breaker=CircuitBreaker(clock=clock), **kw)


