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

HANDLE_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")
BANNED_HANDLES = {"admin", "support", "api", "explore", "settings", "balance", "root", "ai", "shnica"}


def register_product(app, db, User):
    models = init_product_models(db)
    Balance = models["Balance"]
    Ledger = models["Ledger"]
    CreatorProfile = models["CreatorProfile"]
    Work = models["Work"]
    FreeQuota = models["FreeQuota"]
    LoginCode = models["LoginCode"]
    Complaint = models["Complaint"]
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
                inbound_id = enqueue_inbound(
                    {
                        "model_id": integrated_id,
                        "provider": spec.get("provider"),
                        "prompt": prompt,
                        "user_id": user.id,
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
            from queue_runtime.jobs import get_job

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
            from queue_runtime.jobs import get_job

            for _ in range(60):
                job = {}
                try:
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

    def _work_public(work: Work, owner_view: bool = False, viewer_id: Optional[int] = None):
        if not work:
            return None
        url = work.original_url if owner_view and work.owner_id == (viewer_id or work.owner_id) else (work.watermarked_url or work.original_url)
        if owner_view:
            url = work.original_url or work.watermarked_url
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
            "likes": work.likes,
            "published_at": work.published_at.isoformat() if work.published_at else None,
            "owner_id": work.owner_id,
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
        if sort == "popular":
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
    def api_work_like(work_id):
        work = Work.query.filter_by(id=work_id, status="published").first()
        if not work:
            return jsonify({"error": "not_found"}), 404
        work.likes = int(work.likes or 0) + 1
        db.session.commit()
        return jsonify({"likes": work.likes})

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
        return jsonify(
            {
                "handle": prof.handle,
                "display_name": prof.display_name or (user.name if user else handle),
                "bio": prof.bio,
                "avatar_url": prof.avatar_url,
                "contacts": contacts,
                "works": [_work_public(w) for w in works],
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
        if data.get("consent_152"):
            prof.consent_152 = True
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
        row = LoginCode(
            email=email,
            code_hash=generate_password_hash(code),
            expires_at=datetime.utcnow() + timedelta(minutes=10),
        )
        db.session.add(row)
        db.session.commit()
        # Dev: return code when not production mail configured
        payload = {"ok": True}
        if (os.getenv("FLASK_ENV") or "development") != "production":
            payload["dev_code"] = code
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

    # expose models on app for tests
    app.extensions["product_models"] = models
    return models
