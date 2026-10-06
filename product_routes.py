"""Product API routes: jobs, balance, works, explore, settings, admin, robokassa."""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Optional

from flask import Response, g, jsonify, request, session, stream_with_context
from werkzeug.security import check_password_hash, generate_password_hash

import billing
import free_quota
import media_store
from assistant_rules import recommend as assistant_recommend
from pricing import PRICING_SEED, list_pricing_public, price_rub_media
from product_models import init_product_models
from robokassa import get_payment_provider
from security import ensure_csrf_token, rate_limit

HANDLE_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")
BANNED_HANDLES = {"admin", "support", "api", "explore", "settings", "balance", "account", "root", "ai", "shnica"}
CONTACT_NET_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")


def _parse_contacts_extra(raw: Any) -> list[dict[str, Any]]:
    if raw is None or raw == "":
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data[:24]:
        if not isinstance(item, dict):
            continue
        login = str(item.get("login") or "").strip()[:250]
        if not login:
            continue
        net = str(item.get("net") or "custom").strip().lower()[:32]
        if net != "custom" and not CONTACT_NET_RE.match(net):
            net = "custom"
        label = str(item.get("label") or "").strip()[:40]
        if net == "custom" and not label:
            label = "Соцсеть"
        row: dict[str, Any] = {"net": net, "login": login, "show": bool(item.get("show", True))}
        if label:
            row["label"] = label
        out.append(row)
    return out


def _dump_contacts_extra(items: Any) -> Optional[str]:
    normalized = _parse_contacts_extra(items)
    return json.dumps(normalized, ensure_ascii=False) if normalized else None


def register_product(app, db, User):
    models = init_product_models(db)
    Balance = models["Balance"]
    Ledger = models["Ledger"]
    CreatorProfile = models["CreatorProfile"]
    Work = models["Work"]
    FreeQuota = models["FreeQuota"]
    LoginCode = models["LoginCode"]
    Complaint = models["Complaint"]
    WorkLike = models["WorkLike"]
    Thread = models["Thread"]
    ThreadMessage = models["ThreadMessage"]
    AssistantMetric = models["AssistantMetric"]

    def current_user():
        uid = session.get("user_id")
        if not uid:
            return None
        return User.query.get(uid)

    def require_user(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                return jsonify({"error": "auth_required"}), 401
            return fn(user, *args, **kwargs)

        return wrapper

    def admin_emails():
        return {e.strip().lower() for e in (os.getenv("ADMIN_EMAILS") or "").split(",") if e.strip()}

    def require_admin(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user or (user.email or "").lower() not in admin_emails():
                return jsonify({"error": "forbidden"}), 403
            return fn(user, *args, **kwargs)

        return wrapper

    def profile_for(user_id: int):
        p = CreatorProfile.query.filter_by(user_id=user_id).first()
        if not p:
            p = CreatorProfile(user_id=user_id, referral_code=secrets.token_urlsafe(8)[:10])
            db.session.add(p)
            db.session.commit()
        return p

    def ensure_profile_schema():
        from sqlalchemy import inspect, text

        try:
            with app.app_context():
                insp = inspect(db.engine)
                if "creator_profiles" not in insp.get_table_names():
                    return
                cols = {c["name"] for c in insp.get_columns("creator_profiles")}
                if "contacts_extra" not in cols:
                    db.session.execute(text("ALTER TABLE creator_profiles ADD COLUMN contacts_extra TEXT"))
                    db.session.commit()
        except Exception:
            try:
                with app.app_context():
                    db.session.rollback()
            except Exception:
                pass

    ensure_profile_schema()

    def pricing_row(model_key: str):
        for row in PRICING_SEED:
            if row.model_key == model_key:
                return row
        return None

    def estimate_price_kop(model_key: str, params: dict) -> tuple[int, dict]:
        row = pricing_row(model_key)
        if not row or not row.enabled:
            raise ValueError("unknown_model")
        if row.is_free:
            return 0, {"model_key": model_key, "is_free": True}
        dur = int(params.get("duration_sec") or 5)
        if row.max_duration_sec:
            dur = min(dur, row.max_duration_sec)
        if row.unit == "per_second":
            per = price_rub_media(row.cost_usd, row.markup, row.unit)
            rub = per * max(1, dur)
        else:
            rub = price_rub_media(row.cost_usd, row.markup, row.unit)
        return int(rub * 100), {"model_key": model_key, "duration_sec": dur, "price_rub": rub}

    # --- enriched /api/auth/me (replaces auth.py handler) ---
    def api_me():
        ensure_csrf_token()
        user = current_user()
        if not user:
            return jsonify({"user": None, "balance_kop": 0})
        bal = billing.get_or_create_balance(db, Balance, user.id)
        prof = profile_for(user.id)
        fq = free_quota.get_quota(db, FreeQuota, user.id)
        return jsonify(
            {
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "name": user.name,
                    "provider": user.provider,
                    "handle": prof.handle,
                    "email_verified": bool(prof.email_verified),
                },
                "balance_kop": bal.balance_kop,
                "held_kop": bal.held_kop,
                "available_kop": billing.available_kop(bal),
                "free_left": free_quota.free_left(fq),
                "profile": {
                    "handle": prof.handle,
                    "display_name": prof.display_name or user.name,
                    "bio": prof.bio,
                    "telegram": prof.telegram,
                    "vk": prof.vk,
                    "website": prof.website,
                    "show_telegram": prof.show_telegram,
                    "show_vk": prof.show_vk,
                    "show_website": prof.show_website,
                    "show_email": prof.show_email,
                    "referral_code": prof.referral_code,
                    "avatar_url": prof.avatar_url,
                    "contacts_extra": _parse_contacts_extra(getattr(prof, "contacts_extra", None)),
                },
            }
        )

    app.view_functions["auth_me"] = api_me


    @app.post("/api/jobs/estimate")
    @require_user
    def api_jobs_estimate(user):
        data = request.get_json(silent=True) or {}
        model_key = (data.get("model_key") or "").strip()
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        try:
            price_kop, snap = estimate_price_kop(model_key, params)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        bal = billing.get_or_create_balance(db, Balance, user.id)
        return jsonify(
            {
                "price_kop": price_kop,
                "price_rub": price_kop / 100,
                "available_kop": billing.available_kop(bal),
                "enough": billing.available_kop(bal) >= price_kop,
                "snapshot": snap,
                "confirm_required": price_kop > 10000,
            }
        )

    @app.post("/api/jobs/start")
    @require_user
    def api_jobs_start(user):
        data = request.get_json(silent=True) or {}
        model_key = (data.get("model_key") or "").strip()
        prompt = str(data.get("prompt") or "").strip()
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        if not prompt:
            return jsonify({"error": "empty"}), 400
        try:
            price_kop, snap = estimate_price_kop(model_key, params)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if price_kop > 10000 and not data.get("confirm"):
            return jsonify({"error": "confirm_required", "price_kop": price_kop}), 402

        row = pricing_row(model_key)
        is_free = bool(row and row.is_free)
        job_id = secrets.token_hex(12)

        if is_free:
            prof = profile_for(user.id)
            if not prof.email_verified and (os.getenv("FLASK_ENV") or "").lower() == "production":
                return jsonify({"error": "email_unverified"}), 403
            fq = free_quota.get_quota(db, FreeQuota, user.id)
            if free_quota.free_left(fq) <= 0:
                return jsonify({"error": "free_limit"}), 429
            # capacity check
            r = getattr(g, "redis", None)
            if r is not None and free_quota.queue_len(r) >= free_quota.capacity_24h() and int(fq.lifetime_success or 0) > 0:
                return jsonify({"error": "free_queue_full"}), 429
            score = free_quota.priority_score(fq, 0)
            payload = {
                "job_id": job_id,
                "user_id": user.id,
                "model_key": model_key,
                "prompt": prompt,
                "params": params,
                "enqueued_at": time.time(),
                "score": score,
            }
            if r is not None:
                free_quota.enqueue_free(r, payload, score)
            # also store job meta in redis job key if possible
            try:
                from queue_runtime.jobs import set_job

                set_job(job_id, status="queued_free", user_id=user.id, model_key=model_key, prompt=prompt, price_kop=0, is_free=True)
            except Exception:
                pass
            work = Work(
                owner_id=user.id,
                kind="video",
                model_key=model_key,
                prompt=prompt,
                params=json.dumps(params, ensure_ascii=False),
                status="draft",
                job_id=job_id,
            )
            db.session.add(work)
            db.session.commit()
            return jsonify({"job_id": job_id, "status": "queued_free", "work_id": work.id, "price_kop": 0, "queue": True})

        # paid path
        try:
            billing.hold(db, Balance, Ledger, user_id=user.id, amount_kop=price_kop, job_id=job_id, model_key=model_key, snapshot=snap)
        except billing.InsufficientFunds as exc:
            return jsonify({"error": "insufficient_funds", "need_kop": exc.need_kop, "have_kop": exc.have_kop}), 402

        # Prefer existing generate queue when model maps to integrated catalog
        status = "held"
        job_id_out = job_id
        stub_url = "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1200&q=80"
        allow_stub = (os.getenv("ALLOW_STUB_GEN") or "1").strip().lower() in {"1", "true", "yes"}
        try:
            from queue_runtime.jobs import enqueue_inbound, set_job, publish_result

            integrated = app.config.get("INTEGRATED_MODELS") or {}
            integrated_id = model_key if model_key in integrated else None
            if not integrated_id and "wan" in model_key and "wan-3-0" in integrated:
                integrated_id = "wan-3-0"

            if integrated_id:
                spec = integrated[integrated_id]
                fields_fn = app.config.get("GENERATE_JOB_FIELDS")
                gen_fields = fields_fn(integrated_id, prompt) if callable(fields_fn) else None
                if not gen_fields:
                    gen_fields = {
                        "model_id": integrated_id,
                        "provider": spec.get("provider"),
                    }
                inbound_id = enqueue_inbound(
                    {
                        **gen_fields,
                        "prompt": prompt,
                        "user_id": user.id,
                        "owner_id": user.id,
                        "price_kop": price_kop,
                        "billing_job_id": job_id,
                    }
                )
                set_job(inbound_id, billing_job_id=job_id, status="queued")
                job_id_out = inbound_id
                status = "queued"
            else:
                set_job(job_id, status="queued", user_id=user.id, model_key=model_key, prompt=prompt, price_kop=price_kop)
                if allow_stub:
                    publish_result(
                        job_id,
                        {
                            "ok": True,
                            "status": "succeeded",
                            "output": stub_url,
                            "kind": "image",
                        },
                    )
                    billing.capture(db, Balance, Ledger, user_id=user.id, amount_kop=price_kop, job_id=job_id, model_key=model_key)
                    status = "succeeded"
        except Exception as exc:  # noqa: BLE001
            if allow_stub:
                # Local/dev without Redis: succeed immediately and capture hold
                try:
                    billing.capture(db, Balance, Ledger, user_id=user.id, amount_kop=price_kop, job_id=job_id, model_key=model_key)
                    status = "succeeded"
                    # Best-effort in-process job meta for SSE polling fallback
                    app.extensions.setdefault("stub_jobs", {})[job_id] = {
                        "id": job_id,
                        "status": "succeeded",
                        "output": stub_url,
                        "ok": True,
                    }
                except Exception:
                    billing.release(db, Balance, Ledger, user_id=user.id, amount_kop=price_kop, job_id=job_id, model_key=model_key)
                    return jsonify({"error": "queue_unavailable", "detail": str(exc)}), 503
            else:
                billing.release(db, Balance, Ledger, user_id=user.id, amount_kop=price_kop, job_id=job_id, model_key=model_key)
                return jsonify({"error": "queue_unavailable", "detail": str(exc)}), 503

        kind = (row.category if row else "image")
        if kind == "tool":
            kind = "image"
        work = Work(
            owner_id=user.id,
            kind=kind if kind in {"video", "image", "audio", "text"} else "image",
            model_key=model_key,
            prompt=prompt,
            params=json.dumps(params, ensure_ascii=False),
            status="draft",
            job_id=job_id_out,
        )
        if status == "succeeded":
            work.original_url = stub_url
            work.thumb_url = work.original_url
        db.session.add(work)
        db.session.commit()
        return jsonify(
            {
                "job_id": work.job_id,
                "status": status,
                "work_id": work.id,
                "price_kop": price_kop,
            }
        )

    @app.get("/api/jobs/<job_id>")
    @require_user
    def api_jobs_get(user, job_id):
        try:
            from queue_runtime.jobs import generate_job_public, get_job

            generate_job_public(job_id)
            job = get_job(job_id) or {}
        except Exception:
            job = {}
        if not job:
            job = (app.extensions.get("stub_jobs") or {}).get(job_id) or {}
        work = Work.query.filter_by(job_id=job_id, owner_id=user.id).first()
        return jsonify({"job": job, "work": _work_public(work, owner_view=True) if work else None})

    @app.get("/api/jobs/stream")
    @require_user
    def api_jobs_stream(user):
        job_id = (request.args.get("id") or "").strip()
        if not job_id:
            return jsonify({"error": "id_required"}), 400

        @stream_with_context
        def gen():
            from queue_runtime.jobs import generate_job_public, get_job

            yield "retry: 3000\n\n"
            for _ in range(8):
                job = {}
                try:
                    generate_job_public(job_id)
                    job = get_job(job_id) or {}
                except Exception:
                    job = {}
                if not job:
                    job = (app.extensions.get("stub_jobs") or {}).get(job_id) or {"status": "unknown"}
                work = Work.query.filter_by(job_id=job_id, owner_id=user.id).first()
                payload = {"job": job, "work": _work_public(work, owner_view=True) if work else None}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                st = (job or {}).get("status")
                if st in {"succeeded", "failed", "error"}:
                    break
                time.sleep(3)

        return Response(gen(), mimetype="text/event-stream")

    def _viewer_liked(work_id: int, viewer_id: Optional[int] = None) -> bool:
        if viewer_id:
            return WorkLike.query.filter_by(work_id=work_id, user_id=viewer_id).first() is not None
        liked_ids = session.get("liked_works") or []
        try:
            return int(work_id) in {int(x) for x in liked_ids}
        except Exception:
            return False

    def _work_public(work: Work, owner_view: bool = False, viewer_id: Optional[int] = None):
        if not work:
            return None
        url = work.original_url if owner_view and work.owner_id == (viewer_id or work.owner_id) else (work.watermarked_url or work.original_url)
        if owner_view:
            url = work.original_url or work.watermarked_url
        prof = CreatorProfile.query.filter_by(user_id=work.owner_id).first()
        owner_user = User.query.get(work.owner_id) if work.owner_id else None
        return {
            "id": work.id,
            "kind": work.kind,
            "model_key": work.model_key,
            "prompt": work.prompt,
            "status": work.status,
            "title": work.title,
            "tags": (work.tags or "").split(",") if work.tags else [],
            "thumb_url": work.thumb_url or work.watermarked_url or work.original_url,
            "media_url": media_store.presign(url) if url else None,
            "downloads": work.downloads,
            "likes": int(work.likes or 0),
            "liked": _viewer_liked(work.id, viewer_id),
            "published_at": work.published_at.isoformat() if work.published_at else None,
            "owner_id": work.owner_id,
            "owner_handle": (prof.handle if prof else None),
            "owner_name": (prof.display_name if prof and prof.display_name else None)
            or (owner_user.name if owner_user and owner_user.name else None)
            or (owner_user.email.split("@")[0] if owner_user and owner_user.email else None),
        }

    @app.get("/api/works/mine")
    @require_user
    def api_works_mine(user):
        rows = Work.query.filter_by(owner_id=user.id).order_by(Work.created_at.desc()).limit(100).all()
        return jsonify({"items": [_work_public(w, owner_view=True, viewer_id=user.id) for w in rows]})

    @app.post("/api/works/<int:work_id>/save")
    @require_user
    def api_works_save(user, work_id):
        work = Work.query.filter_by(id=work_id, owner_id=user.id).first()
        if not work:
            return jsonify({"error": "not_found"}), 404
        if work.status == "draft":
            work.status = "saved"
            db.session.commit()
        return jsonify({"ok": True, "work": _work_public(work, owner_view=True, viewer_id=user.id)})

    @app.post("/api/works/<int:work_id>/unpublish")
    @require_user
    def api_works_unpublish(user, work_id):
        work = Work.query.filter_by(id=work_id, owner_id=user.id).first()
        if not work:
            return jsonify({"error": "not_found"}), 404
        if work.status == "published":
            work.status = "saved"
            db.session.commit()
        return jsonify({"ok": True, "work": _work_public(work, owner_view=True, viewer_id=user.id)})

    @app.post("/api/works/<int:work_id>/publish")
    @require_user
    def api_works_publish(user, work_id):
        work = Work.query.filter_by(id=work_id, owner_id=user.id).first()
        if not work:
            return jsonify({"error": "not_found"}), 404
        data = request.get_json(silent=True) or {}
        if not data.get("agree_rules"):
            return jsonify({"error": "agree_required"}), 400
        prof = profile_for(user.id)
        if not prof.handle:
            return jsonify({"error": "handle_required"}), 400
        title = str(data.get("title") or "").strip()[:200]
        tags = data.get("tags") if isinstance(data.get("tags"), list) else []
        tags = [str(t).strip()[:32] for t in tags[:5] if str(t).strip()]
        # stop-words light filter
        bad = re.search(r"(убий|террор|porn|порно|suicide)", f"{title} {work.prompt}", re.I)
        if bad:
            return jsonify({"error": "moderation"}), 400
        # watermark
        if work.original_url and work.kind in {"image", "video"}:
            try:
                raw = media_store.download_url_to_bytes(work.original_url)
                if raw and work.kind == "image":
                    wm = media_store.watermark_image(raw, prof.handle)
                    key = f"works/{user.id}/{work.id}_wm.jpg"
                    work.watermarked_url = media_store.upload_bytes(key, wm, "image/jpeg")
                    work.thumb_url = work.watermarked_url
                elif work.kind == "video":
                    # keep original as watermarked fallback until worker ffmpeg
                    work.watermarked_url = work.watermarked_url or work.original_url
            except Exception:
                work.watermarked_url = work.watermarked_url or work.original_url
        work.title = title or (work.prompt[:80] if work.prompt else f"Работа {work.id}")
        work.tags = ",".join(tags)
        work.status = "published"
        work.published_at = datetime.utcnow()
        db.session.commit()
        fq = free_quota.get_quota(db, FreeQuota, user.id)
        free_quota.grant_publish_bonus(db, fq)
        return jsonify({"ok": True, "work": _work_public(work, owner_view=True, viewer_id=user.id)})

    @app.get("/api/explore")
    def api_explore():
        kind = (request.args.get("kind") or "").strip()
        sort = (request.args.get("sort") or "new").strip()
        q = Work.query.filter_by(status="published")
        if kind in {"video", "image", "audio", "text"}:
            q = q.filter_by(kind=kind)
        if sort in {"popular", "top"}:
            q = q.order_by(Work.likes.desc(), Work.downloads.desc())
        else:
            q = q.order_by(Work.published_at.desc())
        rows = q.limit(60).all()
        viewer = current_user()
        return jsonify(
            {
                "items": [
                    _work_public(w, owner_view=False, viewer_id=viewer.id if viewer else None) for w in rows
                ]
            }
        )

    @app.get("/api/works/<int:work_id>")
    def api_work_get(work_id):
        work = Work.query.get(work_id)
        if not work or (work.status != "published" and (not current_user() or current_user().id != work.owner_id)):
            return jsonify({"error": "not_found"}), 404
        viewer = current_user()
        owner_view = bool(viewer and viewer.id == work.owner_id)
        return jsonify({"work": _work_public(work, owner_view=owner_view, viewer_id=viewer.id if viewer else None)})

    @app.post("/api/works/<int:work_id>/like")
    @rate_limit(40, 60, "work_like")
    def api_work_like(work_id):
        """Toggle like for any published generation (video/image/audio/text)."""
        work = Work.query.filter_by(id=work_id, status="published").first()
        if not work:
            return jsonify({"error": "not_found"}), 404
        user = current_user()
        liked = False
        if user:
            row = WorkLike.query.filter_by(work_id=work_id, user_id=user.id).first()
            if row:
                db.session.delete(row)
                work.likes = max(0, int(work.likes or 0) - 1)
                liked = False
            else:
                db.session.add(WorkLike(work_id=work_id, user_id=user.id))
                work.likes = int(work.likes or 0) + 1
                liked = True
        else:
            liked_ids = [int(x) for x in (session.get("liked_works") or []) if str(x).isdigit()]
            if work_id in liked_ids:
                liked_ids = [x for x in liked_ids if x != work_id]
                work.likes = max(0, int(work.likes or 0) - 1)
                liked = False
            else:
                liked_ids.append(work_id)
                work.likes = int(work.likes or 0) + 1
                liked = True
            session["liked_works"] = liked_ids
            session.modified = True
        db.session.commit()
        return jsonify({"likes": int(work.likes or 0), "liked": liked})

    @app.post("/api/works/<int:work_id>/complaint")
    def api_work_complaint(work_id):
        work = Work.query.get(work_id)
        if not work:
            return jsonify({"error": "not_found"}), 404
        data = request.get_json(silent=True) or {}
        reason = str(data.get("reason") or "").strip()
        if len(reason) < 5:
            return jsonify({"error": "reason_required"}), 400
        viewer = current_user()
        db.session.add(Complaint(work_id=work_id, reporter_id=viewer.id if viewer else None, reason=reason[:1000]))
        db.session.commit()
        return jsonify({"ok": True})

    @app.get("/api/creators/<handle>")
    def api_creator(handle):
        prof = CreatorProfile.query.filter_by(handle=handle).first()
        if not prof:
            return jsonify({"error": "not_found"}), 404
        user = User.query.get(prof.user_id)
        works = (
            Work.query.filter_by(owner_id=prof.user_id, status="published")
            .order_by(Work.published_at.desc())
            .limit(60)
            .all()
        )
        contacts = {}
        if prof.show_telegram and prof.telegram:
            contacts["telegram"] = prof.telegram
        if prof.show_vk and prof.vk:
            contacts["vk"] = prof.vk
        if prof.show_website and prof.website:
            contacts["website"] = prof.website
        if prof.show_email and user:
            contacts["email"] = user.email
        extra_public = []
        for item in _parse_contacts_extra(getattr(prof, "contacts_extra", None)):
            if not item.get("show"):
                continue
            extra_public.append(item)
        viewer = current_user()
        return jsonify(
            {
                "handle": prof.handle,
                "display_name": prof.display_name or (user.name if user else handle),
                "bio": prof.bio,
                "avatar_url": prof.avatar_url,
                "contacts": contacts,
                "contacts_extra": extra_public,
                "works": [
                    _work_public(w, owner_view=False, viewer_id=viewer.id if viewer else None)
                    for w in works
                ],
            }
        )

    @app.post("/api/settings/profile")
    @require_user
    def api_settings_profile(user):
        data = request.get_json(silent=True) or {}
        prof = profile_for(user.id)
        handle = str(data.get("handle") or "").strip()
        if handle:
            if not HANDLE_RE.match(handle) or handle.lower() in BANNED_HANDLES:
                return jsonify({"error": "bad_handle"}), 400
            other = CreatorProfile.query.filter_by(handle=handle).first()
            if other and other.user_id != user.id:
                return jsonify({"error": "handle_taken"}), 409
            prof.handle = handle
        if "display_name" in data:
            prof.display_name = str(data.get("display_name") or "")[:120]
        if "bio" in data:
            prof.bio = str(data.get("bio") or "")[:160]
        for field in ("telegram", "vk", "website"):
            if field in data:
                setattr(prof, field, str(data.get(field) or "")[:250] or None)
        for field in ("show_telegram", "show_vk", "show_website", "show_email"):
            if field in data:
                setattr(prof, field, bool(data.get(field)))
        if "contacts_extra" in data:
            prof.contacts_extra = _dump_contacts_extra(data.get("contacts_extra"))
        if data.get("consent_152"):
            prof.consent_152 = True
        db.session.commit()
        return jsonify({"ok": True})

    @app.post("/api/me/avatar")
    @require_user
    @rate_limit(10, 60, "avatar_up")
    def api_me_avatar(user):
        f = request.files.get("file") or request.files.get("avatar")
        if not f or not f.filename:
            return jsonify({"error": "no_file"}), 400
        raw = f.read()
        if not raw:
            return jsonify({"error": "empty"}), 400
        if len(raw) > 10 * 1024 * 1024:
            return jsonify({"error": "too_large"}), 400
        ctype = (f.mimetype or "").lower().split(";")[0].strip()
        name = (f.filename or "").lower()
        ok_ext = name.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))
        # browsers sometimes send empty / octet-stream for canvas blobs
        if ctype not in {"image/jpeg", "image/png", "image/webp", "image/gif", "image/jpg"} and not (
            ok_ext or ctype in {"", "application/octet-stream"}
        ):
            return jsonify({"error": "bad_type"}), 400
        try:
            from PIL import Image
            im = Image.open(__import__("io").BytesIO(raw)).convert("RGB")
            im.thumbnail((400, 400))
            side = 400
            canvas = Image.new("RGB", (side, side), (30, 18, 56))
            x = (side - im.width) // 2
            y = (side - im.height) // 2
            canvas.paste(im, (x, y))
            buf = __import__("io").BytesIO()
            canvas.save(buf, format="JPEG", quality=86)
            data = buf.getvalue()
        except Exception:
            app.logger.exception("avatar decode failed")
            return jsonify({"error": "bad_image"}), 400
        key = f"avatars/{user.id}/{int(time.time())}.jpg"
        try:
            stored = media_store.upload_bytes(key, data, "image/jpeg")
        except Exception:
            app.logger.exception("avatar upload failed")
            return jsonify({"error": "upload_failed"}), 502
        # Keep durable path in DB (not a short-lived presigned URL)
        durable = stored if stored.startswith(("/media/", "s3://")) else stored
        public = media_store.presign(stored) if stored.startswith("s3://") else stored
        try:
            prof = profile_for(user.id)
            prof.avatar_url = durable[:500]
            db.session.commit()
        except Exception:
            app.logger.exception("avatar profile save failed")
            db.session.rollback()
            return jsonify({"error": "save_failed"}), 500
        return jsonify({"ok": True, "url": public})

    @app.delete("/api/me/avatar")
    @require_user
    def api_me_avatar_delete(user):
        prof = profile_for(user.id)
        prof.avatar_url = None
        db.session.commit()
        return jsonify({"ok": True})

    @app.post("/api/auth/email-code/request")
    @rate_limit(5, 60, "email_code")
    def api_email_code_request():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email") or "").strip().lower()
        if "@" not in email:
            return jsonify({"error": "invalid_email"}), 400
        if not data.get("consent_152"):
            return jsonify({"error": "consent_required"}), 400
        code = f"{secrets.randbelow(1000000):06d}"
        from mailer import send_login_code, smtp_configured

        is_prod = (os.getenv("FLASK_ENV") or "development") == "production"
        testing = bool(app.config.get("TESTING"))
        use_smtp = smtp_configured() and not testing

        if use_smtp:
            try:
                send_login_code(email, code)
            except Exception:
                app.logger.exception("email code send failed for %s", email)
                return jsonify({"error": "send_failed"}), 502
        elif is_prod:
            app.logger.error("SMTP not configured in production")
            return jsonify({"error": "send_failed"}), 503
        elif not testing:
            # SMTP not set up: refuse to pretend the letter was sent
            app.logger.error("SMTP not configured — refuse email-code request")
            return jsonify({"error": "send_failed"}), 503

        row = LoginCode(
            email=email,
            code_hash=generate_password_hash(code),
            expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
        db.session.add(row)
        db.session.commit()
        payload = {"ok": True}
        # Tests only: return code so pytest can verify login without SMTP
        if testing:
            payload["dev_code"] = code
        elif not use_smtp:
            app.logger.info("[mail] login code generated for %s (no SMTP)", email)
        return jsonify(payload)

    @app.post("/api/auth/email-code/verify")
    @rate_limit(10, 60, "email_verify")
    def api_email_code_verify():
        data = request.get_json(silent=True) or {}
        email = str(data.get("email") or "").strip().lower()
        code = str(data.get("code") or "").strip()
        row = (
            LoginCode.query.filter_by(email=email)
            .order_by(LoginCode.created_at.desc())
            .first()
        )
        if not row or row.expires_at < datetime.utcnow():
            return jsonify({"error": "expired"}), 400
        if int(row.attempts or 0) >= 5:
            return jsonify({"error": "too_many_attempts"}), 429
        row.attempts = int(row.attempts or 0) + 1
        db.session.commit()
        if not check_password_hash(row.code_hash, code):
            return jsonify({"error": "invalid_code"}), 401
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email, provider="email_code", provider_id=email, name=email.split("@")[0], password_hash=None)
            db.session.add(user)
            db.session.commit()
        session["user_id"] = user.id
        prof = profile_for(user.id)
        prof.email_verified = True
        prof.consent_152 = True
        db.session.commit()
        return jsonify({"user": {"id": user.id, "email": user.email, "name": user.name}})

    @app.get("/api/balance")
    @require_user
    def api_balance(user):
        bal = billing.get_or_create_balance(db, Balance, user.id)
        entries = (
            Ledger.query.filter_by(user_id=user.id).order_by(Ledger.created_at.desc()).limit(50).all()
        )
        return jsonify(
            {
                "balance_kop": bal.balance_kop,
                "held_kop": bal.held_kop,
                "available_kop": billing.available_kop(bal),
                "ledger": [
                    {
                        "id": e.id,
                        "kind": e.kind,
                        "amount_kop": e.amount_kop,
                        "model_key": e.model_key,
                        "job_id": e.job_id,
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                    }
                    for e in entries
                ],
            }
        )

    @app.post("/api/balance/topup")
    @require_user
    def api_balance_topup(user):
        data = request.get_json(silent=True) or {}
        amount_rub = int(data.get("amount_rub") or 0)
        if amount_rub < 100:
            return jsonify({"error": "min_100"}), 400
        provider = get_payment_provider()
        if not provider.configured():
            # Dev stub credit
            if (os.getenv("FLASK_ENV") or "development") != "production":
                inv = f"dev{int(time.time())}{user.id}"
                billing.topup(
                    db,
                    Balance,
                    Ledger,
                    user_id=user.id,
                    amount_kop=amount_rub * 100,
                    idempotency_key=f"topup:{inv}",
                    meta={"stub": True},
                )
                return jsonify({"ok": True, "stub": True, "balance_kop": billing.get_or_create_balance(db, Balance, user.id).balance_kop})
            return jsonify({"error": "payments_not_configured"}), 503
        inv = str(int(time.time()))[-6:] + str(user.id)
        # store mapping inv→user in redis/session ledger pending via idempotency later
        session[f"topup_inv_{inv}"] = user.id
        start = provider.start_topup(
            user_id=user.id,
            amount_kop=amount_rub * 100,
            inv_id=inv,
            description="Доступ к сервису генерации контента",
        )
        return jsonify({"pay_url": start.pay_url, "inv_id": start.inv_id})

    @app.post("/api/payments/robokassa/result")
    def api_robokassa_result():
        form = request.form.to_dict() or (request.get_json(silent=True) or {})
        provider = get_payment_provider()
        try:
            verified = provider.verify_result(form)
        except Exception:
            return "bad sign", 400
        inv = verified["inv_id"]
        user_id = session.get(f"topup_inv_{inv}")
        # also allow InvId encoding user
        if not user_id:
            # fallback: last digits after timestamp are user id — best-effort
            try:
                user_id = int(str(inv)[6:])
            except Exception:
                return "bad inv", 400
        billing.topup(
            db,
            Balance,
            Ledger,
            user_id=int(user_id),
            amount_kop=verified["amount_kop"],
            idempotency_key=f"topup:{inv}",
            meta={"provider": "robokassa", "inv_id": inv},
        )
        return f"OK{inv}"

    @app.get("/api/admin/overview")
    @require_admin
    def api_admin_overview(user):
        r = getattr(g, "redis", None)
        qlen = free_quota.queue_len(r) if r is not None else 0
        pause = 0
        if r is not None:
            try:
                pause = float(r.get(free_quota.FREE_PAUSE_KEY) or 0)
            except Exception:
                pause = 0
        from pricing import get_usd_rub_rate

        rate, stale = get_usd_rub_rate()
        complaints = Complaint.query.filter_by(status="open").count()
        metrics = AssistantMetric.query.order_by(AssistantMetric.day_key.desc()).limit(7).all()
        return jsonify(
            {
                "usd_rub_rate": rate,
                "rate_stale": stale,
                "free_queue_len": qlen,
                "free_capacity_24h": free_quota.capacity_24h(),
                "free_paused_until": pause,
                "open_complaints": complaints,
                "assistant_metrics": [
                    {"day": m.day_key, "total": m.total, "without_llm": m.without_llm} for m in metrics
                ],
            }
        )

    @app.get("/api/jobs/<job_id>/queue")
    @require_user
    def api_jobs_queue(user, job_id):
        r = getattr(g, "redis", None)
        pos = free_quota.queue_position(r, job_id) if r is not None else 0
        qlen = free_quota.queue_len(r) if r is not None else 0
        eta_min = pos * 10 if pos else 0
        paid = None
        for key in ("bytedance/seedance-2.0-mini", "bytedance/seedance-2.0", "alibaba/wan-3"):
            row = pricing_row(key)
            if row and row.enabled and not row.is_free:
                rub = price_rub_media(row.cost_usd, row.markup, row.unit)
                if row.unit == "per_second":
                    rub = rub * 5
                label = row.version_label or row.model_key
                paid = {"model_key": row.model_key, "price_rub": rub, "label": f"{label} за {rub} ₽"}
                break
        return jsonify({"position": pos, "queue_len": qlen, "eta_min": eta_min, "paid_alt": paid})

    @app.post("/api/admin/complaints/<int:cid>/hide")
    @require_admin
    def api_admin_hide(user, cid):
        c = Complaint.query.get(cid)
        if not c:
            return jsonify({"error": "not_found"}), 404
        work = Work.query.get(c.work_id)
        if work:
            work.status = "hidden"
        c.status = "resolved"
        db.session.commit()
        return jsonify({"ok": True})

    @app.post("/api/admin/complaints/<int:cid>/restore")
    @require_admin
    def api_admin_restore(user, cid):
        c = Complaint.query.get(cid)
        if not c:
            return jsonify({"error": "not_found"}), 404
        work = Work.query.get(c.work_id)
        if work and work.status == "hidden":
            work.status = "published"
        c.status = "dismissed"
        db.session.commit()
        return jsonify({"ok": True})

    @app.get("/api/admin/complaints")
    @require_admin
    def api_admin_complaints(user):
        rows = Complaint.query.filter_by(status="open").order_by(Complaint.created_at.desc()).limit(50).all()
        return jsonify(
            {
                "items": [
                    {
                        "id": c.id,
                        "work_id": c.work_id,
                        "reason": c.reason,
                        "created_at": c.created_at.isoformat() if c.created_at else None,
                    }
                    for c in rows
                ]
            }
        )

    @app.get("/api/admin/report")
    @require_admin
    def api_admin_report(user):
        # Simple revenue from capture ledger entries
        from sqlalchemy import func

        captures = (
            Ledger.query.filter_by(kind="capture")
            .with_entities(Ledger.model_key, func.sum(Ledger.amount_kop), func.count())
            .group_by(Ledger.model_key)
            .all()
        )
        items = []
        for model_key, amount_sum, cnt in captures:
            revenue_kop = abs(int(amount_sum or 0))
            row = pricing_row(model_key or "")
            cost_rub = 0.0
            if row and not row.is_free:
                # rough: revenue / markup / 1.30 ≈ cost in rub
                cost_rub = (revenue_kop / 100) / max(1.5, float(row.markup or 2)) / 1.30
            margin = 0.0
            if revenue_kop:
                margin = 1.0 - (cost_rub / (revenue_kop / 100))
            items.append(
                {
                    "model_key": model_key,
                    "revenue_kop": revenue_kop,
                    "jobs": int(cnt or 0),
                    "est_cost_rub": round(cost_rub, 2),
                    "margin": round(margin, 3),
                    "low_margin": margin < 0.30,
                }
            )
        return jsonify({"items": items})

    # --- internal chat / threads ---
    KIND_LABEL = {"prompt": "промпт", "original": "оригинал", "order": "заказ", "assistant": "помощник"}

    ASSISTANT_HELP = [
        (re.compile(r"баланс|пополн|оплат|деньг|руб|сбп|карт", re.I),
         "Баланс нужен для генераций в Студии. Откройте вкладку «Баланс», выберите сумму от 100 ₽ и нажмите «Пополнить»."),
        (re.compile(r"студи|генерац|модел|seedance|kling|seedream|создать|сгенер", re.I),
         "Студия — раздел в шапке: выбираете модель, задаёте промпт и запускаете генерацию. Списание только за готовый результат."),
        (re.compile(r"витрин|опублик|explore|подборк", re.I),
         "Витрина — публичная лента работ. После генерации можно опубликовать работу; во вкладке «Работы» видно статус."),
        (re.compile(r"чат|сообщен|диалог|запрос|промпт|оригинал|заказ", re.I),
         "Во вкладке «Чат» — помощник и переписка по запросам клиентов. Отвечайте прямо в {AI}-шнице."),
        (re.compile(r"профиль|ник|контакт|фото|о себе|кабинет|заполн", re.I),
         "Вкладка «Профиль» — имя, ник, описание, фото и контакты. Можно заполнить вручную или спросить меня здесь."),
        (re.compile(r"лайк|сердеч", re.I),
         "Лайки ставят на витрине. В шапке кабинета видно сумму лайков по вашим работам."),
        (re.compile(r"помощ|что умеешь|как польз|справка|help|faq", re.I),
         "Я первый чат у каждого: помогаю с профилем и отвечаю про Студию, Витрину, баланс и чаты."),
    ]

    def _assistant_reply(text: str) -> str:
        for rx, ans in ASSISTANT_HELP:
            if rx.search(text or ""):
                return ans
        return "Могу подсказать про баланс, Студию, Витрину, чат и профиль. Спросите своими словами."

    def _ensure_assistant_thread(user) -> Thread:
        th = (
            Thread.query.filter_by(kind="assistant", buyer_id=user.id)
            .order_by(Thread.id.asc())
            .first()
        )
        if th:
            return th
        th = Thread(
            kind="assistant",
            work_id=None,
            buyer_id=user.id,
            seller_id=user.id,
            status="answered",
        )
        db.session.add(th)
        db.session.flush()
        db.session.add(
            ThreadMessage(
                thread_id=th.id,
                sender_id=None,
                text="Привет! Я помощник {AI}-шницы — всегда первый чат в списке. Помогу заполнить профиль или отвечу про Студию, Витрину, баланс и чаты. О чём спросить?",
                read_by_buyer=False,
                read_by_seller=True,
            )
        )
        db.session.commit()
        return th

    def _peer_card(user_id: int) -> dict:
        u = User.query.get(user_id)
        prof = CreatorProfile.query.filter_by(user_id=user_id).first()
        name = (prof.display_name if prof and prof.display_name else None) or (u.name if u else None) or (u.email.split("@")[0] if u and u.email else "Пользователь")
        return {"name": name, "grad": "#8A66FF,#5B35E0", "handle": prof.handle if prof else None}

    def _thread_payload(th: Thread, viewer_id: int) -> dict:
        if th.kind == "assistant":
            peer = {"name": "{AI}-шница", "grad": "#FFA235,#F2668B", "handle": None, "assistant": True}
        else:
            peer_id = th.seller_id if viewer_id == th.buyer_id else th.buyer_id
            peer = _peer_card(peer_id)
        msgs = (
            ThreadMessage.query.filter_by(thread_id=th.id)
            .order_by(ThreadMessage.created_at.asc())
            .limit(200)
            .all()
        )
        unread = 0
        for m in msgs:
            if m.is_system:
                continue
            if viewer_id == th.buyer_id and not m.read_by_buyer and m.sender_id != viewer_id:
                unread += 1
            if viewer_id == th.seller_id and not m.read_by_seller and m.sender_id != viewer_id:
                unread += 1
        work_card = None
        if th.work_id:
            w = Work.query.get(th.work_id)
            if w:
                work_card = {
                    "title": w.title or w.model_key or "Работа",
                    "src": w.thumb_url or w.watermarked_url or w.original_url or "/assets/bg-light.jpg",
                }
        out_msgs = []
        for m in msgs:
            if m.is_system:
                out_msgs.append({"sys": m.text or "", "ts": int((m.created_at or datetime.utcnow()).timestamp() * 1000)})
                continue
            item = {
                "from": "me" if m.sender_id == viewer_id else "them",
                "text": m.text or "",
                "ts": int((m.created_at or datetime.utcnow()).timestamp() * 1000),
                "read": bool(m.read_by_buyer and m.read_by_seller) if m.sender_id == viewer_id else False,
            }
            if m.prompt:
                item["prompt"] = m.prompt
            if m.file_name:
                item["file"] = {"name": m.file_name, "size": m.file_size or ""}
            out_msgs.append(item)
        role = "assistant" if th.kind == "assistant" else ("buyer" if viewer_id == th.buyer_id else "seller")
        return {
            "id": str(th.id),
            "with": peer,
            "kind": th.kind,
            "role": role,
            "work": work_card,
            "status": "answered" if th.status == "answered" else "new",
            "unread": unread,
            "msgs": out_msgs,
        }

    @app.get("/api/threads")
    @require_user
    def api_threads_list(user):
        _ensure_assistant_thread(user)
        filt = str(request.args.get("filter") or "all")
        rows = (
            Thread.query.filter((Thread.buyer_id == user.id) | (Thread.seller_id == user.id))
            .order_by(Thread.updated_at.desc())
            .limit(100)
            .all()
        )
        # assistant always first
        rows = sorted(rows, key=lambda t: (0 if t.kind == "assistant" else 1, -(t.updated_at.timestamp() if t.updated_at else 0)))
        items = [_thread_payload(t, user.id) for t in rows]
        if filt == "unread":
            items = [i for i in items if i["unread"]]
        elif filt == "assistant":
            items = [i for i in items if i["kind"] == "assistant"]
        elif filt in {"prompt", "original", "order"}:
            items = [i for i in items if i["kind"] == filt]
        return jsonify({"items": items})

    @app.get("/api/threads/unread")
    @require_user
    def api_threads_unread(user):
        rows = Thread.query.filter((Thread.buyer_id == user.id) | (Thread.seller_id == user.id)).all()
        total = sum(_thread_payload(t, user.id)["unread"] for t in rows)
        return jsonify({"unread": total})

    def _resolve_seller_id(creator: str, creator_name: str = "") -> Optional[int]:
        """Find seller by handle / numeric id, or provision a demo seller for showcase creators."""
        raw = str(creator or "").strip()
        if not raw:
            return None
        handle = raw.lstrip("@").strip()[:32]
        if not handle:
            return None
        prof = CreatorProfile.query.filter_by(handle=handle).first()
        if prof:
            return prof.user_id
        if handle.isdigit():
            return int(handle)
        # Showcase/demo creators (c3, zheltok_demo, …) — create a shadow seller so chat works
        safe = re.sub(r"[^a-zA-Z0-9_]", "", handle).lower()[:24] or f"c{abs(hash(handle)) % 100000}"
        email = f"demo+{safe}@aishnitsa.local"
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(
                email=email,
                name=(creator_name or handle)[:200],
                provider="demo",
                provider_id=safe,
                password_hash=None,
            )
            db.session.add(u)
            db.session.flush()
        prof = profile_for(u.id)
        if not prof.handle:
            taken = CreatorProfile.query.filter_by(handle=safe).first()
            prof.handle = safe if not taken or taken.user_id == u.id else f"{safe[:18]}_{u.id}"[:24]
            if creator_name:
                prof.display_name = str(creator_name)[:120]
            elif not prof.display_name:
                prof.display_name = handle[:120]
            db.session.commit()
        return u.id

    @app.post("/api/threads")
    @require_user
    @rate_limit(20, 60, "threads_create")
    def api_threads_create(user):
        data = request.get_json(silent=True) or {}
        kind = str(data.get("kind") or "prompt").strip()
        if kind == "custom":
            kind = "order"
        if kind not in {"prompt", "original", "order"}:
            return jsonify({"error": "bad_kind"}), 400
        work_id = data.get("workId") or data.get("work_id")
        work = None
        seller_id = None
        if work_id not in (None, ""):
            try:
                work = Work.query.get(int(work_id))
            except (TypeError, ValueError):
                # demo string ids like w01 — resolve owner by creator handle later
                work = None
            if work:
                seller_id = work.owner_id
        if not seller_id:
            creator = str(data.get("creator") or data.get("creatorNick") or "").strip()
            creator_name = str(data.get("creatorName") or data.get("creator_name") or "").strip()
            seller_id = _resolve_seller_id(creator, creator_name)
        if not seller_id:
            return jsonify({"error": "seller_not_found"}), 404
        if seller_id == user.id:
            return jsonify({"error": "self"}), 400
        text = str(data.get("text") or data.get("msg") or "").strip()[:4000]
        fmt = str(data.get("fmt") or "").strip()[:200]
        work_title = str(data.get("workTitle") or data.get("work_title") or "").strip()[:200]
        work_src = str(data.get("workSrc") or data.get("work_src") or "").strip()[:700]

        # One shared dialog buyer ↔ seller (both sides see the same thread)
        th = (
            Thread.query.filter(
                Thread.buyer_id == user.id,
                Thread.seller_id == seller_id,
                Thread.kind != "assistant",
            )
            .order_by(Thread.id.desc())
            .first()
        )
        created = False
        if not th:
            created = True
            th = Thread(
                kind=kind,
                work_id=work.id if work else None,
                buyer_id=user.id,
                seller_id=seller_id,
                status="new",
            )
            db.session.add(th)
            db.session.flush()
        else:
            # Keep dialog kind current; attach work if thread had none
            th.kind = kind
            if work and work.id and not th.work_id:
                th.work_id = work.id

        buyer = _peer_card(user.id)
        label = KIND_LABEL.get(kind, kind)
        title = (work.title if work and work.title else None) or work_title or None
        sys = f"{buyer['name']} запросил(а) {label}"
        if title:
            sys += f" к «{title}»"
        if fmt:
            sys += f" · {fmt}"
        db.session.add(
            ThreadMessage(
                thread_id=th.id,
                sender_id=None,
                is_system=True,
                text=sys,
                read_by_buyer=True,
                read_by_seller=False,
            )
        )
        if text:
            db.session.add(
                ThreadMessage(
                    thread_id=th.id,
                    sender_id=user.id,
                    text=text,
                    read_by_buyer=True,
                    read_by_seller=False,
                )
            )
        th.status = "new"
        th.updated_at = datetime.utcnow()
        db.session.commit()
        payload = _thread_payload(th, user.id)
        # Soft work card for showcase/demo requests without a DB work row
        if not payload.get("work") and (work_title or work_src):
            payload["work"] = {
                "title": work_title or "Работа",
                "src": work_src or "/assets/bg-light.jpg",
            }
        return jsonify({"ok": True, "threadId": str(th.id), "created": created, "thread": payload})

    @app.get("/api/threads/<int:thread_id>/messages")
    @require_user
    def api_threads_messages(user, thread_id):
        th = Thread.query.get(thread_id)
        if not th or user.id not in {th.buyer_id, th.seller_id}:
            return jsonify({"error": "not_found"}), 404
        return jsonify(_thread_payload(th, user.id))

    @app.post("/api/threads/<int:thread_id>/messages")
    @require_user
    @rate_limit(60, 60, "threads_msg")
    def api_threads_post_message(user, thread_id):
        th = Thread.query.get(thread_id)
        if not th or user.id not in {th.buyer_id, th.seller_id}:
            return jsonify({"error": "not_found"}), 404
        data = request.get_json(silent=True) or {}
        text = str(data.get("text") or "").strip()[:4000]
        prompt = str(data.get("prompt") or "").strip()[:8000] or None
        file_meta = data.get("file") if isinstance(data.get("file"), dict) else None
        if not text and not prompt and not file_meta:
            return jsonify({"error": "empty"}), 400
        msg = ThreadMessage(
            thread_id=th.id,
            sender_id=user.id,
            text=text,
            prompt=prompt,
            file_name=(str(file_meta.get("name") or "")[:255] if file_meta else None) or None,
            file_size=(str(file_meta.get("size") or "")[:40] if file_meta else None) or None,
            file_url=(str(file_meta.get("url") or "")[:700] if file_meta else None) or None,
            read_by_buyer=user.id == th.buyer_id,
            read_by_seller=user.id == th.seller_id,
        )
        db.session.add(msg)
        if th.kind == "assistant":
            db.session.add(
                ThreadMessage(
                    thread_id=th.id,
                    sender_id=None,
                    text=_assistant_reply(text),
                    read_by_buyer=False,
                    read_by_seller=True,
                )
            )
            th.status = "answered"
        else:
            th.status = "new" if user.id == th.buyer_id else th.status
        th.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"ok": True, "thread": _thread_payload(th, user.id)})

    @app.patch("/api/threads/<int:thread_id>")
    @require_user
    def api_threads_patch(user, thread_id):
        th = Thread.query.get(thread_id)
        if not th or user.id not in {th.buyer_id, th.seller_id}:
            return jsonify({"error": "not_found"}), 404
        data = request.get_json(silent=True) or {}
        if "status" in data:
            st = str(data.get("status") or "")
            if st in {"open", "new"}:
                th.status = "new"
            elif st == "answered":
                th.status = "answered"
        if data.get("read"):
            msgs = ThreadMessage.query.filter_by(thread_id=th.id).all()
            for m in msgs:
                if user.id == th.buyer_id:
                    m.read_by_buyer = True
                else:
                    m.read_by_seller = True
        th.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"ok": True, "thread": _thread_payload(th, user.id)})

    # expose models on app for tests
    app.extensions["product_models"] = models
    return models
