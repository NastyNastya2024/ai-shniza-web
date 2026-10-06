from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode, quote

import requests
from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "jwks": "https://www.googleapis.com/oauth2/v3/certs",
        "issuers": ("https://accounts.google.com", "accounts.google.com"),
        "scope": "openid email profile",
        "id_env": "GOOGLE_CLIENT_ID",
        "secret_env": "GOOGLE_CLIENT_SECRET",
    },
    "github": {
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "scope": "read:user user:email",
        "id_env": "GITHUB_CLIENT_ID",
        "secret_env": "GITHUB_CLIENT_SECRET",
    },
    "yandex": {
        "authorize": "https://oauth.yandex.ru/authorize",
        "token": "https://oauth.yandex.ru/token",
        "scope": "login:email login:info",
        "id_env": "YANDEX_CLIENT_ID",
        "secret_env": "YANDEX_CLIENT_SECRET",
    },
    "vk": {
        "authorize": "https://oauth.vk.com/authorize",
        "token": "https://oauth.vk.com/access_token",
        "scope": "email",
        "id_env": "VK_CLIENT_ID",
        "secret_env": "VK_CLIENT_SECRET",
    },
}

_JWKS_CACHE: dict = {"keys": [], "until": 0.0}


def load_env(base_dir: str) -> None:
    """Load .env into os.environ without overriding already-set variables."""
    path = os.path.join(base_dir, ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = value.strip().strip('"').strip("'")


def _provider_creds(name: str):
    spec = PROVIDERS.get(name)
    if not spec:
        return None, None, None
    client_id = (os.getenv(spec["id_env"]) or "").strip()
    client_secret = (os.getenv(spec["secret_env"]) or "").strip()
    return spec, client_id, client_secret


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _safe_next(raw: str | None, default: str = "/app") -> str:
    nxt = str(raw or "").strip()
    if nxt.startswith("/") and not nxt.startswith("//") and not nxt.startswith("/\\"):
        return nxt
    return default


def _google_redirect_uri() -> str:
    """Must match Authorized redirect URI in Google Cloud Console exactly."""
    base = (os.getenv("BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if base:
        return f"{base}/auth/google/callback"
    return url_for("google_oauth_callback", _external=True)


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url_encode(digest)


def _get_google_jwks(force: bool = False) -> list:
    now = time.time()
    if not force and _JWKS_CACHE["until"] > now and _JWKS_CACHE["keys"]:
        return _JWKS_CACHE["keys"]
    jwks_url = (os.getenv("GOOGLE_JWKS_URL") or PROVIDERS["google"]["jwks"]).strip()
    resp = requests.get(jwks_url, timeout=15)
    resp.raise_for_status()
    keys = (resp.json() or {}).get("keys") or []
    max_age = 3600
    cc = resp.headers.get("Cache-Control") or ""
    if "max-age=" in cc:
        try:
            max_age = int(cc.split("max-age=")[1].split(",")[0].strip())
        except (ValueError, IndexError):
            pass
    _JWKS_CACHE["keys"] = keys
    _JWKS_CACHE["until"] = now + max(60, max_age)
    return keys


def _jwk_rsa_public_key(jwk: dict):
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    from cryptography.hazmat.backends import default_backend

    n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
    e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
    return RSAPublicNumbers(e, n).public_key(default_backend())


def _verify_google_id_token(id_token: str, expected_nonce: str, client_id: str) -> dict:
    """Verify Google ID token: RS256 signature via JWKS, aud/iss/exp/nonce/email_verified."""
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes
    from cryptography.exceptions import InvalidSignature

    parts = str(id_token).split(".")
    if len(parts) != 3:
        raise ValueError("bad_token")
    header_b64, payload_b64, sig_b64 = parts
    header = json.loads(_b64url_decode(header_b64))
    claims = json.loads(_b64url_decode(payload_b64))
    if header.get("alg") != "RS256":
        raise ValueError("bad_alg")

    kid = header.get("kid")
    jwk = next((k for k in _get_google_jwks() if k.get("kid") == kid), None)
    if not jwk:
        jwk = next((k for k in _get_google_jwks(force=True) if k.get("kid") == kid), None)
    if not jwk:
        raise ValueError("unknown_kid")

    public_key = _jwk_rsa_public_key(jwk)
    try:
        public_key.verify(
            _b64url_decode(sig_b64),
            f"{header_b64}.{payload_b64}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise ValueError("bad_signature") from exc

    now = int(time.time())
    issuers = PROVIDERS["google"]["issuers"]
    env_iss = (os.getenv("GOOGLE_ISSUERS") or "").strip()
    if env_iss:
        issuers = tuple(x.strip() for x in env_iss.split(",") if x.strip())
    if claims.get("iss") not in issuers:
        raise ValueError("bad_iss")
    aud = claims.get("aud")
    if isinstance(aud, list):
        if client_id not in aud:
            raise ValueError("bad_aud")
    elif aud != client_id:
        raise ValueError("bad_aud")
    if int(claims.get("exp") or 0) < now - 60:
        raise ValueError("expired")
    if int(claims.get("iat") or 0) > now + 300:
        raise ValueError("bad_iat")
    if claims.get("nonce") != expected_nonce:
        raise ValueError("bad_nonce")
    if not claims.get("email") or claims.get("email_verified") is not True:
        raise ValueError("email_not_verified")
    return claims


def _fetch_profile(provider: str, token_payload: dict, access_token: str):
    email = ""
    name = ""
    provider_id = ""

    if provider == "google":
        info = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        info.raise_for_status()
        data = info.json()
        email = (data.get("email") or "").lower()
        name = data.get("name") or ""
        provider_id = str(data.get("id") or email)

    elif provider == "github":
        info = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=15,
        )
        info.raise_for_status()
        data = info.json()
        provider_id = str(data.get("id") or "")
        name = data.get("name") or data.get("login") or ""
        email = (data.get("email") or "").lower()
        if not email:
            emails = requests.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                timeout=15,
            )
            if emails.ok:
                primary = next((item for item in emails.json() if item.get("primary") and item.get("email")), None)
                email = ((primary or {}).get("email") or "").lower()

    elif provider == "yandex":
        info = requests.get(
            "https://login.yandex.ru/info",
            params={"format": "json"},
            headers={"Authorization": f"OAuth {access_token}"},
            timeout=15,
        )
        info.raise_for_status()
        data = info.json()
        email = (data.get("default_email") or (data.get("emails") or [""])[0] or "").lower()
        name = data.get("real_name") or data.get("display_name") or ""
        provider_id = str(data.get("id") or email)

    elif provider == "vk":
        email = (token_payload.get("email") or "").lower()
        user_id = str(token_payload.get("user_id") or "")
        provider_id = user_id
        if user_id:
            info = requests.get(
                "https://api.vk.com/method/users.get",
                params={"access_token": access_token, "v": "5.199", "user_ids": user_id},
                timeout=15,
            )
            if info.ok:
                person = (info.json().get("response") or [{}])[0]
                name = f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()

    if not email:
        email = f"{provider}_{provider_id or 'user'}@users.aishniza.local"
    if not provider_id:
        provider_id = email
    return email, name, provider_id


def _upsert_oauth_user(db, User, provider: str, provider_id: str, email: str, name: str):
    email = (email or "").strip().lower()
    user = User.query.filter_by(provider=provider, provider_id=provider_id).first()
    if not user and email:
        user = User.query.filter_by(email=email).first()
    if not user:
        user = User(
            email=email or f"{provider}_{provider_id}@users.aishniza.local",
            provider=provider,
            provider_id=provider_id,
            name=name or (email.split("@")[0] if email else provider),
        )
        db.session.add(user)
    else:
        user.provider = provider
        user.provider_id = provider_id
        if name:
            user.name = name
        if email:
            user.email = email
    db.session.commit()
    return user


def _google_fail(code: str):
    return redirect(f"/auth?error={quote(code)}")


def register_auth(app, db, User):
    @app.route("/api/auth/me")
    def auth_me():
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({"user": None})
        user = db.session.get(User, user_id)
        if not user:
            session.clear()
            return jsonify({"user": None})
        return jsonify({
            "user": {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "provider": user.provider,
            }
        })

    @app.route("/api/auth/logout", methods=["POST"])
    def auth_logout():
        session.clear()
        return jsonify({"ok": True})

    @app.route("/api/auth/register", methods=["POST"])
    def auth_register():
        payload = request.get_json(silent=True) or {}
        email = str(payload.get("email") or "").strip().lower()
        password = str(payload.get("password") or "")
        if "@" not in email or "." not in email.split("@")[-1]:
            return jsonify({"error": "invalid_email"}), 400
        if len(password) < 6:
            return jsonify({"error": "weak_password"}), 400
        if User.query.filter_by(email=email).first():
            return jsonify({"error": "exists"}), 409
        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            provider="password",
            provider_id=email,
            name=email.split("@")[0],
        )
        db.session.add(user)
        db.session.commit()
        session["user_id"] = user.id
        return jsonify({"user": {"id": user.id, "email": user.email, "name": user.name, "provider": user.provider}})

    @app.route("/api/auth/login", methods=["POST"])
    def auth_login():
        payload = request.get_json(silent=True) or {}
        email = str(payload.get("email") or "").strip().lower()
        password = str(payload.get("password") or "")
        user = User.query.filter_by(email=email).first()
        if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
            return jsonify({"error": "invalid"}), 401
        session["user_id"] = user.id
        return jsonify({"user": {"id": user.id, "email": user.email, "name": user.name, "provider": user.provider}})

    # --- Google: Authorization Code + PKCE + id_token (JWKS) ---
    @app.route("/auth/google")
    @app.route("/api/auth/google")
    def google_oauth_start():
        spec, client_id, client_secret = _provider_creds("google")
        if not client_id or not client_secret:
            return _google_fail("not_configured")

        nxt = _safe_next(request.args.get("next"), "/app")
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(48)
        challenge = _pkce_challenge(verifier)

        session["g_oauth"] = {
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "next": nxt,
            "consent": request.args.get("consent") == "1",
            "t": int(time.time()),
        }
        session.modified = True

        auth_url = (os.getenv("GOOGLE_AUTH_URL") or spec["authorize"]).strip()
        params = {
            "client_id": client_id,
            "redirect_uri": _google_redirect_uri(),
            "response_type": "code",
            "scope": spec["scope"],
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
            "access_type": "online",
        }
        hint = str(request.args.get("hint") or "").strip()
        if hint and "@" in hint:
            params["login_hint"] = hint
        return redirect(f"{auth_url}?{urlencode(params)}")

    @app.route("/auth/google/callback")
    @app.route("/api/auth/google/callback")
    def google_oauth_callback():
        spec, client_id, client_secret = _provider_creds("google")
        if not client_id or not client_secret:
            return _google_fail("not_configured")

        tmp = session.pop("g_oauth", None) or {}
        session.modified = True

        err = request.args.get("error")
        if err:
            return _google_fail("cancelled" if err == "access_denied" else "google_error")

        if not tmp or int(time.time()) - int(tmp.get("t") or 0) > 600:
            return _google_fail("expired")
        if not request.args.get("state") or request.args.get("state") != tmp.get("state"):
            return _google_fail("bad_state")
        code = request.args.get("code")
        if not code:
            return _google_fail("google_error")

        token_url = (os.getenv("GOOGLE_TOKEN_URL") or spec["token"]).strip()
        try:
            token_resp = requests.post(
                token_url,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": _google_redirect_uri(),
                    "grant_type": "authorization_code",
                    "code_verifier": tmp.get("verifier") or "",
                },
                headers={"Accept": "application/json"},
                timeout=15,
            )
            token_payload = token_resp.json() if token_resp.content else {}
            if not token_resp.ok or not token_payload.get("id_token"):
                raise ValueError("token_exchange: " + str(token_payload.get("error") or token_resp.status_code))
            claims = _verify_google_id_token(token_payload["id_token"], tmp.get("nonce") or "", client_id)
        except Exception as exc:
            app.logger.warning("google oauth callback failed: %s", exc)
            return _google_fail("google_error")

        email = str(claims.get("email") or "").strip().lower()
        name = str(claims.get("name") or "").strip() or (email.split("@")[0] if email else "user")
        provider_id = str(claims.get("sub") or "")
        if not provider_id or not email:
            return _google_fail("google_error")

        user = _upsert_oauth_user(db, User, "google", provider_id, email, name)

        # Mark consent / verified email on creator profile when present
        try:
            for mapper in db.Model.registry.mappers:
                cls = mapper.class_
                if getattr(cls, "__tablename__", None) == "creator_profiles":
                    prof = db.session.get(cls, user.id)
                    if not prof:
                        prof = cls(user_id=user.id)
                        db.session.add(prof)
                    prof.email_verified = True
                    if tmp.get("consent"):
                        prof.consent_152 = True
                    if claims.get("picture") and hasattr(prof, "avatar_url") and not prof.avatar_url:
                        prof.avatar_url = str(claims.get("picture"))[:500]
                    if name and hasattr(prof, "display_name") and not prof.display_name:
                        prof.display_name = name[:120]
                    db.session.commit()
                    break
        except Exception:
            pass

        session["user_id"] = user.id
        session.permanent = True
        return redirect(_safe_next(tmp.get("next"), "/app"))

    @app.route("/api/auth/<provider>")
    def oauth_start(provider):
        if provider == "google":
            return google_oauth_start()
        spec, client_id, client_secret = _provider_creds(provider)
        if not spec:
            return redirect("/auth?auth_error=unknown_provider")
        if not client_id or not client_secret:
            return redirect(f"/auth?auth_error=oauth_not_configured&provider={quote(provider)}")
        nxt = _safe_next(request.args.get("next"), "/app")
        session["auth_next"] = nxt
        state = secrets.token_urlsafe(24)
        session["oauth_state"] = state
        session["oauth_provider"] = provider
        redirect_uri = url_for("oauth_callback", provider=provider, _external=True)
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
            "scope": spec["scope"],
        }
        if provider == "vk":
            params["display"] = "page"
            params["v"] = "5.199"
        return redirect(f"{spec['authorize']}?{urlencode(params)}")

    @app.route("/api/auth/<provider>/callback")
    def oauth_callback(provider):
        if provider == "google":
            return google_oauth_callback()
        spec, client_id, client_secret = _provider_creds(provider)
        if not spec or not client_id or not client_secret:
            return redirect("/auth?auth_error=oauth_not_configured")
        if request.args.get("error"):
            return redirect("/auth?auth_error=oauth_denied")
        if request.args.get("state") != session.get("oauth_state") or session.get("oauth_provider") != provider:
            return redirect("/auth?auth_error=oauth_state")
        code = request.args.get("code")
        if not code:
            return redirect("/auth?auth_error=oauth_code")

        redirect_uri = url_for("oauth_callback", provider=provider, _external=True)
        try:
            if provider == "vk":
                token_resp = requests.get(
                    spec["token"],
                    params={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": redirect_uri,
                        "code": code,
                    },
                    timeout=15,
                )
            else:
                token_resp = requests.post(
                    spec["token"],
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": redirect_uri,
                        "code": code,
                        "grant_type": "authorization_code",
                    },
                    headers={"Accept": "application/json"},
                    timeout=15,
                )
            token_resp.raise_for_status()
            token_payload = token_resp.json()
            access_token = token_payload.get("access_token")
            if not access_token:
                return redirect("/auth?auth_error=oauth_token")
            email, name, provider_id = _fetch_profile(provider, token_payload, access_token)
        except Exception:
            return redirect("/auth?auth_error=oauth_failed")

        user = _upsert_oauth_user(db, User, provider, provider_id, email, name)
        session.pop("oauth_state", None)
        session.pop("oauth_provider", None)
        session["user_id"] = user.id
        nxt = _safe_next(session.pop("auth_next", None), "/app")
        return redirect(nxt)
