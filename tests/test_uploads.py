"""Скрепка: /api/uploads (загрузка, проверки, владелец) и разрешение upl_… в /api/generate."""
from __future__ import annotations

import io
import os
import struct
import sys

import pytest
from flask import Flask

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import uploads  # noqa: E402


# ───────────── файлы-образцы ─────────────

def _png(w=8, h=6, color=(255, 0, 0)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "PNG")
    return buf.getvalue()


def _jpeg_with_exif(w=40, h=20, orientation=6) -> bytes:
    from PIL import Image
    img = Image.new("RGB", (w, h), (0, 128, 255))
    exif = img.getexif()
    exif[0x0112] = orientation          # повернуть на 90°
    exif[0x010F] = "PhoneMaker"         # «модель телефона» — должна исчезнуть
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _wav(seconds=0.1) -> bytes:
    n = int(8000 * seconds)
    data = b"\x00\x00" * n
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


def _mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 64


# ───────────── приложение для тестов ─────────────

@pytest.fixture()
def app(tmp_path, monkeypatch):
    for k in ("PUBLIC_BASE_URL", "BASE_URL", "UPLOAD_ALLOW_REMOTE_URLS", "UPLOAD_MAX_IMAGE_MB", "UPLOAD_RATE_LIMIT"):
        monkeypatch.delenv(k, raising=False)
    root = tmp_path

    def save(key, data, mime):
        p = root / "media" / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return "/media/" + key

    def read_local(stored):
        p = root / stored.lstrip("/")
        return p.read_bytes() if p.exists() else None

    def delete_local(stored):
        p = root / stored.lstrip("/")
        if p.exists():
            p.unlink()

    a = Flask(__name__)
    a.config.update(SECRET_KEY="t", TESTING=True)
    uploads.register_uploads(a, storage=uploads.Storage(save=save, presign=lambda s, e: s,
                                                         read_local=read_local, delete_local=delete_local))

    @a.post("/login/<int:uid>")
    def _login(uid):
        from flask import session
        session["user_id"] = uid
        return "ok"

    @a.post("/gen")
    def _gen():
        from flask import jsonify, request
        body = request.get_json()
        spec = {"id": "m", "inputs": body.get("inputs") or ["text", "image"]}
        try:
            img, aud, vid = uploads.resolve_generate_media(spec, body.get("image"), body.get("audio"), body.get("video"))
        except uploads.UploadError as exc:
            return jsonify(exc.to_dict()), exc.status
        return jsonify({"image": img, "audio": aud, "video": vid})

    a.root_dir = root
    return a


def _up(c, data, name="a.png", mime="image/png"):
    return c.post("/api/uploads", data={"file": (io.BytesIO(data), name, mime)}, content_type="multipart/form-data")


# ───────────── распознавание типа ─────────────

@pytest.mark.parametrize("data,kind,mime", [
    (b"\xff\xd8\xff\xe0" + b"0" * 20, "image", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n" + b"0" * 20, "image", "image/png"),
    (b"GIF89a" + b"0" * 20, "image", "image/gif"),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image", "image/webp"),
    (b"RIFF\x00\x00\x00\x00WAVEfmt ", "audio", "audio/wav"),
    (b"ID3\x03" + b"0" * 20, "audio", "audio/mpeg"),
    (b"\xff\xfb\x90\x00" + b"0" * 20, "audio", "audio/mpeg"),
    (b"OggS" + b"0" * 20, "audio", "audio/ogg"),
    (b"fLaC" + b"0" * 20, "audio", "audio/flac"),
    (b"\x00\x00\x00\x20ftypM4A " + b"0" * 20, "audio", "audio/mp4"),
    (b"\x00\x00\x00\x20ftypisom" + b"0" * 20, "video", "video/mp4"),
    (b"\x00\x00\x00\x14ftypqt  " + b"0" * 20, "video", "video/quicktime"),
    (b"\x1a\x45\xdf\xa3" + b"0" * 20, "video", "video/webm"),
])
def test_sniff_by_content(data, kind, mime):
    sn = uploads.sniff(data)
    assert sn and sn.kind == kind and sn.mime == mime


def test_sniff_webm_audio_by_declared_mime_and_rejects_unknown():
    assert uploads.sniff(b"\x1a\x45\xdf\xa3....", "audio/webm").kind == "audio"
    assert uploads.sniff(b"%PDF-1.7 hello") is None
    assert uploads.sniff(b"MZ\x90\x00 exe") is None


# ───────────── загрузка ─────────────

def test_upload_image_returns_id_and_saves(app):
    c = app.test_client()
    r = _up(c, _png(8, 6))
    assert r.status_code == 201, r.get_json()
    d = r.get_json()
    assert d["id"].startswith("upl_") and d["kind"] == "image" and d["mime"] == "image/png"
    assert (d["width"], d["height"]) == (8, 6)
    assert d["preview_url"].startswith("/media/uploads/")
    assert (app.root_dir / d["preview_url"].lstrip("/")).exists()


def test_type_is_checked_by_content_not_name(app):
    c = app.test_client()
    r = _up(c, b"%PDF-1.7 not an image", name="photo.png", mime="image/png")
    assert r.status_code == 415 and r.get_json()["error"] == "unsupported_type"
    r = _up(c, _wav(), name="voice.png", mime="image/png")   # имя врёт — тип всё равно audio
    assert r.status_code == 201 and r.get_json()["kind"] == "audio"


def test_broken_image_and_heic_rejected(app):
    c = app.test_client()
    r = _up(c, b"\x89PNG\r\n\x1a\n" + b"garbage" * 10)
    assert r.status_code == 400 and r.get_json()["error"] == "bad_file"
    r = _up(c, b"\x00\x00\x00\x18ftypheic" + b"0" * 40, name="a.heic", mime="image/heic")
    assert r.status_code == 415 and r.get_json()["error"] == "heic_unsupported"


def test_size_limit_per_kind(app, monkeypatch):
    monkeypatch.setenv("UPLOAD_MAX_IMAGE_MB", "0.001")   # ~1 КБ
    c = app.test_client()
    r = _up(c, _png(200, 200, (10, 20, 30)) + b"\x00" * 4096)
    assert r.status_code == 413
    assert r.get_json()["error"] == "file_too_large" and r.get_json()["kind"] == "image"


def test_exif_rotated_and_metadata_removed(app):
    from PIL import Image
    c = app.test_client()
    r = _up(c, _jpeg_with_exif(40, 20, orientation=6), name="p.jpg", mime="image/jpeg")
    d = r.get_json()
    assert r.status_code == 201
    assert (d["width"], d["height"]) == (20, 40)           # повёрнуто
    saved = Image.open(app.root_dir / d["preview_url"].lstrip("/"))
    assert not dict(saved.getexif())                        # EXIF пуст


def test_huge_image_downscaled(app, monkeypatch):
    monkeypatch.setenv("UPLOAD_IMAGE_MAX_SIDE", "100")
    c = app.test_client()
    d = _up(c, _png(400, 200)).get_json()
    assert (d["width"], d["height"]) == (100, 50)


def test_empty_and_missing_file(app):
    c = app.test_client()
    assert c.post("/api/uploads", data={}, content_type="multipart/form-data").get_json()["error"] == "no_file"
    assert _up(c, b"").get_json()["error"] == "empty_file"


def test_rate_limit(app, monkeypatch):
    monkeypatch.setenv("UPLOAD_RATE_LIMIT", "2")
    c = app.test_client()
    assert _up(c, _png()).status_code == 201
    assert _up(c, _png()).status_code == 201
    r = _up(c, _png())
    assert r.status_code == 429 and r.get_json()["error"] == "rate_limited"


# ───────────── владелец ─────────────

def test_only_owner_can_see_and_delete(app):
    a, b = app.test_client(), app.test_client()
    upl = _up(a, _png()).get_json()["id"]
    assert a.get(f"/api/uploads/{upl}").status_code == 200
    assert b.get(f"/api/uploads/{upl}").status_code == 404
    assert b.delete(f"/api/uploads/{upl}").status_code == 404
    assert a.delete(f"/api/uploads/{upl}").status_code == 200
    assert a.get(f"/api/uploads/{upl}").status_code == 404


def test_guest_upload_survives_login(app):
    c = app.test_client()
    upl = _up(c, _png()).get_json()["id"]       # гость прикрепил
    c.post("/login/7")                           # потом вошёл
    r = c.post("/gen", json={"image": upl})
    assert r.status_code == 200 and r.get_json()["image"].startswith("data:image/png;base64,")


def test_user_upload_visible_from_other_session_of_same_user(app):
    a, b = app.test_client(), app.test_client()
    a.post("/login/5"); b.post("/login/5")
    upl = _up(a, _png()).get_json()["id"]
    assert b.post("/gen", json={"image": upl}).status_code == 200
    c = app.test_client(); c.post("/login/6")
    assert c.post("/gen", json={"image": upl}).get_json()["error"] == "upload_not_found"


# ───────────── /api/generate: номер → ссылка ─────────────

def test_resolve_uses_public_base_url(app, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://ai-shniza.ru/")
    c = app.test_client()
    upl = _up(c, _png()).get_json()["id"]
    url = c.post("/gen", json={"image": upl}).get_json()["image"]
    assert url.startswith("https://ai-shniza.ru/media/uploads/") and url.endswith(".png")


def test_resolve_localhost_base_falls_back_to_data_url(app, monkeypatch):
    monkeypatch.setenv("BASE_URL", "http://127.0.0.1:8000")
    c = app.test_client()
    upl = _up(c, _png()).get_json()["id"]
    assert c.post("/gen", json={"image": upl}).get_json()["image"].startswith("data:image/png;base64,")


def test_resolve_s3_presigned():
    store = uploads.MetaStore()
    meta = {"id": "upl_" + "a" * 24, "owner": "u:1", "kind": "image", "mime": "image/png", "stored": "s3://b/k.png"}
    store.put(meta, 60)
    st = uploads.Storage(presign=lambda s, e: f"https://s3/signed?{s}&e={e}")
    url = uploads.resolve_media_ref(meta["id"], "image", {"u:1"}, store, st)
    assert url.startswith("https://s3/signed?s3://b/k.png")


def test_resolve_errors(app):
    c = app.test_client()
    img = _up(c, _png()).get_json()["id"]
    aud = _up(c, _wav(), name="a.wav", mime="audio/wav").get_json()["id"]
    assert c.post("/gen", json={"image": "upl_" + "f" * 24}).get_json()["error"] == "upload_expired"
    assert c.post("/gen", json={"image": "upl_bad"}).get_json()["error"] == "bad_media_ref"
    r = c.post("/gen", json={"image": aud})
    assert r.status_code == 400 and r.get_json()["error"] == "upload_wrong_kind"
    r = c.post("/gen", json={"image": "https://evil.example/x.png"})
    assert r.status_code == 400 and r.get_json()["error"] == "bad_media_ref"
    assert c.post("/gen", json={"image": img}).status_code == 200


def test_media_model_does_not_accept_is_dropped(app):
    c = app.test_client()
    aud = _up(c, _wav(), name="a.wav", mime="audio/wav").get_json()["id"]
    d = c.post("/gen", json={"audio": aud, "inputs": ["text", "image"]}).get_json()
    assert d["audio"] is None
    d = c.post("/gen", json={"audio": aud, "inputs": ["text", "image", "audio"]}).get_json()
    assert d["audio"].startswith("data:audio/wav;base64,")


def test_legacy_data_url_still_works_and_is_checked(app):
    c = app.test_client()
    ok = "data:image/png;base64,iVBORw0KGgo="
    assert c.post("/gen", json={"image": ok}).get_json()["image"] == ok
    assert c.post("/gen", json={"image": "data:audio/wav;base64,AAAA"}).get_json()["error"] == "upload_wrong_kind"


def test_remote_urls_only_when_allowed(app, monkeypatch):
    monkeypatch.setenv("UPLOAD_ALLOW_REMOTE_URLS", "1")
    c = app.test_client()
    assert c.post("/gen", json={"image": "https://cdn.example/x.png"}).get_json()["image"] == "https://cdn.example/x.png"


def test_metastore_redis_failure_falls_back_to_memory():
    class Broken:
        def set(self, *a, **k): raise RuntimeError("down")
        def get(self, *a, **k): raise RuntimeError("down")
        def delete(self, *a, **k): raise RuntimeError("down")
    s = uploads.MetaStore(lambda: Broken())
    s.put({"id": "upl_x"}, 60)
    assert s.get("upl_x") == {"id": "upl_x"}
