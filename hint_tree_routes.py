"""Дерево подсказок в админке: схема, нехарактерные действия, новые пути, черновик, публикация, откат.

    from hint_tree_routes import register_hint_tree
    register_hint_tree(app, db, User, ASSISTANT)       # после register_assistant(...)

Таблицы (создаются обычным db.create_all()):
  hint_tree_versions — версии дерева (draft / published / archived), JSON рабочего формата assistant/data/hint_tree.json
  hint_tree_events   — минимальный лог: история, шаг, реакция, контекст, профессия, короткая подпись действия.
                       Без текста генераций и без истории работ; sid — хэш; хранится HINT_TREE_LOG_DAYS (90) дней.

Опубликованная версия подхватывается всеми воркерами: перед запросом к помощнику раз в 30 с сверяем id версии.
"""
from __future__ import annotations

import copy
import json
import os
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from assistant.tree import HintTree, _stems, make_logger


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.getenv(name) or default)))
    except ValueError:
        return default


def bump(version: str, part: str) -> str:
    """semver: major — новый вектор/уровень, minor — новые истории/подсказки, patch — правка текста."""
    try:
        ma, mi, pa = (int(x) for x in str(version).split(".")[:3])
    except ValueError:
        ma, mi, pa = 1, 0, 0
    if part == "major":
        return f"{ma + 1}.0.0"
    if part == "minor":
        return f"{ma}.{mi + 1}.0"
    return f"{ma}.{mi}.{pa + 1}"


# ===================================================================== правки черновика (без Flask — тестируется отдельно)
def find_story(data: dict, sid: str) -> tuple[dict, dict, dict] | None:
    for v in data.get("vectors") or []:
        for s in v.get("subs") or []:
            for o in s.get("stories") or []:
                if o["id"] == sid:
                    return v, s, o
    return None


def apply_op(data: dict, op: dict) -> tuple[dict, str]:
    """Одна правка черновика. Возвращает (данные, часть версии для bump). ValueError — понятная ошибка для админки."""
    kind = str(op.get("op") or "")
    d = copy.deepcopy(data)
    if kind in ("add_hint", "edit_hints", "set_status"):
        got = find_story(d, str(op.get("story") or ""))
        if not got:
            raise ValueError("Нет такой истории")
        _v, _s, o = got
        if kind == "set_status":
            st = str(op.get("status") or "")
            if st not in ("active", "deprecated"):
                raise ValueError("Статус: active или deprecated")
            o["status"] = st
            return d, "minor"
        i = int(op.get("step") or 0)
        if not (0 <= i < len(o.get("steps") or [])):
            raise ValueError("Нет такого шага")
        hints = o["steps"][i].setdefault("hints", [])
        if kind == "add_hint":
            label = _clean_label(op.get("label"))
            if label in hints:
                raise ValueError("Такая подсказка уже есть")
            pos = int(op.get("position") if op.get("position") is not None else len(hints))
            hints.insert(max(0, min(pos, len(hints))), label)
            return d, "minor"
        new = [_clean_label(x) for x in op.get("hints") or []]
        if not new or len(new) > 6:
            raise ValueError("От 1 до 6 подсказок")
        o["steps"][i]["hints"] = new
        return d, "patch"
    if kind == "add_story":
        vid, sub = str(op.get("vector") or ""), str(op.get("sub") or "")
        v = next((x for x in d.get("vectors") or [] if x["id"] == vid), None)
        s = next((x for x in (v or {}).get("subs") or [] if x["id"] in (sub, f"{vid}.{sub}")), None)
        if not s:
            raise ValueError("Нет такого подвектора")
        title = _clean_label(op.get("title"))
        steps = [{"step": _clean_label(x.get("step")), "hints": [_clean_label(h) for h in x.get("hints") or []][:6]}
                 for x in op.get("steps") or [] if isinstance(x, dict) and x.get("step")]
        if not steps:
            raise ValueError("Нужен хотя бы один шаг")
        n = len(s.get("stories") or []) + 1
        sid = f"{s['id']}.S{n:02d}"
        while find_story(d, sid):
            n += 1
            sid = f"{s['id']}.S{n:02d}"
        s.setdefault("stories", []).append({"id": sid, "title": title, "professions": list(op.get("professions") or [])[:8],
                                            "priority": "low" if op.get("priority") == "low" else "normal", "related": [],
                                            "status": "active", "source": "log", "steps": steps})
        return d, "minor"
    raise ValueError("Неизвестная правка")


def _clean_label(v: Any) -> str:
    s = re.sub(r"\s+", " ", str(v or "")).strip()[:80]
    if not s:
        raise ValueError("Пустая подпись")
    if re.search(r"replicate|fal\.ai|omniroute|openrouter|groq|gigachat|api[_ -]?key|secret|smtp", s, re.I):
        raise ValueError("В подсказках не называем внутреннюю кухню студии")
    return s


# ===================================================================== аналитика по логу
def atypical_report(rows: list[dict], rules: dict) -> list[dict]:
    """Нехарактерные действия: известная история и шаг, но человек сделал то, чего нет в подсказках."""
    runs: Counter = Counter()
    odd: dict[tuple, Counter] = defaultdict(Counter)
    for r in rows:
        key = (r["story"], r["step"])
        if r["kind"] == "run":
            runs[key] += 1
        elif r["kind"] == "atypical" and r.get("label"):
            odd[key][_norm_label(r["label"])] += 1
    share = float(rules.get("atypical_share", 0.05))
    min_runs = int(rules.get("atypical_min_runs", 20))
    out = []
    for key, labels in odd.items():
        total = max(runs[key], sum(labels.values()))
        for label, n in labels.most_common(10):
            sh = n / total if total else 0.0
            out.append({"story": key[0], "step": key[1], "label": label, "count": n, "runs": total,
                        "share": round(sh, 3), "flag": sh >= share and total >= min_runs})
    out.sort(key=lambda x: (not x["flag"], -x["count"]))
    return out[:300]


def new_paths_report(rows: list[dict], rules: dict) -> list[dict]:
    """Новые пути: 3+ действия подряд вне каталога. Группируем по общим словам, считаем разные диалоги."""
    clusters: dict[str, dict] = {}
    for r in rows:
        if r["kind"] != "new_path":
            continue
        trail = r.get("trail") or []
        sig = " ".join(sorted({w for t in trail for w in _stems(t)})[:6]) or "—"
        c = clusters.setdefault(sig, {"signature": sig, "dialogs": set(), "examples": [], "professions": Counter()})
        c["dialogs"].add(r.get("sid") or "")
        if len(c["examples"]) < 3:
            c["examples"].append(" → ".join(trail))
        c["professions"][r.get("profession") or "—"] += 1
    need = int(rules.get("cluster_dialogs", 20))
    out = [{"signature": c["signature"], "dialogs": len(c["dialogs"]), "examples": c["examples"],
            "professions": dict(c["professions"].most_common(3)), "flag": len(c["dialogs"]) >= need}
           for c in clusters.values()]
    out.sort(key=lambda x: (not x["flag"], -x["dialogs"]))
    return out[:200]


def off_story_report(rows: list[dict]) -> list[dict]:
    """Переходы из одной истории в другую посреди шага — кандидаты в связки историй."""
    cnt = Counter((r["story"], r.get("to") or "") for r in rows if r["kind"] == "off_story")
    return [{"from": a, "to": b, "count": n} for (a, b), n in cnt.most_common(50)]


def story_counters(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(lambda: {"starts": 0, "runs": 0, "atypical": 0, "flows": 0, "max_step": 0})
    for r in rows:
        if not r.get("story"):
            continue
        c = out[r["story"]]
        k = r["kind"]
        if k == "start":
            c["starts"] += 1
        elif k == "run":
            c["runs"] += 1
            c["max_step"] = max(c["max_step"], int(r.get("step") or 0))
        elif k == "atypical":
            c["atypical"] += 1
        elif k == "flow":
            c["flows"] += 1
    return dict(out)


def _norm_label(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()[:80]


# ===================================================================== Flask
def register_hint_tree(app: Any, db: Any, User: Any, assistant: Any) -> dict:
    from flask import Response, jsonify, request, send_from_directory, session

    from security import ensure_csrf_token

    class HintTreeVersion(db.Model):
        __tablename__ = "hint_tree_versions"
        id = db.Column(db.Integer, primary_key=True)
        version = db.Column(db.String(16), nullable=False, unique=True)
        status = db.Column(db.String(12), nullable=False, default="draft", index=True)   # draft | published | archived
        data = db.Column(db.Text, nullable=False)
        note = db.Column(db.String(300), nullable=False, default="")
        created_by = db.Column(db.String(120), nullable=False, default="")
        created_at = db.Column(db.DateTime, nullable=False, default=_now)
        published_at = db.Column(db.DateTime, nullable=True)

    class HintTreeEvent(db.Model):
        __tablename__ = "hint_tree_events"
        id = db.Column(db.Integer, primary_key=True)
        ts = db.Column(db.DateTime, nullable=False, default=_now, index=True)
        kind = db.Column(db.String(12), nullable=False, index=True)
        story = db.Column(db.String(40), nullable=True, index=True)
        step = db.Column(db.Integer, nullable=True)
        reaction = db.Column(db.String(8), nullable=True)
        context = db.Column(db.String(4), nullable=True)
        profession = db.Column(db.String(16), nullable=True)
        label = db.Column(db.String(80), nullable=True)
        extra = db.Column(db.Text, nullable=False, default="{}")    # to / trail / flow / streak
        sid = db.Column(db.String(16), nullable=False, default="", index=True)
        uid = db.Column(db.Integer, nullable=True)

    def _admin_email() -> str | None:
        emails = {e.strip().lower() for e in (os.getenv("ADMIN_EMAILS") or "").split(",") if e.strip()}
        uid = session.get("user_id")
        if not uid or not emails:
            return None
        u = db.session.get(User, uid)
        em = (u.email or "").lower() if u else ""
        return em if em in emails else None

    # ------------------------------------------------------------ лог из помощника
    def write(ev: dict) -> None:
        try:
            extra = {k: ev[k] for k in ("to", "trail", "flow", "streak", "action", "leaf") if k in ev}
            uid = ev.get("uid")
            db.session.add(HintTreeEvent(
                kind=str(ev.get("kind") or "")[:12], story=(str(ev["story"])[:40] if ev.get("story") else None),
                step=int(ev["step"]) if isinstance(ev.get("step"), int) else None,
                reaction=(str(ev.get("reaction") or "")[:8] or None), context=(str(ev.get("context") or "")[:4] or None),
                profession=(str(ev.get("profession") or "")[:16] or None), label=(str(ev.get("label") or "")[:80] or None),
                extra=json.dumps(extra, ensure_ascii=False)[:2000], sid=str(ev.get("sid") or "")[:16],
                uid=int(uid) if str(uid or "").isdigit() else None))
            if random.random() < 0.002:
                cutoff = _now() - timedelta(days=_env_int("HINT_TREE_LOG_DAYS", 90, 7, 3650))
                HintTreeEvent.query.filter(HintTreeEvent.ts < cutoff).delete(synchronize_session=False)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("hint tree log failed")

    assistant.d.tree_log = make_logger(write, sid_salt=os.getenv("SECRET_KEY", "")[:16])

    # ------------------------------------------------------------ актуальная версия во всех воркерах
    cache = {"checked": 0.0, "id": None}

    def _published() -> "HintTreeVersion | None":
        return HintTreeVersion.query.filter_by(status="published").order_by(HintTreeVersion.published_at.desc()).first()

    def refresh_tree(force: bool = False) -> None:
        import time
        now = time.monotonic()
        if not force and now - cache["checked"] < 30:
            return
        cache["checked"] = now
        try:
            row = _published()
            if row is None or row.id == cache["id"]:
                return
            asst = app.config.get("ASSISTANT") or assistant
            asst.d.tree = HintTree(json.loads(row.data))
            cache["id"] = row.id
        except Exception:
            app.logger.exception("hint tree refresh failed")

    @app.before_request
    def _hint_tree_fresh():
        if request.path.startswith("/api/assistant/"):
            refresh_tree()

    def _active_data() -> dict:
        asst = app.config.get("ASSISTANT") or assistant
        t = getattr(asst.d, "tree", None)
        return copy.deepcopy(t.data) if t else HintTree.load_json().data

    def _rows(days: int) -> list[dict]:
        since = _now() - timedelta(days=days)
        q = HintTreeEvent.query.filter(HintTreeEvent.ts >= since).order_by(HintTreeEvent.id.asc()).limit(
            _env_int("HINT_TREE_MAX_ROWS", 300_000, 1000, 3_000_000))
        out = []
        for e in q.all():
            try:
                ex = json.loads(e.extra or "{}")
            except ValueError:
                ex = {}
            out.append({"kind": e.kind, "story": e.story, "step": e.step, "reaction": e.reaction, "context": e.context,
                        "profession": e.profession, "label": e.label, "sid": e.sid, "uid": e.uid, **ex})
        return out

    def _days() -> int:
        try:
            return max(1, min(90, int(request.args.get("days") or 7)))
        except ValueError:
            return 7

    def _forbidden():
        return jsonify({"error": "forbidden"}), 403

    # ------------------------------------------------------------ страницы и API
    @app.route("/admin/hint-tree")
    def admin_hint_tree_page():
        ensure_csrf_token()
        return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "admin-hint-tree.html")

    @app.route("/api/admin/hint-tree", methods=["GET"])
    def api_hint_tree():
        if not _admin_email():
            return _forbidden()
        data = _active_data()
        t = HintTree(data)
        rows = _rows(_days())
        draft = HintTreeVersion.query.filter_by(status="draft").order_by(HintTreeVersion.id.desc()).first()
        return jsonify({"version": t.version, "tree": t.summary(), "counters": story_counters(rows),
                        "unknown_profession": sum(1 for r in rows if r["kind"] == "run" and not r.get("profession")),
                        "draft": draft.version if draft else None, "days": _days()})

    @app.route("/api/admin/hint-tree/story/<sid>", methods=["GET"])
    def api_hint_tree_story(sid: str):
        if not _admin_email():
            return _forbidden()
        draft = HintTreeVersion.query.filter_by(status="draft").order_by(HintTreeVersion.id.desc()).first()
        data = json.loads(draft.data) if draft else _active_data()
        got = find_story(data, sid)
        if not got:
            return jsonify({"error": "not_found"}), 404
        v, s, o = got
        rows = [r for r in _rows(_days()) if r.get("story") == sid]
        return jsonify({"vector": v["id"], "sub": s["id"], "examples": s.get("examples") or [], "story": o,
                        "from_draft": bool(draft), "atypical": atypical_report(rows, HintTree(data).rules)[:30]})

    @app.route("/api/admin/hint-tree/atypical", methods=["GET"])
    def api_hint_tree_atypical():
        if not _admin_email():
            return _forbidden()
        return jsonify({"items": atypical_report(_rows(_days()), HintTree(_active_data()).rules)})

    @app.route("/api/admin/hint-tree/new", methods=["GET"])
    def api_hint_tree_new():
        if not _admin_email():
            return _forbidden()
        rows = _rows(_days())
        rules = HintTree(_active_data()).rules
        groups = Counter(r.get("label") or "" for r in rows if r["kind"] == "start" and not r.get("profession"))
        return jsonify({"paths": new_paths_report(rows, rules), "jumps": off_story_report(rows),
                        "no_profession_starts": sum(groups.values()), "rules": rules})

    @app.route("/api/admin/hint-tree/versions", methods=["GET"])
    def api_hint_tree_versions():
        if not _admin_email():
            return _forbidden()
        rows = HintTreeVersion.query.order_by(HintTreeVersion.id.desc()).limit(50).all()
        active = HintTree(_active_data()).version
        return jsonify({"active": active, "items": [
            {"version": r.version, "status": r.status, "note": r.note, "by": r.created_by,
             "created_at": r.created_at.isoformat() + "Z", "published_at": r.published_at.isoformat() + "Z" if r.published_at else None}
            for r in rows]})

    @app.route("/api/admin/hint-tree/draft", methods=["POST"])
    def api_hint_tree_draft():
        email = _admin_email()
        if not email:
            return _forbidden()
        body = request.get_json(silent=True) or {}
        draft = HintTreeVersion.query.filter_by(status="draft").order_by(HintTreeVersion.id.desc()).first()
        base = json.loads(draft.data) if draft else _active_data()
        try:
            data, part = apply_op(base, body)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        # версия черновика = опубликованная + самая сильная правка в нём (patch < minor < major)
        rank = {"patch": 0, "minor": 1, "major": 2}
        strongest = max(part, data.get("_bump") or "patch", key=lambda x: rank.get(x, 0))
        data["_bump"] = strongest
        ver = bump(data.get("_base") or HintTree(_active_data()).version, strongest)
        data["_base"] = data.get("_base") or HintTree(_active_data()).version
        while HintTreeVersion.query.filter(HintTreeVersion.version == ver,
                                           HintTreeVersion.id != (draft.id if draft else -1)).first():
            ver = bump(ver, "patch")
        data["version"] = ver
        if draft is None:
            draft = HintTreeVersion(version=ver, status="draft", data="", created_by=email)
            db.session.add(draft)
        draft.version = ver
        note = str(body.get("note") or "")[:200]
        draft.note = (draft.note + "; " if draft.note else "") + (note or body.get("op", ""))
        draft.note = draft.note[:300]
        draft.data = json.dumps(data, ensure_ascii=False)
        db.session.commit()
        return jsonify({"ok": True, "draft": draft.version})

    def _publish(row: "HintTreeVersion", email: str) -> None:
        for r in HintTreeVersion.query.filter_by(status="published").all():
            r.status = "archived"
        data = json.loads(row.data)
        data.pop("_bump", None)
        data.pop("_base", None)
        HintTree(data)                                   # проверка: битая версия не публикуется
        data.setdefault("changelog", []).append({"version": row.version, "date": _now().date().isoformat(),
                                                 "source": "admin", "changes": row.note or "", "by": email})
        row.data = json.dumps(data, ensure_ascii=False)
        row.status = "published"
        row.published_at = _now()
        db.session.commit()
        refresh_tree(force=True)

    @app.route("/api/admin/hint-tree/publish", methods=["POST"])
    def api_hint_tree_publish():
        email = _admin_email()
        if not email:
            return _forbidden()
        body = request.get_json(silent=True) or {}
        row = HintTreeVersion.query.filter_by(version=str(body.get("version") or "")).first()
        if row is None:
            row = HintTreeVersion.query.filter_by(status="draft").order_by(HintTreeVersion.id.desc()).first()
        if row is None:
            return jsonify({"error": "Нет черновика"}), 400
        try:
            _publish(row, email)
        except Exception as exc:
            db.session.rollback()
            return jsonify({"error": f"Версия не прошла проверку: {exc}"[:200]}), 400
        return jsonify({"ok": True, "active": row.version})

    @app.route("/api/admin/hint-tree/rollback", methods=["POST"])
    def api_hint_tree_rollback():
        """Откат в один клик: снова опубликовать выбранную архивную версию."""
        email = _admin_email()
        if not email:
            return _forbidden()
        body = request.get_json(silent=True) or {}
        row = HintTreeVersion.query.filter_by(version=str(body.get("version") or "")).first()
        if row is None or row.status == "draft":
            return jsonify({"error": "Нет такой опубликованной версии"}), 400
        _publish(row, email)
        return jsonify({"ok": True, "active": row.version})

    @app.route("/api/admin/hint-tree/discard", methods=["POST"])
    def api_hint_tree_discard():
        if not _admin_email():
            return _forbidden()
        HintTreeVersion.query.filter_by(status="draft").delete(synchronize_session=False)
        db.session.commit()
        return jsonify({"ok": True})

    @app.route("/api/admin/hint-tree/sandbox", methods=["POST"])
    def api_hint_tree_sandbox():
        """Песочница: какую историю и какие подсказки увидит человек (по черновику, если он есть)."""
        if not _admin_email():
            return _forbidden()
        body = request.get_json(silent=True) or {}
        draft = HintTreeVersion.query.filter_by(status="draft").order_by(HintTreeVersion.id.desc()).first()
        t = HintTree(json.loads(draft.data)) if draft else HintTree(_active_data())
        text = str(body.get("text") or "")[:300]
        prof = str(body.get("profession") or "").upper() or None
        sid, score = t.match(text, None, prof)
        if not sid:
            node = t.match_out(text)
            return jsonify({"story": None, "score": round(score, 2), "out": node, "version": t.version})
        o = t.stories[sid]
        v, s = t.vec_of[sid]
        ctxs = {}
        hints0 = t.step_hints(sid, 0)
        for c in ("C0", "C1", "C2", "C3", "C4", "C6", "C7"):
            if c == "C0" or t.ctx_allowed(c, v["id"]):
                h, _ = t.apply_ctx(hints0, c, v["id"]) if c != "C0" else (hints0, "")
                ctxs[c] = h
        reactions = {}
        for rid in ("R01", "R02", "R03", "R07", "R08", "R10", "R11", "R14"):
            lf = t.leaf(sid, 0, rid)
            if lf:
                reactions[rid] = lf["hints"]
        return jsonify({"story": {"id": sid, "title": o["title"], "vector": v["id"], "sub": s["id"], "steps": o["steps"],
                                  "professions": o.get("professions") or [], "priority": o.get("priority")},
                        "score": round(score, 2), "contexts": ctxs, "reactions": reactions, "version": t.version,
                        "from_draft": bool(draft)})

    @app.route("/api/admin/hint-tree/export", methods=["GET"])
    def api_hint_tree_export():
        if not _admin_email():
            return _forbidden()
        ver = request.args.get("version")
        row = HintTreeVersion.query.filter_by(version=ver).first() if ver else None
        data = json.loads(row.data) if row else _active_data()
        return Response(json.dumps(data, ensure_ascii=False, indent=1), mimetype="application/json",
                        headers={"Content-Disposition": f"attachment; filename=hint_tree_v{data.get('version')}.json"})

    return {"HintTreeVersion": HintTreeVersion, "HintTreeEvent": HintTreeEvent, "refresh": refresh_tree}
