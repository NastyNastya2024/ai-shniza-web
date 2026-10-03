"""Security helpers: CORS, CSRF, headers, Redis rate limits."""
from __future__ import annotations

import os
import secrets
import time
from functools import wraps
from typing import Callable, Optional

from flask import Flask, Response, g, jsonify, request, session

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore


def _is_prod() -> bool:
    env = (os.getenv("FLASK_ENV") or os.getenv("APP_ENV") or "development").strip().lower()
    return env in {"production", "prod"}


def _allowed_origins() -> list[str]:
    raw = (os.getenv("ALLOWED_ORIGINS") or "").strip()
    if not raw:
        if _is_prod():
            return []
        return ["http://127.0.0.1:8000", "http://localhost:8000"]
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


def _redis_client():
    if redis is None:
        return None
    url = (os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0").strip()
    try:
        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.4)
        client.ping()
        return client
    except Exception:
        return None


_MEMORY_BUCKETS: dict[str, list[float]] = {}


def rate_limit(limit: int, window_sec: int, key_prefix: str) -> Callable:
    """Simple fixed-window rate limit (Redis if available, else process memory)."""

    def decorator(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "unknown").split(",")[0].strip()
            bucket = f"rl:{key_prefix}:{ip}"
            client = getattr(g, "redis", None)
            now = time.time()
            if client is not None:
                try:
                    pipe = client.pipeline()
                    pipe.incr(bucket)
                    pipe.expire(bucket, window_sec)
                    count, _ = pipe.execute()
                    if int(count) > limit:
                        return jsonify({"error": "rate_limited", "retry_after": window_sec}), 429
                except Exception:
                    pass  # fall through to memory
                else:
                    return fn(*args, **kwargs)

            hits = _MEMORY_BUCKETS.setdefault(bucket, [])
            cutoff = now - window_sec
            hits[:] = [t for t in hits if t >= cutoff]
            if len(hits) >= limit:
                return jsonify({"error": "rate_limited", "retry_after": window_sec}), 429
            hits.append(now)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def ensure_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _csrf_ok() -> bool:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    # OAuth browser redirects are GET-only; unsafe methods need token.
    expected = session.get("csrf_token")
    if not expected:
        return False
    sent = (
        request.headers.get("X-CSRF-Token")
        or request.headers.get("X-Csrf-Token")
        or (request.get_json(silent=True) or {}).get("csrf_token")
        or request.form.get("csrf_token")
    )
    if not sent:
        return False
    return secrets.compare_digest(str(sent), str(expected))


def configure_security(app: Flask) -> None:
    prod = _is_prod()
    secret = (os.getenv("SECRET_KEY") or "").strip()
    if prod:
        if not secret or secret in {"change-me", "dev", "secret"}:
            raise RuntimeError("SECRET_KEY must be set to a strong value in production")
        app.config["SECRET_KEY"] = secret
    else:
        app.config["SECRET_KEY"] = secret or app.config.get("SECRET_KEY") or secrets.token_hex(32)

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = prod or (os.getenv("SESSION_COOKIE_SECURE", "").lower() in {"1", "true", "yes"})
    app.config["PERMANENT_SESSION_LIFETIME"] = int(os.getenv("SESSION_TTL_SEC") or 60 * 60 * 24 * 14)

    origins = _allowed_origins()
    try:
        from flask_cors import CORS

        if origins:
            CORS(
                app,
                origins=origins,
                supports_credentials=True,
                allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"],
                methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            )
        elif not prod:
            CORS(app, supports_credentials=True)
        # prod + empty ALLOWED_ORIGINS → no CORS (same-origin only via nginx)
    except ImportError:
        pass

    @app.before_request
    def _security_before():
        g.redis = _redis_client()
        if request.method == "OPTIONS":
            return None
        # Skip CSRF for static assets and health
        path = request.path or ""
        if path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            # OAuth callback is GET; token exchange stays server-side.
            if path.startswith("/api/auth/") and path.count("/") >= 3 and path.endswith("/callback"):
                return None
            # Payment provider webhooks cannot send CSRF cookies from our domain.
            if path in {"/api/payments/robokassa/result", "/api/payments/yookassa/result"}:
                return None
            if not _csrf_ok():
                # Bootstrap: allow first POST to /api/csrf bootstrap via GET only;
                # clients must call GET /api/csrf first.
                return jsonify({"error": "csrf_failed"}), 403
        return None

    @app.after_request
    def _security_headers(resp: Response):
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        csp = os.getenv(
            "CONTENT_SECURITY_POLICY",
            "default-src 'self'; "
            "img-src 'self' data: https: blob:; "
            "media-src 'self' https: blob:; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "script-src 'self' 'unsafe-inline'; "
            "connect-src 'self' https:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        resp.headers.setdefault("Content-Security-Policy", csp)
        if prod or os.getenv("ENABLE_HSTS", "").lower() in {"1", "true", "yes"}:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        # Expose CSRF for same-origin JS via cookie readable by document (not HttpOnly)
        if session.get("csrf_token"):
            resp.set_cookie(
                "csrf_token",
                session["csrf_token"],
                httponly=False,
                samesite="Lax",
                secure=bool(app.config.get("SESSION_COOKIE_SECURE")),
                max_age=int(app.config.get("PERMANENT_SESSION_LIFETIME") or 1209600),
            )
        return resp

    @app.get("/api/csrf")
    def api_csrf():
        token = ensure_csrf_token()
        return jsonify({"csrf_token": token})


def apply_rate_limits(app: Flask) -> None:
    """Attach rate limits to existing view functions by endpoint name."""
    mapping = {
        "api_chat": (30, 60, "chat"),
        "api_generate": (20, 60, "generate"),
        "api_assistant": (40, 60, "assistant"),
        "auth_login": (20, 60, "auth"),
        "auth_register": (10, 60, "auth_reg"),
        "auth_logout": (60, 60, "auth_out"),
        "api_balance_topup": (10, 60, "topup"),
    }
    app.extensions["rate_limit"] = rate_limit

    for endpoint, (limit, window, prefix) in mapping.items():
        view = app.view_functions.get(endpoint)
        if view:
            app.view_functions[endpoint] = rate_limit(limit, window, prefix)(view)
