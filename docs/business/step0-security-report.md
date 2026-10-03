# Шаг 0 — отчёт (безопасность)

**Дата:** 2026-10-02  
**Тесты:** `pytest tests/test_security_step0.py` → **5 passed**

## Сделано
- `app.db` и `__pycache__` убраны из git; история очищена через `git filter-repo`
- `.gitignore`: `*.db`, `__pycache__/`, pytest/coverage
- `security.py`: CORS из `ALLOWED_ORIGINS`, CSRF (`/api/csrf` + `X-CSRF-Token`), security headers (CSP, XFO DENY, nosniff, HSTS в prod), Secure/HttpOnly/SameSite cookies
- `SECRET_KEY` обязателен в production (`FLASK_ENV=production`)
- `debug=True` убран; локально только при `FLASK_DEBUG=1`
- Rate limit (Redis или in-memory) на chat / generate / auth (+ заготовка topup)
- Прод-запуск: `wsgi.py`, `deploy/gunicorn.conf.py`, `deploy/nginx.ai-shniza.conf.example`
- CSRF в `app.js` и `generate.js`
- `env.example` с `ALLOWED_ORIGINS`, `SECRET_KEY`, `REGION`

## Замечания
- После `git filter-repo` remote `origin` мог сброситься — проверьте `git remote -v`. Пуш истории потребует `--force` (согласовать).
- Локальный `app.db` на диске может остаться (игнор); это нормально.
