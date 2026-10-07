"""{AI}-шница — ассистент-навигатор чата студии.

Ядро не зависит от Flask: Assistant(...).handle(...) → dict.
Подключение к Flask — assistant.flask_adapter.register_assistant(app, ...).
"""
from .engine import Assistant, AssistantDeps  # noqa: F401

__all__ = ["Assistant", "AssistantDeps"]
