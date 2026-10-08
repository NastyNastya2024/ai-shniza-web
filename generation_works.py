"""Генерации студии как «работы» + срок хранения неопубликованных.

Правило: неопубликованная генерация хранится 24 часа (WORKS_UNPUBLISHED_TTL_HOURS), потом удаляются
и файл, и запись. Опубликованная (хотя бы раз — published_at заполнен) хранится, пока её не удалят.
Исходные файлы со скрепки живут те же 24 часа (UPLOAD_TTL_SEC в uploads.py).

Что делает модуль:
  • record_generation(job_id, public, owner_id, prompt, params) — когда /api/generate/jobs/<id> отдаёт
    «готово», создаёт Work (status="draft", job_id) один раз на задание и возвращает его. Ссылку провайдера
    (Replicate удаляет файлы через час) в фоне копирует в наше хранилище (media_store) — чтобы 24 часа
    и публикация были правдой.
  • purge_unpublished() — удаляет неопубликованные работы старше срока: файл в S3 / media/, лайки, запись.
    Запускается лениво (не чаще раза в 10 минут на процесс) и командой:
        flask --app server purge-unpublished-works [--dry-run]
  • expires_at(work) — когда работа удалится (None — опубликована и не удалится).
  • purge_local_uploads() — исходные файлы со скрепки в media/uploads/ старше UPLOAD_TTL_SEC (24 ч) удаляются
    той же чисткой. В S3 эти файлы удаляет правило жизненного цикла бакета на префикс uploads/ (1 день).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlparse

log = logging.getLogger(__name__)

MEDIA_KINDS = {"image", "video", "audio"}
EXT = {"image": "png", "video": "mp4", "audio": "mp3"}
MIME = {"image": "image/png", "video": "video/mp4", "audio": "audio/mpeg"}
PURGE_EVERY_SEC = 600


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def ttl_hours() -> int:
    try:
        v = int(os.getenv("WORKS_UNPUBLISHED_TTL_HOURS") or 24)
    except ValueError:
        v = 24
    return max(1, min(24 * 365, v))


def _flag(name: str, default: str = "1") -> bool:
    return (os.getenv(name) or default).strip().lower() not in {"0", "false", "no", "off"}


def is_kept(work: Any) -> bool:
    """Опубликована сейчас или была опубликована — не удаляем."""
    return work.status == "published" or work.published_at is not None


def expires_at(work: Any) -> datetime | None:
    if is_kept(work) or not work.created_at:
        return None
    return work.created_at + timedelta(hours=ttl_hours())


def expires_iso(work: Any) -> str | None:
    dt = expires_at(work)
    return dt.replace(microsecond=0).isoformat() + "Z" if dt else None


def delete_stored(url: str | None) -> bool:
    """Удалить файл, который лежит у нас (s3://… или /media/…). Ссылки провайдеров не трогаем."""
    if not url:
        return False
    try:
        if url.startswith("/media/"):
            import media_store
            root = os.path.realpath(os.path.join(os.path.dirname(media_store.__file__), "media"))
            path = os.path.realpath(os.path.join(os.path.dirname(media_store.__file__), url.lstrip("/")))
            if path.startswith(root + os.sep) and os.path.isfile(path):
                os.remove(path)
                return True
            return False
        if url.startswith("s3://"):
            import media_store
            if not media_store.s3_enabled():
                return False
            bucket, _, key = url[5:].partition("/")
            media_store._s3_client().delete_object(Bucket=bucket, Key=key)
            return True
    except Exception:  # noqa: BLE001
        log.exception("delete stored media failed: %s", url)
    return False


def upload_ttl_sec() -> int:
    try:
        return max(600, int(os.getenv("UPLOAD_TTL_SEC") or 24 * 3600))
    except ValueError:
        return 24 * 3600


def purge_local_uploads(root: str | None = None, now: float | None = None, dry_run: bool = False) -> int:
    """Исходники со скрепки, сохранённые локально (без S3): media/uploads/**, старше UPLOAD_TTL_SEC."""
    if root is None:
        import media_store
        root = os.path.join(os.path.dirname(media_store.__file__), "media", "uploads")
    if not os.path.isdir(root):
        return 0
    cutoff = (now or time.time()) - upload_ttl_sec()
    n = 0
    for dirpath, _dirs, files in os.walk(root, topdown=False):
        for name in files:
            path = os.path.join(dirpath, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    n += 1
                    if not dry_run:
                        os.remove(path)
            except OSError:
                pass
        if not dry_run and dirpath != root:
            try:
                os.rmdir(dirpath)          # пустые папки дней
            except OSError:
                pass
    return n


def register_generation_works(app: Any, db: Any, copy_fn: Callable[[int], None] | None = None) -> dict:
    models = app.extensions.get("product_models") or {}
    Work = models["Work"]
    WorkLike = models.get("WorkLike")
    state = {"last_purge": 0.0}

    def _copy_to_storage(work_id: int) -> None:
        """Скачать результат у провайдера и положить в наше хранилище. Ошибка — не страшно: остаётся ссылка провайдера."""
        import media_store

        with app.app_context():
            work = db.session.get(Work, work_id)
            if not work or not work.original_url or not work.original_url.startswith("http"):
                return
            src = work.original_url
            try:
                raw = media_store.download_url_to_bytes(src)
                if not raw:
                    return
                ext = os.path.splitext(urlparse(src).path)[1].lstrip(".").lower()[:5] or EXT.get(work.kind, "bin")
                key = f"works/{work.owner_id}/{work.id}.{ext}"
                stored = media_store.upload_bytes(key, raw, MIME.get(work.kind, "application/octet-stream"))
                work = db.session.get(Work, work_id)
                if not work:                      # успели удалить — подчищаем
                    delete_stored(stored)
                    return
                work.original_url = stored
                if work.thumb_url == src:
                    work.thumb_url = stored
                db.session.commit()
            except Exception:  # noqa: BLE001
                db.session.rollback()
                log.exception("copy generation %s to storage failed", work_id)

    def _start_copy(work_id: int) -> None:
        if copy_fn is not None:
            copy_fn(work_id)
            return
        if not _flag("WORKS_COPY_RESULTS"):
            return
        threading.Thread(target=_copy_to_storage, args=(work_id,), daemon=True, name=f"work-copy-{work_id}").start()

    def record_generation(job_id: str, public: dict, owner_id: Any, prompt: str = "", params: Any = None):
        """Готовая генерация → Work (один раз на задание). Текстовые ответы работами не считаем."""
        if not owner_id or not job_id or not isinstance(public, dict):
            return None
        kind = str(public.get("kind") or "")
        urls = [u for u in (public.get("urls") or []) if isinstance(u, str) and u.startswith("http")]
        if kind not in MEDIA_KINDS or not urls:
            return None
        work = Work.query.filter_by(job_id=job_id).first()
        if work:
            return work if work.owner_id == owner_id else None
        work = Work(
            owner_id=owner_id,
            kind=kind,
            model_key=str(public.get("model") or "")[:200] or "unknown",
            prompt=(prompt or "")[:4000],
            params=json.dumps(params, ensure_ascii=False) if params else None,
            original_url=urls[0][:700],
            thumb_url=urls[0][:700] if kind == "image" else None,
            status="draft",
            job_id=job_id,
            created_at=_now(),
        )
        db.session.add(work)
        db.session.commit()
        _start_copy(work.id)
        maybe_purge()
        return work

    def purge_unpublished(dry_run: bool = False, now: datetime | None = None) -> int:
        """Удалить неопубликованные работы старше срока. Возвращает, сколько удалено (или удалилось бы)."""
        cutoff = (now or _now()) - timedelta(hours=ttl_hours())
        q = Work.query.filter(Work.status != "published", Work.published_at.is_(None), Work.created_at < cutoff)
        rows = q.limit(5000).all()
        if dry_run:
            return len(rows)
        for w in rows:
            for url in {w.original_url, w.watermarked_url, w.thumb_url}:
                delete_stored(url)
            if WorkLike is not None:
                WorkLike.query.filter_by(work_id=w.id).delete(synchronize_session=False)
            db.session.delete(w)
        db.session.commit()
        if rows:
            log.info("purged %s unpublished works older than %sh", len(rows), ttl_hours())
        return len(rows)

    def maybe_purge() -> None:
        if not _flag("WORKS_PURGE_ENABLED"):
            return
        t = time.time()
        if t - state["last_purge"] < PURGE_EVERY_SEC:
            return
        state["last_purge"] = t
        try:
            purge_local_uploads()
        except Exception:  # noqa: BLE001
            log.exception("purge local uploads failed")
        try:
            purge_unpublished()
        except Exception:  # noqa: BLE001
            db.session.rollback()
            log.exception("purge unpublished works failed")

    try:
        import click

        @app.cli.command("purge-unpublished-works")
        @click.option("--dry-run", is_flag=True, help="Только посчитать, ничего не удалять")
        def purge_cmd(dry_run):
            """Удалить неопубликованные генерации (24 ч) и локальные исходники со скрепки (24 ч)."""
            n = purge_unpublished(dry_run=dry_run)
            u = purge_local_uploads(dry_run=dry_run)
            click.echo(("would delete" if dry_run else "deleted") + f" {n} unpublished works (ttl {ttl_hours()}h)"
                       + f", {u} local upload files (ttl {upload_ttl_sec() // 3600}h)")
    except Exception:  # noqa: BLE001
        pass

    ext = {"record": record_generation, "purge": purge_unpublished, "maybe_purge": maybe_purge,
           "copy": _copy_to_storage, "expires_iso": expires_iso, "_state": state}
    app.extensions["generation_works"] = ext
    return ext
