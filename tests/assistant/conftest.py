from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # assistant_testkit
from assistant_testkit import PRICES, make_chain, ok_json, FakeTransport  # noqa: E402,F401
from assistant.cards import load_cards  # noqa: E402
from assistant.engine import Assistant, AssistantDeps  # noqa: E402
from assistant.session import MemoryStore  # noqa: E402


@pytest.fixture()
def cards():
    return load_cards()


@pytest.fixture()
def price_fn():
    return lambda mid: PRICES.get(mid)


@pytest.fixture()
def make_assistant(cards, price_fn):
    def factory(transport=None, health=None, llm=True, **kw):
        c, nb = cards
        chain = None
        if llm:
            chain = make_chain(transport or FakeTransport(omniroute=[("ok", ok_json())]))
        deps = AssistantDeps(cards=c, neighbors=nb, price_fn=price_fn, health_fn=health, llm=chain,
                             store=MemoryStore(), **kw)
        return Assistant(deps)

    return factory
