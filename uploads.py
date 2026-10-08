"""Скрепка в студии: загрузка файлов для генерации.

Поток:
  1. Фронт (attach.js) отправляет файл: POST /api/uploads (multipart, поле «file»).
  2. Сервер проверяет тип по содержимому (не по имени), размер, у картинок — пиксели;
     поворачивает фото по EXIF и убирает метаданные; сохраняет в S3 или в media/
     (через media_store) и отвечает ссылкой-номером {"id": "upl_…"}.
  3. В /api/generate фронт кладёт этот номер в поле image / audio / video.
     resolve_generate_media() превращает номер в ссылку, которую скачает провайдер:
       S3            → подписанная ссылка (UPLOAD_PRESIGN_SEC, по умолчанию сутки);
       media/ + PUBLIC_BASE_URL (или BASE_URL) → https://сайт/media/…;
       media/ без публичного адреса (локальная разработка) → data URL.
  Старые клиенты (generate.js) по-прежнему могут слать data URL — они проходят как раньше.

Номер видит только владелец: вошедший пользователь (u:<id>) или гость этой сессии (g:<токен>).
Гость может прикрепить файл до входа — после входа файл остаётся его.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from flask import Flask, current_app, jsonify, request, session

log = logging.getLogger(__name__)

KINDS = ("image", "audio", "video")
ID_RE = re.compile(r"^upl_[a-f0-9]{24}$")


def _env_mb(name: str, default: float) -> int:
    try:
        return int(float(os.getenv(name) or default) * 1024 * 1024)
    except ValueError:
        return int(default * 1024 * 1024)


def limits() -> dict[str, int]:
    """Максимальный размер файла по типу, байты."""
    return {
        "image": _env_mb("UPLOAD_MAX_IMAGE_MB", 20),
        "audio": _env_mb("UPLOAD_MAX_AUDIO_MB", 30),
        "video": _env_mb("UPLOAD_MAX_VIDEO_MB", 100),
    }


def ttl_sec() -> int:
    return int(os.getenv("UPLOAD_TTL_SEC") or 24 * 3600)


# ───────────────────────── тип файла по содержимому ─────────────────────────

@dataclass
class Sniff:
    kind: str
    mime: str
    ext: str


class UploadError(Exception):
    """Ошибка для ответа клиенту: code — машинный, status — HTTP."""

    def __init__(self, code: str, status: int = 400, detail: str = "", **extra: Any):
        super().__init__(code)
        self.code = code
        self.status = status
        self.detail = detail
        self.extra = extra

    def to_dict(self) -> dict:
        out = {"error": self.code}
        if self.detail:
            out["detail"] = self.detail
        out.update(self.extra)
        return out


MediaRefError = UploadError  # для /api/generate — те же коды и формат

_MP4_AUDIO_BRANDS = {b"M4A ", b"M4B ", b"M4P ", b"F4A "}
_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis", b"avif", b"avis"}


def sniff(head: bytes, declared_mime: str = "") -> Optional[Sniff]:
    """Определяет тип по первым байтам. Возвращает None, если формат не поддерживаем."""
    declared = (declared_mime or "").lower()
    if head.startswith(b"\xff\xd8\xff"):
        return Sniff("image", "image/jpeg", "jpg")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return Sniff("image", "image/png", "png")
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return Sniff("image", "image/gif", "gif")
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return Sniff("image", "image/webp", "webp")
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return Sniff("audio", "audio/wav", "wav")
    if head[:4] == b"fLaC":
        return Sniff("audio", "audio/flac", "flac")
    if head[:4] == b"OggS":
        return Sniff("audio", "audio/ogg", "ogg")
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return Sniff("audio", "audio/mpeg", "mp3")
    if head[:4] == b"\x1a\x45\xdf\xa3":  # Matroska / WebM
        if declared.startswith("audio/"):
            return Sniff("audio", "audio/webm", "webm")
        return Sniff("video", "video/webm", "webm")
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _HEIF_BRANDS:
            return Sniff("image", "image/heic", "heic")  # отдельная ошибка ниже
        if brand in _MP4_AUDIO_BRANDS or declared in {"audio/mp4", "audio/x-m4a", "audio/m4a", "audio/aac"}:
            return Sniff("audio", "audio/mp4", "m4a")
        if brand == b"qt  ":
            return Sniff("video", "video/quicktime", "mov")
        return Sniff("video", "video/mp4", "mp4")
    return None


# ───────────────────────── картинки ─────────────────────────

def process_image(data: bytes, sn: Sniff) -> tuple[bytes, Sniff, int, int]:
    """Проверяет картинку, поворачивает по EXIF, убирает метаданные, уменьшает огромные.

    GIF не трогаем (анимация). Возвращает (байты, тип, ширина, высота).
    """
    if sn.mime == "image/heic":
        raise UploadError("heic_unsupported", 415, "HEIC/AVIF: сохраните фото как JPG или PNG")
    try:
        from PIL import Image, ImageOps
    except ImportError:  # Pillow есть в requirements; без него — без обработки
        return data, sn, 0, 0

    max_side = int(os.getenv("UPLOAD_IMAGE_MAX_SIDE") or 4096)
    Image.MAX_IMAGE_PIXELS = int(os.getenv("UPLOAD_IMAGE_MAX_PIXELS") or 60_000_000)
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        img = Image.open(io.BytesIO(data))
        img.load()
    except Image.DecompressionBombError:
        raise UploadError("image_too_big", 413, "слишком много пикселей")
    except Exception:
        raise UploadError("bad_file", 400, "файл повреждён или это не картинка")

    if sn.mime == "image/gif":
        return data, sn, img.width, img.height

    exif = img.getexif() if hasattr(img, "getexif") else {}
    needs_rotate = bool(exif and exif.get(0x0112, 1) not in (0, 1))
    too_big = max(img.width, img.height) > max_side
    has_meta = bool(exif) or bool(img.info.get("exif"))  # EXIF: геометка, модель телефона — убираем
    if not (needs_rotate or too_big or has_meta):
        return data, sn, img.width, img.height

    img = ImageOps.exif_transpose(img)
    if too_big:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    out = io.BytesIO()
    if sn.mime == "image/png":
        img.save(out, "PNG", optimize=True)
    elif sn.mime == "image/webp":
        img.save(out, "WEBP", quality=92)
    else:
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(out, "JPEG", quality=92, optimize=True)
        sn = Sniff("image", "image/jpeg", "jpg")
    return out.getvalue(), sn, img.width, img.height


# ───────────────────────── где лежат записи о файлах ─────────────────────────

class MetaStore:
    """upl_id → запись. Redis (переживает рестарт, общий для воркеров) или память процесса."""

    def __init__(self, redis_fn: Optional[Callable[[], Any]] = None):
        self._redis_fn = redis_fn
        self._client = None
        self._retry_at = 0.0
        self._mem: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def _redis(self):
        """Клиент Redis с кэшем; если Redis лёг — пробуем снова не чаще раза в 30 с."""
        if self._client is not None:
            return self._client
        if not self._redis_fn or time.time() < self._retry_at:
            return None
        try:
            self._client = self._redis_fn()
        except Exception:  # noqa: BLE001
            self._client = None
        if self._client is None:
            self._retry_at = time.time() + 30
        return self._client

    def put(self, meta: dict, ttl: int) -> None:
        r = self._redis()
        if r is not None:
            try:
                r.set(f"upl:{meta['id']}", json.dumps(meta, ensure_ascii=False), ex=ttl)
                return
            except Exception:  # noqa: BLE001
                log.warning("uploads: redis set failed, using memory")
        with self._lock:
            self._gc()
            self._mem[meta["id"]] = (time.time() + ttl, meta)

    def get(self, upl_id: str) -> Optional[dict]:
        r = self._redis()
        if r is not None:
            try:
                raw = r.get(f"upl:{upl_id}")
                if raw:
                    return json.loads(raw)
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            row = self._mem.get(upl_id)
            if not row:
                return None
            if row[0] < time.time():
                self._mem.pop(upl_id, None)
                return None
            return row[1]

    def delete(self, upl_id: str) -> None:
        r = self._redis()
        if r is not None:
            try:
                r.delete(f"upl:{upl_id}")
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._mem.pop(upl_id, None)

    def count_recent(self, owner: str, window: int) -> int:
        """Сколько файлов владелец загрузил за окно (лимит от спама)."""
        key = f"uplrate:{owner}"
        r = self._redis()
        if r is not None:
            try:
                pipe = r.pipeline()
                pipe.incr(key)
                pipe.expire(key, window)
                n, _ = pipe.execute()
                return int(n)
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            until, meta = self._mem.get(key, (0.0, {"n": 0}))
            if until < time.time():
                meta = {"n": 0}
                until = time.time() + window
            meta["n"] = int(meta.get("n", 0)) + 1
            self._mem[key] = (until, meta)
            return meta["n"]

    def _gc(self) -> None:
        now = time.time()
        for k in [k for k, (until, _) in self._mem.items() if until < now]:
            self._mem.pop(k, None)


# ───────────────────────── хранение байтов ─────────────────────────

def _default_save(key: str, data: bytes, mime: str) -> str:
    import media_store
    return media_store.upload_bytes(key, data, mime)


def _default_presign(stored: str, expires: int) -> str:
    import media_store
    return media_store.presign(stored, expires=expires)


def _default_read_local(stored: str) -> Optional[bytes]:
    root = os.path.dirname(os.path.abspath(__file__))
    path = os.path.normpath(os.path.join(root, stored.lstrip("/")))
    if not path.startswith(os.path.join(root, "media")):
        return None
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _default_delete_local(stored: str) -> None:
    data_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
    path = os.path.normpath(os.path.join(os.path.dirname(data_root), stored.lstrip("/")))
    if path.startswith(data_root):
        try:
            os.remove(path)
        except OSError:
            pass


@dataclass
class Storage:
    save: Callable[[str, bytes, str], str] = _default_save
    presign: Callable[[str, int], str] = _default_presign
    read_local: Callable[[str], Optional[bytes]] = _default_read_local
    delete_local: Callable[[str], None] = _default_delete_local


# ───────────────────────── владелец ─────────────────────────

def _owner_for_new() -> str:
    uid = session.get("user_id")
    if uid:
        return f"u:{uid}"
    tok = session.get("upl_guest")
    if not tok:
        tok = secrets.token_hex(12)
        session["upl_guest"] = tok
    return f"g:{tok}"


def current_owners() -> set[str]:
    owners = set()
    uid = session.get("user_id")
    if uid:
        owners.add(f"u:{uid}")
    tok = session.get("upl_guest")
    if tok:
        owners.add(f"g:{tok}")
    return owners


def _public_base() -> str:
    base = (os.getenv("PUBLIC_BASE_URL") or os.getenv("BASE_URL") or "").strip().rstrip("/")
    if not base:
        return ""
    if re.match(r"^https?://(localhost|127\.|0\.0\.0\.0|\[::1\])", base):
        return ""  # провайдер не достучится до локальной машины
    return base


# ───────────────────────── /api/generate: номер → ссылка ─────────────────────────

def _ext():
    ext = current_app.extensions.get("uploads")
    if ext is None:
        raise UploadError("uploads_disabled", 503)
    return ext


def _provider_url(meta: dict, storage: Storage) -> str:
    stored = meta["stored"]
    if stored.startswith("s3://"):
        return storage.presign(stored, int(os.getenv("UPLOAD_PRESIGN_SEC") or 24 * 3600))
    if stored.startswith(("http://", "https://")):
        return stored
    base = _public_base()
    if base:
        return base + stored
    data = storage.read_local(stored)
    if data is None:
        raise UploadError("upload_expired", 410, "файл больше недоступен — прикрепите заново")
    inline_max = _env_mb("UPLOAD_INLINE_MAX_MB", 20)
    if len(data) > inline_max:
        raise UploadError("media_not_reachable", 503,
                          "задайте PUBLIC_BASE_URL или S3, чтобы провайдер мог скачать большой файл")
    return f"data:{meta['mime']};base64,{base64.b64encode(data).decode('ascii')}"


def resolve_media_ref(value: Optional[str], kind: str, owners: Iterable[str],
                      store: MetaStore, storage: Storage) -> Optional[str]:
    """Значение поля image/audio/video из /api/generate → то, что уходит провайдеру."""
    v = (value or "").strip()
    if not v:
        return None
    if v.startswith("upl_"):
        if not ID_RE.match(v):
            raise UploadError("bad_media_ref", 400)
        meta = store.get(v)
        if not meta:
            raise UploadError("upload_expired", 410, "файл больше недоступен — прикрепите заново")
        if meta.get("owner") not in set(owners):
            raise UploadError("upload_not_found", 404)
        if meta.get("kind") != kind:
            raise UploadError("upload_wrong_kind", 400, f"{meta.get('kind')} в поле {kind}")
        return _provider_url(meta, storage)
    if v.startswith("data:"):
        head = v[5:40].lower()
        if not head.startswith(kind + "/") and not (kind == "audio" and head.startswith("video/webm")):
            raise UploadError("upload_wrong_kind", 400, f"data URL не {kind}")
        approx = (len(v) - v.find(",") - 1) * 3 // 4
        if approx > limits()[kind]:
            raise UploadError("file_too_large", 413, max_mb=limits()[kind] // (1024 * 1024))
        return v
    if v.startswith(("http://", "https://")):
        if (os.getenv("UPLOAD_ALLOW_REMOTE_URLS") or "").strip() in {"1", "true", "yes"}:
            return v
        raise UploadError("bad_media_ref", 400, "используйте /api/uploads")
    raise UploadError("bad_media_ref", 400)


def resolve_generate_media(spec: dict, image: Optional[str], audio: Optional[str],
                           video: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Для api_generate: разрешает номера файлов, отбрасывает то, что модель не принимает."""
    accepts = set(spec.get("inputs") or [])
    if not any((image, audio, video)):
        return image, audio, video
    ext = _ext()
    owners = current_owners()
    out = []
    for kind, val in (("image", image), ("audio", audio), ("video", video)):
        if not (val or "").strip():
            out.append(None)
            continue
        if kind not in accepts:
            log.info("uploads: %s dropped for model %s (inputs=%s)", kind, spec.get("id"), sorted(accepts))
            out.append(None)
            continue
        out.append(resolve_media_ref(val, kind, owners, ext["store"], ext["storage"]))
    return out[0], out[1], out[2]


# ───────────────────────── маршруты ─────────────────────────

def _public_meta(meta: dict, storage: Storage) -> dict:
    stored = meta["stored"]
    if stored.startswith("s3://"):
        preview = storage.presign(stored, 3600)
    else:
        preview = stored
    return {
        "id": meta["id"],
        "kind": meta["kind"],
        "mime": meta["mime"],
        "size": meta["size"],
        "name": meta["name"],
        "width": meta.get("width") or None,
        "height": meta.get("height") or None,
        "preview_url": preview,
        "expires_at": meta["expires_at"],
    }


def _safe_name(name: str) -> str:
    name = os.path.basename(name or "").strip() or "file"
    name = re.sub(r"[\x00-\x1f<>\"\\/|?*]", "_", name)
    return name[:120]


def register_uploads(app: Flask, *, redis_fn: Optional[Callable[[], Any]] = None,
                     storage: Optional[Storage] = None) -> None:
    app.extensions["uploads"] = {"store": MetaStore(redis_fn), "storage": storage or Storage()}

    @app.post("/api/uploads")
    def api_uploads_create():
        store, storage = _ext()["store"], _ext()["storage"]
        lim = limits()
        biggest = max(lim.values())
        if request.content_length and request.content_length > biggest + 1024 * 1024:
            return jsonify({"error": "file_too_large", "max_mb": biggest // (1024 * 1024)}), 413
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "no_file"}), 400

        owner = _owner_for_new()
        window = int(os.getenv("UPLOAD_RATE_WINDOW_SEC") or 600)
        if store.count_recent(owner, window) > int(os.getenv("UPLOAD_RATE_LIMIT") or 40):
            return jsonify({"error": "rate_limited", "retry_after": window}), 429

        data = f.stream.read(biggest + 1)
        if not data:
            return jsonify({"error": "empty_file"}), 400
        sn = sniff(data[:64], f.mimetype or "")
        if sn is None:
            return jsonify({"error": "unsupported_type",
                            "detail": "подходят JPG, PNG, WebP, GIF, MP3, WAV, M4A, OGG, FLAC, MP4, MOV, WebM"}), 415
        if len(data) > lim[sn.kind]:
            return jsonify({"error": "file_too_large", "kind": sn.kind,
                            "max_mb": lim[sn.kind] // (1024 * 1024)}), 413
        width = height = 0
        try:
            if sn.kind == "image":
                data, sn, width, height = process_image(data, sn)
        except UploadError as exc:
            return jsonify(exc.to_dict()), exc.status

        upl_id = "upl_" + secrets.token_hex(12)
        key = time.strftime("uploads/%Y/%m/%d/") + f"{upl_id}.{sn.ext}"
        try:
            stored = storage.save(key, data, sn.mime)
        except Exception:  # noqa: BLE001
            log.exception("uploads: save failed")
            return jsonify({"error": "storage_unavailable"}), 503

        ttl = ttl_sec()
        meta = {
            "id": upl_id, "owner": owner, "kind": sn.kind, "mime": sn.mime, "size": len(data),
            "name": _safe_name(f.filename), "width": width, "height": height,
            "stored": stored, "created_at": int(time.time()), "expires_at": int(time.time()) + ttl,
        }
        store.put(meta, ttl)
        return jsonify(_public_meta(meta, storage)), 201

    @app.get("/api/uploads/<upl_id>")
    def api_uploads_get(upl_id: str):
        store, storage = _ext()["store"], _ext()["storage"]
        meta = store.get(upl_id) if ID_RE.match(upl_id or "") else None
        if not meta or meta.get("owner") not in current_owners():
            return jsonify({"error": "upload_not_found"}), 404
        return jsonify(_public_meta(meta, storage))

    @app.delete("/api/uploads/<upl_id>")
    def api_uploads_delete(upl_id: str):
        store, storage = _ext()["store"], _ext()["storage"]
        meta = store.get(upl_id) if ID_RE.match(upl_id or "") else None
        if not meta or meta.get("owner") not in current_owners():
            return jsonify({"error": "upload_not_found"}), 404
        store.delete(upl_id)
        if meta["stored"].startswith("/media/"):
            storage.delete_local(meta["stored"])
        return jsonify({"ok": True})
