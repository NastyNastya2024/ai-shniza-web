"""Метрики сайта для админа: где люди спотыкаются при генерации, где уходят, сколько раз возвращаются.

Сбор (без сторонних счётчиков, всё своё):
  POST /api/m  — пачка событий от /aish-metrics.js (sendBeacon). CSRF не нужен (см. security.py), есть лимит частоты.
       тело: {vid, sid, events: [{n, page, ago, p: {...}}]}
       vid — анонимный id браузера (localStorage), sid — визит (новый после 30 мин тишины).
       uid берём из серверной сессии (вошёл ли человек); IP и User-Agent не храним (только mobile/desktop).
Отчёт (только ADMIN_EMAILS):
  GET /admin/metrics                         — страница admin-metrics.html
  GET /api/admin/metrics?days=7|30|90        — весь отчёт одним JSON (build_report)
  GET /api/admin/metrics/visitor/<vid>       — путь одного посетителя: визиты и события по порядку
  GET /api/admin/metrics/events.csv?days=N   — сырые события для выгрузки

Env: METRICS_DAYS (90 — сколько хранить), METRICS_MAX_ROWS (400000 — потолок строк в отчёте),
     METRICS_SKIP_HEADLESS (1 — не писать HeadlessChrome/ботов).
Таблица site_events создаётся обычным db.create_all().
"""
from __future__ import annotations

import csv
import io
import json
import os
import random
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

# ─────────────────────────────────────────────────────────────── словарь событий
# имя события → разрешённые поля props (всё остальное отбрасываем)
EVENTS: dict[str, tuple[str, ...]] = {
    "page_view": ("ref", "utm_source", "utm_medium", "utm_campaign", "lang", "w", "theme"),
    "page_leave": ("ms", "scroll", "pending"),
    "prompt_sent": ("len", "files", "assist"),
    "assist_reply": ("intent", "degraded", "gate", "models"),
    "assist_action": ("action", "value"),
    "models_shown": ("n", "kind"),
    "model_pick": ("model", "kind", "src"),
    "generate_click": ("model", "kind", "src"),
    "gen_start": ("model", "kind", "queue"),
    "gen_done": ("model", "kind", "ms"),
    "gen_fail": ("model", "kind", "code", "http", "started", "ms"),
    "gate": ("type", "src"),
    "login_click": ("src",),
    "topup_click": ("src",),
    "topup_start": ("amount",),
    "attach_add": ("kind",),
    "attach_fail": ("kind", "code"),
    "publish": ("work",),
    "publish_fail": ("code",),
    "new_chat": (),
    "vit_open": ("work", "kind"),
    "vit_use": ("work", "model"),
    "vit_like": ("work",),
    "auth_view": ("next",),
    "auth_ok": ("method",),
    "auth_fail": ("method", "code"),
    "js_error": ("msg", "src"),
}
PAGE_LABEL = {"/": "Главная", "/app": "Студия", "/explore": "Витрина", "/creator": "Страница автора",
              "/account": "Кабинет", "/auth": "Вход", "/w": "Работа", "/prices": "Цены", "/legal": "Документы",
              "/other": "Другие"}
FUNNEL: list[tuple[str, str]] = [
    ("visit", "Зашли на сайт"),
    ("studio", "Открыли студию"),
    ("prompt", "Написали идею или нажали кнопку помощника"),
    ("models", "Увидели подборку нейросетей"),
    ("pick", "Выбрали нейросеть"),
    ("click", "Нажали «Сгенерировать»"),
    ("start", "Генерация запущена"),
    ("done", "Получили результат"),
    ("share", "Опубликовали на витрине"),
]
STEP_OF_EVENT = {"prompt_sent": "prompt", "assist_action": "prompt", "models_shown": "models", "model_pick": "pick",
                 "generate_click": "click", "gen_start": "start", "gen_done": "done", "publish": "share"}
STEP_INDEX = {k: i for i, (k, _) in enumerate(FUNNEL)}
EXIT_LABEL = {
    "left_waiting": "Ушли, не дождавшись результата генерации",
    "after_error": "Ушли после ошибки генерации",
    "gate_login": "Ушли на просьбе войти",
    "gate_topup": "Ушли на просьбе пополнить баланс",
    "assistant_confused": "Помощник не понял — ушли",
    "no_click": "Выбрали нейросеть, но не запустили",
    "no_pick": "Увидели подборку, но не выбрали нейросеть",
    "no_models": "Написали идею — дальше не пошли",
    "studio_idle": "Открыли студию и ничего не сделали",
    "success": "Ушли с готовым результатом",
    "bounce": "Отказ: одна страница",
    "browse": "Посмотрели страницы, до студии не дошли",
}
GEN_ERROR_LABEL = {
    "auth": "Не вошёл в аккаунт",
    "insufficient_funds": "Не хватило денег на балансе",
    "moderation": "Фильтр контента нейросети",
    "timeout": "Слишком долго — время вышло",
    "need_image": "Нейросети нужно фото, а его нет",
    "need_audio": "Нейросети нужен звук",
    "need_video": "Нейросети нужно видео",
    "upload_expired": "Файл устарел или не найден",
    "file_too_large": "Файл слишком большой",
    "service_down": "Сервис генерации недоступен",
    "model_down": "Нейросеть временно недоступна",
    "free_limit": "Кончились бесплатные генерации",
    "free_queue_full": "Бесплатная очередь переполнена",
    "estimate_failed": "Не удалось посчитать цену",
    "failed": "Нейросеть не справилась",
    "not_started": "Генерация не запустилась",
    "network": "Нет связи",
}
ATTACH_ERROR_LABEL = {"type": "Формат файла не подходит", "heic": "Фото HEIC (iPhone)", "too_large": "Файл слишком большой",
                      "file_too_large": "Файл слишком большой", "network": "Обрыв связи при загрузке", "server": "Ошибка сервера"}
# ответы помощника, которые значат «не понял / что-то пошло не так»
ASSIST_PROBLEM = {"junk": "Не понял сообщение («ооло»)", "pipe_junk": "Не понял ответ на шаге флоу",
                  "internal_error": "Внутренняя ошибка помощника", "model_down": "Нейросеть недоступна — предложил другие",
                  "off_topic": "Вопрос не по теме", "unknown": "Не распознал задачу", "noop": "Кнопка без действия",
                  "pipe_style_fail": "Не смог разобрать стиль картинки", "crisis": "Кризисное сообщение",
                  "safety": "Запрещённый запрос", "safety_person": "Запрос о реальном человеке", "injection": "Попытка взлома промпта"}
VISIT_BUCKETS = ("1", "2", "3–5", "6–10", "11+")
GAP_BUCKETS = (("< 1 часа", 3600), ("1–24 часа", 86400), ("1–7 дней", 7 * 86400), ("> 7 дней", None))

_ID_RX = re.compile(r"^[A-Za-z0-9_-]{8,32}$")
_BOT_RX = re.compile(r"bot|spider|crawl|slurp|facebookexternalhit|yandex(?:bot|metrika)|lighthouse|pingdom", re.I)
_HEADLESS_RX = re.compile(r"headless", re.I)
_MOBILE_RX = re.compile(r"Mobi|Android|iPhone|iPad", re.I)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(os.getenv(name) or default)
    except ValueError:
        v = default
    return max(lo, min(hi, v))


def norm_page(path: Any) -> str:
    p = str(path or "/").split("?")[0].split("#")[0].strip().lower()[:200] or "/"
    if p in ("/", "/index.html", "/landing.html"):
        return "/"
    if p in ("/app", "/app.html", "/studio"):
        return "/app"
    if p.startswith("/explore"):
        return "/explore"
    if p.startswith("/creator") or p.startswith("/@") or p.startswith("/u/"):
        return "/creator"
    if p.startswith("/account") or p.startswith("/balance") or p.startswith("/settings"):
        return "/account"
    if p.startswith("/auth"):
        return "/auth"
    if p.startswith("/w/") or p.startswith("/work"):
        return "/w"
    if p.startswith("/prices") or p.startswith("/catalog"):
        return "/prices"
    if p.startswith("/legal"):
        return "/legal"
    return "/other"


def clean_props(name: str, raw: Any) -> dict:
    keys = EVENTS.get(name) or ()
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for k in keys:
        if k not in raw:
            continue
        v = raw[k]
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, float)):
            if v == v and abs(v) < 1e12:            # без NaN и мусора
                out[k] = round(float(v), 2) if isinstance(v, float) else int(v)
        elif v is None:
            continue
        else:
            s = re.sub(r"[\x00-\x1f]", " ", str(v)).strip()[:120]
            if s:
                out[k] = s
    return out


def clean_batch(body: Any, ua: str = "", skip_headless: bool = True) -> tuple[str, str, list[dict]] | None:
    """Проверка пачки от браузера. None — отбросить целиком (бот, кривые id)."""
    if not isinstance(body, dict):
        return None
    if ua and (_BOT_RX.search(ua) or (skip_headless and _HEADLESS_RX.search(ua))):
        return None
    vid, sid = str(body.get("vid") or ""), str(body.get("sid") or "")
    if not _ID_RX.match(vid) or not _ID_RX.match(sid):
        return None
    evs = body.get("events")
    if not isinstance(evs, list):
        return None
    out = []
    for e in evs[:40]:
        if not isinstance(e, dict):
            continue
        n = str(e.get("n") or "")
        if n not in EVENTS:
            continue
        try:
            ago = max(0, min(600_000, int(e.get("ago") or 0)))
        except (TypeError, ValueError):
            ago = 0
        out.append({"n": n, "page": norm_page(e.get("page")), "ago": ago, "p": clean_props(n, e.get("p"))})
    return vid, sid, out


# ─────────────────────────────────────────────────────────────── отчёт (чистые функции — их и тестируем)
def _pct(a: float, b: float) -> float:
    return round(100.0 * a / b, 1) if b else 0.0


def _median(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def _bucket_visits(n: int) -> str:
    return "1" if n <= 1 else "2" if n == 2 else "3–5" if n <= 5 else "6–10" if n <= 10 else "11+"


def _gap_bucket(sec: float) -> str:
    for label, lim in GAP_BUCKETS:
        if lim is None or sec < lim:
            return label
    return GAP_BUCKETS[-1][0]


def _session_summary(evs: list[dict]) -> dict:
    """evs — события одного визита по времени. Самый дальний шаг, причина ухода, страницы."""
    names = [e["name"] for e in evs]
    views = [e for e in evs if e["name"] == "page_view"]
    pages = [e["page"] for e in views]
    reached = {"visit"}
    if "/app" in pages:
        reached.add("studio")
    for e in evs:
        st = STEP_OF_EVENT.get(e["name"])
        if st:
            reached.add(st)
            reached.add("studio")          # все шаги генерации — в студии
        if e["name"] == "models_shown" or (e["name"] == "assist_reply" and int(e["props"].get("models") or 0) > 0):
            reached.add("models")
    furthest = max(STEP_INDEX[s] for s in reached)
    # время между шагами (первое появление каждого шага)
    first_at: dict[str, datetime] = {}
    for e in evs:
        st = "studio" if (e["name"] == "page_view" and e["page"] == "/app") else STEP_OF_EVENT.get(e["name"])
        if e["name"] == "assist_reply" and int(e["props"].get("models") or 0) > 0:
            st = "models"
        if st and st not in first_at:
            first_at[st] = e["ts"]
    # причина ухода — по последнему значимому событию
    starts = names.count("gen_start")
    ends = names.count("gen_done") + names.count("gen_fail")
    leave_pending = any(e["name"] == "page_leave" and e["props"].get("pending") for e in evs[-3:])
    sig = [e for e in evs if e["name"] in ("gen_start", "gen_done", "gen_fail", "gate", "publish", "generate_click")
           or (e["name"] == "assist_reply" and e["props"].get("intent") in ASSIST_PROBLEM)]
    last = sig[-1] if sig else None
    if (starts > ends) or leave_pending:
        reason = "left_waiting"
    elif last and last["name"] == "gen_fail":
        reason = "after_error"
    elif last and last["name"] == "gate":
        reason = "gate_topup" if last["props"].get("type") == "topup" else "gate_login"
    elif last and last["name"] == "assist_reply" and furthest < STEP_INDEX["done"]:
        reason = "assistant_confused"
    elif furthest >= STEP_INDEX["done"]:
        reason = "success"
    elif furthest >= STEP_INDEX["pick"]:
        reason = "no_click"
    elif furthest == STEP_INDEX["models"]:
        reason = "no_pick"
    elif furthest == STEP_INDEX["prompt"]:
        reason = "no_models"
    elif furthest == STEP_INDEX["studio"]:
        reason = "studio_idle"
    elif len(views) <= 1:
        reason = "bounce"
    else:
        reason = "browse"
    start, end = evs[0]["ts"], evs[-1]["ts"]
    for e in evs:
        if e["name"] == "page_leave" and e["props"].get("ms"):
            end = max(end, e["ts"])
    return {"start": start, "end": end, "sec": (end - start).total_seconds(), "pages": pages, "views": len(views),
            "landing": pages[0] if pages else (evs[0]["page"]), "exit_page": pages[-1] if pages else evs[-1]["page"],
            "reached": reached, "furthest": furthest, "reason": reason, "first_at": first_at,
            "uid": next((e["uid"] for e in evs if e["uid"]), None), "device": evs[0]["device"],
            "ref": next((e["props"].get("ref") for e in views if e["props"].get("ref")), ""),
            "utm": next((e["props"].get("utm_source") for e in views if e["props"].get("utm_source")), ""),
            "lang": next((e["props"].get("lang") for e in views if e["props"].get("lang")), ""),
            "gen_done": names.count("gen_done"), "gen_fail": names.count("gen_fail")}


def build_report(rows: Iterable[dict], days: int, now: datetime | None = None,
                 first_seen: dict[str, datetime] | None = None) -> dict:
    """rows: {ts, vid, sid, uid, page, name, props(dict), device} за период. first_seen: vid → первое событие за всё время."""
    now = now or _now()
    rows = sorted(rows, key=lambda r: (r["ts"], r.get("id") or 0))
    by_sid: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_sid[r["sid"]].append(r)
    sessions = {}
    vid_of = {}
    for sid, evs in by_sid.items():
        s = _session_summary(evs)
        s["sid"], s["vid"] = sid, evs[0]["vid"]
        sessions[sid] = s
        vid_of[sid] = s["vid"]
    by_vid: dict[str, list[dict]] = defaultdict(list)
    for s in sessions.values():
        by_vid[s["vid"]].append(s)
    for lst in by_vid.values():
        lst.sort(key=lambda s: s["start"])
    period_start = now - timedelta(days=days)
    first_seen = first_seen or {}
    n_vis = len(by_vid)
    new_vis = sum(1 for v, lst in by_vid.items() if (first_seen.get(v) or lst[0]["start"]) >= period_start)
    views_total = sum(1 for r in rows if r["name"] == "page_view")
    s_list = list(sessions.values())
    names = Counter(r["name"] for r in rows)

    # ── сводка
    first_result = []
    for s in s_list:
        fa = s["first_at"]
        if "done" in fa and "studio" in fa:
            first_result.append((fa["done"] - fa["studio"]).total_seconds())
    summary = {
        "visitors": n_vis, "new_visitors": new_vis, "returning_visitors": n_vis - new_vis,
        "sessions": len(s_list), "pageviews": views_total,
        "sessions_per_visitor": round(len(s_list) / n_vis, 2) if n_vis else 0,
        "pages_per_session": round(views_total / len(s_list), 2) if s_list else 0,
        "median_session_sec": _median([s["sec"] for s in s_list]),
        "bounce_rate": _pct(sum(1 for s in s_list if s["reason"] == "bounce"), len(s_list)),
        "logged_in_share": _pct(sum(1 for s in s_list if s["uid"]), len(s_list)),
        "mobile_share": _pct(sum(1 for s in s_list if s["device"] == "mobile"), len(s_list)),
        "gen_click": names["generate_click"], "gen_start": names["gen_start"], "gen_done": names["gen_done"],
        "gen_fail": names["gen_fail"],
        "gen_success_rate": _pct(names["gen_done"], names["gen_done"] + names["gen_fail"]),
        "visitors_with_result": sum(1 for v, lst in by_vid.items() if any(s["gen_done"] for s in lst)),
        "first_result_median_sec": _median(first_result),
        "studio_visitors": sum(1 for v, lst in by_vid.items() if any("studio" in s["reached"] for s in lst)),
    }

    # ── по дням
    daily = []
    day_rows: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        day_rows[r["ts"].strftime("%Y-%m-%d")].append(r)
    for i in range(days - 1, -1, -1):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        rs = day_rows.get(d, [])
        c = Counter(r["name"] for r in rs)
        daily.append({"day": d, "visitors": len({r["vid"] for r in rs}), "sessions": len({r["sid"] for r in rs}),
                      "pageviews": c["page_view"], "gen_start": c["gen_start"], "gen_done": c["gen_done"],
                      "gen_fail": c["gen_fail"]})

    # ── страницы: сколько раз один и тот же человек открывает страницу
    view_cnt: dict[str, Counter] = defaultdict(Counter)        # page → vid → просмотров
    sess_views: dict[str, Counter] = defaultdict(Counter)      # page → sid → просмотров
    page_time: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["name"] == "page_view":
            view_cnt[r["page"]][r["vid"]] += 1
            sess_views[r["page"]][r["sid"]] += 1
        elif r["name"] == "page_leave" and r["props"].get("ms"):
            page_time[r["page"]].append(float(r["props"]["ms"]) / 1000)
    exit_cnt = Counter(s["exit_page"] for s in s_list)
    land_cnt = Counter(s["landing"] for s in s_list)
    pages = []
    for p, vc in view_cnt.items():
        views = sum(vc.values())
        dist = Counter(_bucket_visits(n) for n in vc.values())
        sess = len(sess_views[p])
        pages.append({"page": p, "label": PAGE_LABEL.get(p, p), "views": views, "visitors": len(vc),
                      "views_per_visitor": round(views / len(vc), 2), "max_views_one_visitor": max(vc.values()),
                      "repeat_dist": {b: dist.get(b, 0) for b in VISIT_BUCKETS},
                      "sessions": sess, "reload_sessions": sum(1 for n in sess_views[p].values() if n >= 2),
                      "landing_sessions": land_cnt.get(p, 0), "exit_sessions": exit_cnt.get(p, 0),
                      "exit_rate": _pct(exit_cnt.get(p, 0), sess), "median_sec": _median(page_time.get(p, []))})
    pages.sort(key=lambda x: -x["views"])

    # ── воронка генерации: по визитам и по людям
    def funnel_for(groups: list[set]) -> list[dict]:
        out, prev, first = [], None, None
        for k, label in FUNNEL:
            n = sum(1 for g in groups if k in g)
            first = n if first is None else first
            out.append({"key": k, "label": label, "count": n, "conv_prev": _pct(n, prev) if prev is not None else 100.0,
                        "conv_first": _pct(n, first), "drop": (prev - n) if prev is not None else 0})
            prev = n
        return out
    # шаг засчитан, если человек дошёл до него или дальше (модель можно выбрать и в панели, минуя подборку помощника)
    upto = lambda k: {FUNNEL[i][0] for i in range(k + 1)}  # noqa: E731
    funnel_sessions = funnel_for([upto(s["furthest"]) for s in s_list])
    funnel_visitors = funnel_for([upto(max(s["furthest"] for s in lst)) for lst in by_vid.values()])
    step_times = []
    for (a, la), (b, lb) in zip(FUNNEL[1:], FUNNEL[2:]):
        xs = [(s["first_at"][b] - s["first_at"][a]).total_seconds() for s in s_list
              if a in s["first_at"] and b in s["first_at"] and s["first_at"][b] >= s["first_at"][a]]
        step_times.append({"from": la, "to": lb, "median_sec": _median(xs), "n": len(xs)})

    # ── где уходят
    rc = Counter(s["reason"] for s in s_list)
    exits = [{"reason": k, "label": EXIT_LABEL[k], "sessions": rc.get(k, 0), "share": _pct(rc.get(k, 0), len(s_list))}
             for k in EXIT_LABEL if rc.get(k)]
    exits.sort(key=lambda x: -x["sessions"])
    exit_pages = [{"page": p, "label": PAGE_LABEL.get(p, p), "sessions": n, "share": _pct(n, len(s_list))}
                  for p, n in exit_cnt.most_common()]

    # ── трудности при генерации
    fails = [r for r in rows if r["name"] == "gen_fail"]
    fc = Counter(r["props"].get("code") or "failed" for r in fails)
    fail_codes = [{"code": c, "label": GEN_ERROR_LABEL.get(c, c), "count": n, "share": _pct(n, len(fails)),
                   "visitors": len({r["vid"] for r in fails if (r["props"].get("code") or "failed") == c})}
                  for c, n in fc.most_common()]
    per_model: dict[str, Counter] = defaultdict(Counter)
    gen_ms: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["name"] in ("generate_click", "gen_start", "gen_done", "gen_fail"):
            m = r["props"].get("model") or "—"
            per_model[m][r["name"]] += 1
            if r["name"] == "gen_done" and r["props"].get("ms"):
                gen_ms[m].append(float(r["props"]["ms"]) / 1000)
    models = []
    for m, c in per_model.items():
        tot = c["gen_done"] + c["gen_fail"]
        models.append({"model": m, "clicks": c["generate_click"], "starts": c["gen_start"], "done": c["gen_done"],
                       "fail": c["gen_fail"], "fail_rate": _pct(c["gen_fail"], tot), "median_sec": _median(gen_ms.get(m, []))})
    models.sort(key=lambda x: -(x["fail"] * 1000 + x["clicks"]))
    intents = Counter(r["props"].get("intent") or "unknown" for r in rows if r["name"] == "assist_reply")
    assist_problems = [{"intent": k, "label": ASSIST_PROBLEM[k], "count": n} for k, n in intents.most_common() if k in ASSIST_PROBLEM]
    degraded = sum(1 for r in rows if r["name"] == "assist_reply" and r["props"].get("degraded"))
    gates = Counter(r["props"].get("type") or "login" for r in rows if r["name"] == "gate")
    ac = Counter(r["props"].get("code") or "server" for r in rows if r["name"] == "attach_fail")
    long_gen = sum(1 for r in rows if r["name"] == "gen_done" and float(r["props"].get("ms") or 0) > 180_000)
    js = Counter(r["props"].get("msg") or "?" for r in rows if r["name"] == "js_error")
    # люди, у которых генерация так и не получилась: были ошибки, ни одного результата
    stuck = []
    for v, lst in by_vid.items():
        f = sum(s["gen_fail"] for s in lst)
        if f and not any(s["gen_done"] for s in lst):
            stuck.append(v)
    problems = {
        "fail_codes": fail_codes, "models": models[:30],
        "assistant": assist_problems, "assistant_replies": sum(intents.values()), "assistant_degraded": degraded,
        "assistant_top_intents": [{"intent": k, "count": n} for k, n in intents.most_common(15)],
        "gates": {"login": gates.get("login", 0), "topup": gates.get("topup", 0),
                  "login_click": names["login_click"], "topup_click": names["topup_click"], "topup_start": names["topup_start"],
                  "auth_ok": names["auth_ok"], "auth_fail": names["auth_fail"]},
        "attach": {"added": names["attach_add"], "failed": names["attach_fail"],
                   "codes": [{"code": c, "label": ATTACH_ERROR_LABEL.get(c, c), "count": n} for c, n in ac.most_common()]},
        "long_generations": long_gen, "left_waiting": rc.get("left_waiting", 0),
        "visitors_never_succeeded": len(stuck),
        "js_errors": [{"msg": k, "count": n} for k, n in js.most_common(10)],
        "publish_fail": names["publish_fail"],
    }

    # ── возвраты: сколько раз приходит один человек и с какого этапа возвращается
    visits_dist = Counter(_bucket_visits(len(lst)) for lst in by_vid.values())
    gaps = Counter()
    ret_from: dict[str, list[int]] = defaultdict(lambda: [0, 0])       # причина ухода → [визитов, из них вернулись]
    ret_stage: dict[int, list[int]] = defaultdict(lambda: [0, 0])      # дальний шаг визита → [визитов, вернулись]
    ret_to_land = Counter()
    ret_to_step = Counter()
    continued = progressed = total_returns = 0
    matrix = Counter()
    for v, lst in by_vid.items():
        best = -1
        for i, s in enumerate(lst):
            returned = i + 1 < len(lst)
            ret_from[s["reason"]][0] += 1
            ret_stage[s["furthest"]][0] += 1
            if returned:
                ret_from[s["reason"]][1] += 1
                ret_stage[s["furthest"]][1] += 1
            best = max(best, s["furthest"])
            if i == 0:
                continue
            prev = lst[i - 1]
            total_returns += 1
            gaps[_gap_bucket((s["start"] - prev["end"]).total_seconds())] += 1
            ret_to_land[s["landing"]] += 1
            ret_to_step[s["furthest"]] += 1
            matrix[(prev["reason"], s["furthest"])] += 1
            prev_best = max(x["furthest"] for x in lst[:i])
            if s["furthest"] >= max(prev["furthest"], STEP_INDEX["studio"]):
                continued += 1
            if s["furthest"] > prev_best:
                progressed += 1
    returns = {
        "visits_per_visitor": {b: visits_dist.get(b, 0) for b in VISIT_BUCKETS},
        "returning_share": _pct(sum(1 for lst in by_vid.values() if len(lst) > 1), n_vis),
        "returns": total_returns,
        "gap": [{"label": g, "count": gaps.get(g, 0)} for g, _ in GAP_BUCKETS],
        "by_exit_reason": sorted([{"reason": k, "label": EXIT_LABEL[k], "sessions": a, "returned": b, "rate": _pct(b, a)}
                                  for k, (a, b) in ret_from.items()], key=lambda x: -x["sessions"]),
        "by_stage": [{"step": FUNNEL[i][0], "label": FUNNEL[i][1], "sessions": ret_stage[i][0], "returned": ret_stage[i][1],
                      "rate": _pct(ret_stage[i][1], ret_stage[i][0])} for i in range(len(FUNNEL)) if ret_stage[i][0]],
        "return_landing": [{"page": p, "label": PAGE_LABEL.get(p, p), "count": n} for p, n in ret_to_land.most_common()],
        "return_reached": [{"step": FUNNEL[i][0], "label": FUNNEL[i][1], "count": ret_to_step[i]}
                           for i in range(len(FUNNEL)) if ret_to_step[i]],
        "continued_share": _pct(continued, total_returns), "progressed_share": _pct(progressed, total_returns),
        "matrix": [{"from": EXIT_LABEL[a], "to": FUNNEL[b][1], "count": n} for (a, b), n in matrix.most_common(25)],
    }

    # ── откуда пришли и с чего начали
    refs = Counter(s["ref"] or "(прямой заход)" for s in s_list)
    utm = Counter(s["utm"] for s in s_list if s["utm"])
    sources = {"referrers": [{"ref": k, "sessions": n} for k, n in refs.most_common(15)],
               "utm": [{"source": k, "sessions": n} for k, n in utm.most_common(15)],
               "landing": [{"page": p, "label": PAGE_LABEL.get(p, p), "sessions": n} for p, n in land_cnt.most_common()],
               "devices": dict(Counter(s["device"] for s in s_list)),
               "langs": dict(Counter(s["lang"] or "—" for s in s_list))}

    # ── посетители (последние 60)
    vis = []
    for v, lst in by_vid.items():
        vc = Counter(p for s in lst for p in s["pages"])
        vis.append({"vid": v, "uid": next((s["uid"] for s in lst if s["uid"]), None), "visits": len(lst),
                    "pageviews": sum(s["views"] for s in lst), "studio_opens": vc.get("/app", 0),
                    "furthest": FUNNEL[max(s["furthest"] for s in lst)][1], "gen_done": sum(s["gen_done"] for s in lst),
                    "gen_fail": sum(s["gen_fail"] for s in lst), "last_reason": EXIT_LABEL[lst[-1]["reason"]],
                    "first_seen": (first_seen.get(v) or lst[0]["start"]).isoformat() + "Z",
                    "last_seen": lst[-1]["end"].isoformat() + "Z", "device": lst[-1]["device"]})
    vis.sort(key=lambda x: x["last_seen"], reverse=True)

    return {"days": days, "generated_at": now.isoformat() + "Z", "events": len(rows), "summary": summary, "daily": daily,
            "pages": pages, "funnel": {"sessions": funnel_sessions, "visitors": funnel_visitors, "step_times": step_times},
            "exits": {"reasons": exits, "pages": exit_pages}, "problems": problems, "returns": returns,
            "sources": sources, "visitors": vis[:60]}


def visitor_journey(rows: Iterable[dict]) -> dict:
    rows = sorted(rows, key=lambda r: (r["ts"], r.get("id") or 0))
    by_sid: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_sid[r["sid"]].append(r)
    visits = []
    for sid, evs in by_sid.items():
        s = _session_summary(evs)
        visits.append({"sid": sid, "start": s["start"].isoformat() + "Z", "sec": s["sec"], "furthest": FUNNEL[s["furthest"]][1],
                       "reason": EXIT_LABEL[s["reason"]], "pages": [PAGE_LABEL.get(p, p) for p in s["pages"]],
                       "events": [{"t": e["ts"].isoformat() + "Z", "n": e["name"], "page": PAGE_LABEL.get(e["page"], e["page"]),
                                   "p": e["props"]} for e in evs][:400]})
    visits.sort(key=lambda v: v["start"])
    return {"visits": visits, "uid": next((r["uid"] for r in rows if r["uid"]), None)}


# ─────────────────────────────────────────────────────────────── Flask
def register_site_metrics(app: Any, db: Any, User: Any) -> dict:
    from flask import Response, jsonify, request, send_from_directory, session

    from security import ensure_csrf_token, rate_limit

    class SiteEvent(db.Model):
        __tablename__ = "site_events"
        id = db.Column(db.Integer, primary_key=True)
        ts = db.Column(db.DateTime, nullable=False, default=_now, index=True)
        vid = db.Column(db.String(32), nullable=False, index=True)
        sid = db.Column(db.String(32), nullable=False, index=True)
        uid = db.Column(db.Integer, nullable=True, index=True)
        page = db.Column(db.String(16), nullable=False, default="/")
        name = db.Column(db.String(24), nullable=False, index=True)
        props = db.Column(db.Text, nullable=False, default="{}")
        device = db.Column(db.String(8), nullable=False, default="desktop")

    def _admin_ok() -> bool:
        emails = {e.strip().lower() for e in (os.getenv("ADMIN_EMAILS") or "").split(",") if e.strip()}
        uid = session.get("user_id")
        if not uid or not emails:
            return False
        u = User.query.get(uid)
        return bool(u and (u.email or "").lower() in emails)

    def _rows(since: datetime, vid: str | None = None):
        q = SiteEvent.query.filter(SiteEvent.ts >= since)
        if vid:
            q = q.filter(SiteEvent.vid == vid)
        q = q.order_by(SiteEvent.ts.asc(), SiteEvent.id.asc()).limit(_env_int("METRICS_MAX_ROWS", 400_000, 1000, 5_000_000))
        for e in q.all():
            try:
                p = json.loads(e.props or "{}")
            except ValueError:
                p = {}
            yield {"id": e.id, "ts": e.ts, "vid": e.vid, "sid": e.sid, "uid": e.uid, "page": e.page, "name": e.name,
                   "props": p if isinstance(p, dict) else {}, "device": e.device}

    @app.route("/api/m", methods=["POST"])
    @rate_limit(240, 60, "metrics")
    def api_metrics_ingest():
        if request.content_length and request.content_length > 64_000:
            return ("", 413)
        body = request.get_json(silent=True, force=True)
        skip = (os.getenv("METRICS_SKIP_HEADLESS") or "1").strip().lower() not in {"0", "false", "no"}
        got = clean_batch(body, request.headers.get("User-Agent") or "", skip)
        if not got or not got[2]:
            return ("", 204)
        vid, sid, evs = got
        now = _now()
        uid = session.get("user_id")
        device = "mobile" if _MOBILE_RX.search(request.headers.get("User-Agent") or "") else "desktop"
        for e in evs:
            db.session.add(SiteEvent(ts=now - timedelta(milliseconds=e["ago"]), vid=vid, sid=sid, uid=uid, page=e["page"],
                                     name=e["n"], props=json.dumps(e["p"], ensure_ascii=False), device=device))
        if random.random() < 0.01:   # ленивая чистка старых событий
            cutoff = now - timedelta(days=_env_int("METRICS_DAYS", 90, 7, 3650))
            SiteEvent.query.filter(SiteEvent.ts < cutoff).delete(synchronize_session=False)
        db.session.commit()
        return ("", 204)

    @app.route("/admin/metrics")
    def admin_metrics_page():
        ensure_csrf_token()
        return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "admin-metrics.html")

    @app.route("/api/admin/metrics", methods=["GET"])
    def api_admin_metrics():
        if not _admin_ok():
            return jsonify({"error": "forbidden"}), 403
        try:
            days = int(request.args.get("days") or 30)
        except ValueError:
            days = 30
        days = max(1, min(_env_int("METRICS_DAYS", 90, 7, 3650), days))
        now = _now()
        rows = list(_rows(now - timedelta(days=days)))
        vids = list({r["vid"] for r in rows})
        first_seen: dict[str, datetime] = {}
        for i in range(0, len(vids), 500):
            chunk = vids[i:i + 500]
            for v, ts in db.session.query(SiteEvent.vid, db.func.min(SiteEvent.ts)).filter(SiteEvent.vid.in_(chunk)).group_by(SiteEvent.vid):
                first_seen[v] = ts
        rep = build_report(rows, days, now, first_seen)
        rep["max_days"] = _env_int("METRICS_DAYS", 90, 7, 3650)
        return jsonify(rep)

    @app.route("/api/admin/metrics/visitor/<vid>", methods=["GET"])
    def api_admin_metrics_visitor(vid):
        if not _admin_ok():
            return jsonify({"error": "forbidden"}), 403
        if not _ID_RX.match(vid or ""):
            return jsonify({"error": "bad_vid"}), 400
        since = _now() - timedelta(days=_env_int("METRICS_DAYS", 90, 7, 3650))
        out = visitor_journey(_rows(since, vid))
        if out.get("uid"):
            u = User.query.get(out["uid"])
            out["email"] = (u.email if u else "") or ""
        return jsonify(out)

    @app.route("/api/admin/metrics/events.csv", methods=["GET"])
    def api_admin_metrics_csv():
        if not _admin_ok():
            return jsonify({"error": "forbidden"}), 403
        try:
            days = max(1, min(365, int(request.args.get("days") or 30)))
        except ValueError:
            days = 30
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["ts_utc", "visitor", "visit", "user_id", "page", "event", "props", "device"])
        for r in _rows(_now() - timedelta(days=days)):
            w.writerow([r["ts"].isoformat(), r["vid"], r["sid"], r["uid"] or "", r["page"], r["name"],
                        json.dumps(r["props"], ensure_ascii=False), r["device"]])
        return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename=site-events-{days}d.csv"})

    return {"SiteEvent": SiteEvent}
