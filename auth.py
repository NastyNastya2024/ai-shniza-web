from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode, quote

import requests
from flask import jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
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


def load_env(base_dir: str) -> None:
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
            if key:
                os.environ[key] = value.strip().strip('"').strip("'")


def _provider_creds(name: str):
    spec = PROVIDERS.get(name)
    if not spec:
        return None, None, None
    client_id = (os.getenv(spec["id_env"]) or "").strip()
    client_secret = (os.getenv(spec["secret_env"]) or "").strip()
    return spec, client_id, client_secret


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

    @app.route("/api/auth/<provider>")
    def oauth_start(provider):
        spec, client_id, client_secret = _provider_creds(provider)
        if not spec:
            return redirect("/?auth_error=unknown_provider")
        if not client_id or not client_secret:
            return redirect(f"/?auth_error=oauth_not_configured&provider={quote(provider)}")
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
        if provider == "google":
            params["access_type"] = "online"
            params["prompt"] = "select_account"
        if provider == "vk":
            params["display"] = "page"
            params["v"] = "5.199"
        return redirect(f"{spec['authorize']}?{urlencode(params)}")

    @app.route("/api/auth/<provider>/callback")
    def oauth_callback(provider):
        spec, client_id, client_secret = _provider_creds(provider)
        if not spec or not client_id or not client_secret:
            return redirect("/?auth_error=oauth_not_configured")
        if request.args.get("error"):
            return redirect("/?auth_error=oauth_denied")
        if request.args.get("state") != session.get("oauth_state") or session.get("oauth_provider") != provider:
            return redirect("/?auth_error=oauth_state")
        code = request.args.get("code")
        if not code:
            return redirect("/?auth_error=oauth_code")

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
                return redirect("/?auth_error=oauth_token")
            email, name, provider_id = _fetch_profile(provider, token_payload, access_token)
        except Exception:
            return redirect("/?auth_error=oauth_failed")

        user = User.query.filter_by(provider=provider, provider_id=provider_id).first()
        if not user and email:
            user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email, provider=provider, provider_id=provider_id, name=name or email)
            db.session.add(user)
        else:
            user.provider = provider
            user.provider_id = provider_id
            if name:
                user.name = name
            if email:
                user.email = email
        db.session.commit()
        session.pop("oauth_state", None)
        session.pop("oauth_provider", None)
        session["user_id"] = user.id
        return redirect("/")
