# OmniRoute (отдельный сервис)

Поднимает опубликованный образ `diegosouzapw/omniroute` рядом с Flask.
Исходники в `OmniRoute-release-v3.8.51/` для справки; для рантайма не обязательны.

## Старт

```bash
cd deploy/omniroute
docker compose up -d
```

- Dashboard: http://127.0.0.1:20128
- API: http://127.0.0.1:20128/v1
- Health: http://127.0.0.1:20128/healthz

## Стоп / логи

```bash
docker compose logs -f omniroute
docker compose down
```

Данные (ключи, sqlite) в Docker volume `omniroute-data`.

## Дальше

1. Dashboard: http://127.0.0.1:20128 (пароль в `deploy/omniroute/.env` → `INITIAL_PASSWORD`).
2. API key уже можно создать скриптом bootstrap; ключ лежит в корневом `.env` как `OMNIROUTE_API_KEY`.
3. Flask Generate: модели `omni-auto` / `omni-auto-free` (`provider: omniroute`).
4. Проверка: `curl -H "Authorization: Bearer $OMNIROUTE_API_KEY" http://127.0.0.1:20128/v1/models`
