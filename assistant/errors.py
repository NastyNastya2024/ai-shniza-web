"""Объяснение ошибок и задержек генерации — шаблоны, 0 токенов.

На входе — контекст из UI (то, что фронт знает о последнем задании):
  last_error        код ошибки из ответа /api/generate или poll (insufficient_funds, channel_unavailable, timeout…)
  last_http_status  HTTP-статус последнего ответа
  job_status        queued | queued_free | dispatched | running | requeued | failed | succeeded
  job_age_sec       сколько секунд задание живёт
  job_provider      replicate | fal | omniroute (если известен) — для сообщения о переключении
  selected_model_id модель последнего задания
На выходе — ≤4 строки + кнопки. Деньги: при ошибке hold возвращается — говорим об этом прямо.
"""
from __future__ import annotations

from typing import Any

# обычное время генерации по типу, секунд (для «это нормально / уже долго»)
TYPICAL_SEC = {"image": 40, "edit": 40, "video": 240, "music": 90, "sfx": 40, "text": 20}

E: dict[str, dict[str, Any]] = {
    "queued": {
        "ru": ["Задание в очереди — ждёт свободный канал.", "Обычно старт за 1–2 минуты. Экран можно закрыть."],
        "en": ["Your job is queued — waiting for a free channel.", "Usually starts within 1–2 minutes. You can close the screen."],
        "chips": [("wait", "wait")],
    },
    "queued_free": {
        "ru": ["Бесплатная очередь сейчас длинная.", "Платная генерация стартует сразу."],
        "en": ["The free queue is long right now.", "Paid generation starts immediately."],
        "chips": [("wait", "wait"), ("topup", "open_topup")],
    },
    "running_ok": {
        "ru": ["Генерация идёт. Для {kind} это обычно до {mins} мин.", "Результат появится в «Моих работах» — без публикации он хранится 24 часа."],
        "en": ["Generating. For {kind} this usually takes up to {mins} min.", "The result will appear in “My works” — unpublished, it’s kept for 24 hours."],
        "chips": [("wait", "wait")],
    },
    "running_slow": {
        "ru": ["Генерация идёт дольше обычного — провайдер перегружен.", "Деньги спишутся только за готовый результат."],
        "en": ["It's taking longer than usual — the provider is busy.", "You are charged only for a finished result."],
        "chips": [("wait", "wait"), ("faster", "faster")],
    },
    "failover": {
        "ru": ["Основной провайдер не ответил — переключили на резервный.", "Цена та же, ждать чуть дольше."],
        "en": ["The main provider didn't respond — switched to backup.", "Same price, slightly longer wait."],
        "chips": [("wait", "wait")],
    },
    "timeout": {
        "ru": ["Провайдер не успел сгенерировать вовремя.", "Деньги не списаны. Можно повторить или выбрать модель быстрее."],
        "en": ["The provider didn't finish in time.", "You were not charged. Retry or pick a faster model."],
        "chips": [("retry", "retry"), ("faster", "faster")],
    },
    "channel_unavailable": {
        "ru": ["Эта модель временно недоступна.", "Деньги не списаны. Предложу похожую."],
        "en": ["This model is temporarily unavailable.", "You were not charged. I'll suggest a similar one."],
        "chips": [("similar", "similar"), ("retry", "retry")],
    },
    "upstream": {
        "ru": ["Провайдер вернул ошибку.", "Деньги не списаны. Повторите или возьмите похожую модель."],
        "en": ["The provider returned an error.", "You were not charged. Retry or try a similar model."],
        "chips": [("retry", "retry"), ("similar", "similar")],
    },
    "insufficient_funds": {
        "ru": ["Не хватает средств на балансе.", "Пополните или выберите модель дешевле."],
        "en": ["Not enough balance.", "Top up or choose a cheaper model."],
        "chips": [("topup", "open_topup"), ("cheaper", "cheaper")],
    },
    "auth_required": {
        "ru": ["Чтобы генерировать, войдите в аккаунт."],
        "en": ["Please sign in to generate."],
        "chips": [("login", "login")],
    },
    "free_limit": {
        "ru": ["Бесплатные генерации на сегодня закончились.", "Завтра лимит обновится, или можно пополнить баланс."],
        "en": ["Free generations for today are used up.", "The limit resets tomorrow, or you can top up."],
        "chips": [("topup", "open_topup")],
    },
    "image_required": {
        "ru": ["Этой модели нужно фото.", "Прикрепите фото или выберите модель без него."],
        "en": ["This model needs a photo.", "Attach one or choose a model without photo."],
        "chips": [("attach", "attach"), ("no_photo_model", "no_photo_model")],
    },
    "moderation": {
        "ru": ["Запрос не прошёл проверку правил.", "Попробуйте описать идею иначе — помогу переформулировать."],
        "en": ["The request didn't pass the content rules.", "Try describing it differently — I can help rephrase."],
        "chips": [("rephrase", "rephrase")],
    },
    "rate_limited": {
        "ru": ["Слишком много запросов подряд.", "Подождите минуту и повторите."],
        "en": ["Too many requests in a row.", "Wait a minute and retry."],
        "chips": [("retry", "retry")],
    },
    "queue_unavailable": {
        "ru": ["Сервис генерации перегружен.", "Деньги не списаны. Повторите через пару минут."],
        "en": ["The generation service is overloaded.", "You were not charged. Retry in a couple of minutes."],
        "chips": [("retry", "retry")],
    },
    "unknown": {
        "ru": ["Что-то пошло не так.", "Деньги за неудачную генерацию не списываются. Повторите или напишите в поддержку."],
        "en": ["Something went wrong.", "Failed generations are not charged. Retry or contact support."],
        "chips": [("retry", "retry"), ("support", "support")],
    },
}

KIND_WORD = {"ru": {"image": "картинки", "edit": "правки фото", "video": "видео", "music": "музыки", "sfx": "звука", "text": "текста"},
             "en": {"image": "images", "edit": "photo edits", "video": "video", "music": "music", "sfx": "sound", "text": "text"}}

ALIASES = {
    "not_configured": "channel_unavailable", "unsupported_provider": "channel_unavailable", "bad_response": "upstream",
    "worker_error": "upstream", "failed": "upstream", "send_failed": "upstream", "free_queue_full": "queued_free",
    "unauthorized": "auth_required", "login_required": "auth_required", "no_image": "image_required",
    "image_required": "image_required", "too_many_requests": "rate_limited",
}


def classify(ctx: dict[str, Any]) -> str:
    err = (ctx.get("last_error") or "").strip().lower()
    if err:
        err = ALIASES.get(err, err)
        if err in E:
            return err
    st = ctx.get("last_http_status")
    if st == 401:
        return "auth_required"
    if st == 402:
        return "insufficient_funds"
    if st == 429:
        return "rate_limited"
    if st == 503:
        return "queue_unavailable"
    if isinstance(st, int) and st >= 500:
        return "upstream"
    js = ctx.get("job_status")
    if js == "queued_free":
        return "queued_free"
    if js in {"queued", "dispatched"}:
        return "queued"
    if js == "requeued" or ctx.get("job_failover"):
        return "failover"
    if js == "running":
        return "running"
    if js == "failed":
        return "upstream"
    return "unknown"


def explain(ctx: dict[str, Any], lang: str, kind: str | None = None) -> tuple[str, list[str], list[tuple[str, str]]]:
    code = classify(ctx)
    if code == "running":
        k = kind or "image"
        typical = TYPICAL_SEC.get(k, 120)
        age = float(ctx.get("job_age_sec") or 0)
        code = "running_slow" if age > typical * 1.5 else "running_ok"
        row = E[code]
        lines = [s.format(kind=KIND_WORD.get(lang, KIND_WORD["ru"]).get(k, k), mins=max(1, round(typical / 60)))
                 for s in (row.get(lang) or row["ru"])]
        return code, lines, list(row["chips"])
    row = E[code]
    return code, list(row.get(lang) or row["ru"]), list(row["chips"])
