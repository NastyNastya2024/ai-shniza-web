# Yandex Object Storage (S3) — инструкция для ai-shniza

Object Storage в Yandex Cloud — S3-совместимое хранилище.  
Нужен для этапа 0 плана: worker кладёт туда результаты генерации (B2b), позже браузер заливает референсы по presigned URL (B1).

Официально: [создать бакет](https://yandex.cloud/ru/docs/storage/operations/buckets/create), [статический ключ](https://yandex.cloud/ru/docs/iam/operations/sa/create-access-key), [CORS](https://yandex.cloud/ru/docs/storage/operations/buckets/cors).

---

## Что получится в итоге

| Артефакт | Куда положить |
|---|---|
| Имя бакета | `.env` → `S3_BUCKET` |
| Endpoint | `.env` → `S3_ENDPOINT` |
| Region | `.env` → `S3_REGION` (обычно `ru-central1`) |
| Key ID | `.env` → `S3_ACCESS_KEY` |
| Secret Key | `.env` → `S3_SECRET_KEY` (один раз показать — сохранить сразу) |

Рекомендуемые имена:

- бакет: `ai-shniza-media` (или `ai-shniza-media-prod`) — **уникален во всём Object Storage**, латиница/цифры/дефис
- сервисный аккаунт: `sa-ai-shniza-storage`
- префиксы ключей объектов: `media/` (результаты), `uploads/` (user upload)

---

## 0. Перед началом

1. Аккаунт в [Yandex Cloud Console](https://console.yandex.cloud/).
2. Платёжный аккаунт привязан (без биллинга бакет не создастся).
3. Выбран **каталог** (folder), где уже/будет VM.
4. Роль вашего пользователя: хотя бы `storage.editor` + `iam.serviceAccounts.admin` в каталоге (или шире — `editor` / `admin`).

---

## 1. Сервисный аккаунт

Консоль → каталог → **Сервисные аккаунты** → **Создать**.

| Поле | Значение |
|---|---|
| Имя | `sa-ai-shniza-storage` |
| Описание | Object Storage for ai-shniza worker/uploads |

Создать.

### Роли на каталог (для этого SA)

На карточке SA → **Назначить роли** (или IAM каталога → назначить на SA):

| Роль | Зачем |
|---|---|
| `storage.editor` | создавать объекты, читать, удалять в бакетах каталога |
| `storage.uploader` | достаточно, если editor избыточен; на старте удобнее `storage.editor` |

Для нашего сценария хватает **`storage.editor`** на каталог (или ACL только на конкретный бакет — см. ниже).

Не выдавать `admin` / `storage.admin` без нужды.

---

## 2. Статический ключ доступа (Access Key / Secret)

Без него boto3 / awscli / worker не ходят в S3 API.

1. Открыть SA `sa-ai-shniza-storage`.
2. Вкладка **Ключи доступа** / **Создать новый ключ** → тип **Статический ключ доступа**.
3. Описание: `ai-shniza s3`.
4. **Сразу скопировать Secret Key** — второй раз консоль его не покажет.
5. Key ID тоже сохранить.

В `.env` на VM (не в git):

```env
S3_ACCESS_KEY=YCAJExxxxxxxxxxxxxxxx
S3_SECRET_KEY=YCPxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
S3_BUCKET=ai-shniza-media
S3_REGION=ru-central1
S3_ENDPOINT=https://storage.yandexcloud.net
```

Endpoint для path-style / boto3 обычно: `https://storage.yandexcloud.net`.  
Публичный URL объекта (если разрешено чтение):  
`https://storage.yandexcloud.net/<bucket>/<key>`  
или виртуальный хост: `https://<bucket>.storage.yandexcloud.net/<key>`.

---

## 3. Создать бакет

Консоль → **Object Storage** → **Создать бакет**.

| Параметр | Рекомендация для старта |
|---|---|
| Имя | `ai-shniza-media` (глобально уникальное) |
| Класс хранилища | **Standard** |
| Макс. размер | по желанию лимит (например 50–100 GB), можно без лимита на старте |
| Доступ на чтение объектов | **Ограниченный** (private) — см. §4 |
| Доступ на просмотр списка | **Ограниченный** |
| Шифрование | по умолчанию ок; SSE можно включить позже |

Создать.

### Через CLI (опционально)

Если установлен [YC CLI](https://yandex.cloud/ru/docs/cli/quickstart):

```bash
yc storage bucket create \
  --name ai-shniza-media \
  --default-storage-class standard \
  --max-size 107374182400
```

Создание бакета через API/CLI часто требует уже выданных статических ключей или IAM-токена — в консоли проще для первого раза.

---

## 4. Доступ: private сейчас, публичное чтение медиа — осознанно

**Не открывать бакет на запись анонимам.**

### Вариант A (безопасный старт) — полностью private

- Анонимное чтение: **выкл**
- Worker/Flask читают и отдают медиа через **presigned GET** (срок жизни URL, напр. 1–24 ч)
- Для Dialog UI: API отдаёт signed URL, не прямой «вечный» линк

Подходит, пока мало пользователей и нет CDN.

### Вариант B (проще для UI) — public-read только для объектов

В настройках бакета → **Права доступа** / anonymous access:

| Флаг | Значение |
|---|---|
| Чтение объектов | **Разрешить** (public-read) |
| Список объектов | **Запретить** |
| Чтение настроек бакета | **Запретить** |

Тогда URL вида  
`https://storage.yandexcloud.net/ai-shniza-media/media/<job_id>/out.png`  
открывается в `<img>` / `<video>` без подписи.

Минус: кто знает URL — скачает файл. Ключи объектов делать непредсказуемыми (`uuid`), не `user_id/1.png`.

**Рекомендация на этап 0–4:** начать с **варианта A** (private + signed GET) или B, если хочется быстрее проверить UI. Запись всегда только с ключами SA.

ACL на объект при upload worker’ом: для варианта B можно ставить `public-read` на объект; для A — private.

---

## 5. CORS (нужен для B1 — upload из браузера)

Пока только worker кладёт файлы с VM — CORS можно отложить.  
Перед этапом 5 (presign PUT) настроить обязательно.

Бакет → **CORS** → настроить правило:

| Поле | Значение |
|---|---|
| Allowed Origins | `https://ваш-домен.ru` (без `*` в проде) |
| Allowed Methods | `GET`, `PUT`, `HEAD` (при необходимости `POST`) |
| Allowed Headers | `*` или `Content-Type`, `Content-Length` |
| Expose Headers | `ETag` |
| Max Age Seconds | `3000` |

Для локальной отладки upload можно временно добавить `http://127.0.0.1:8000` — потом убрать.

---

## 6. Права SA именно на бакет (опционально, жёстче)

Вместо роли на весь каталог можно выдать доступ только к бакету:

1. Бакет → **Права доступа** → добавить субъекта `sa-ai-shniza-storage`.
2. Права: чтение + запись объектов (полный доступ к объектам бакета).

Так SA не трогает чужие бакеты в каталоге.

---

## 7. Проверка с VM / ноутбука (smoke test)

На машине с Python:

```bash
pip install boto3
```

```python
import boto3

s3 = boto3.client(
    "s3",
    endpoint_url="https://storage.yandexcloud.net",
    region_name="ru-central1",
    aws_access_key_id="YCAJE...",       # S3_ACCESS_KEY
    aws_secret_access_key="YCP...",     # S3_SECRET_KEY
)

bucket = "ai-shniza-media"
key = "media/_smoke/hello.txt"

s3.put_object(Bucket=bucket, Key=key, Body=b"ok", ContentType="text/plain")
print(s3.get_object(Bucket=bucket, Key=key)["Body"].read())
s3.delete_object(Bucket=bucket, Key=key)
print("S3 OK")
```

Через AWS CLI (тот же endpoint):

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
aws --endpoint-url=https://storage.yandexcloud.net \
  s3 cp ./test.txt s3://ai-shniza-media/media/_smoke/test.txt
aws --endpoint-url=https://storage.yandexcloud.net \
  s3 ls s3://ai-shniza-media/media/_smoke/
```

Если `AccessDenied` — роли SA / ключ / имя бакета.

---

## 8. Что не делать

- Не коммитить `S3_SECRET_KEY` в git.
- Не ставить анонимный **list** бакета.
- Не давать анонимам **write**.
- Не использовать бакет с точкой в имени, если нужен простой HTTPS на `*.storage.yandexcloud.net` без своего сертификата (имя без точки проще).
- Не класть секреты и `.env` в Object Storage «для удобства».

---

## 9. Чеклист этапа 0 (Object Storage)

- [ ] SA `sa-ai-shniza-storage` создан
- [ ] Роль `storage.editor` (или доступ к бакету) выдана
- [ ] Статический ключ создан, secret сохранён вне git
- [ ] Бакет создан, имя уникально
- [ ] Анонимная запись выключена; list выключен
- [ ] Выбран private + signed URL **или** public-read объектов
- [ ] Smoke test `put` / `get` / `delete` прошёл
- [ ] Переменные прописаны в `.env` на сервере
- [ ] (Позже) CORS под домен приложения

---

## 10. Связь с планом

После этого пункта этапа 0 из [plan.md](./plan.md) закрыт по storage. Дальше — Postgres/Redis на VM и деплой Flask; worker→S3 подключается на этапе 4.
