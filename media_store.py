"""Object storage helpers + watermark / publish compress (Pillow/ffmpeg).

Video quality policy:
  • Generation / draft: keep original provider quality (original_url).
  • Publish to showcase: write a public copy (~1/PUBLISH_VIDEO_SIZE_RATIO of bytes)
    into watermarked_url. Owner download still uses original_url.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
from typing import Optional, Tuple
from urllib.parse import urlparse

DOMAIN = os.getenv("DOMAIN") or "ai-shniza.ru"
EGG_PATH = os.path.join(os.path.dirname(__file__), "img", "egg-logo-glazunya-v3.png")
# Showcase public videos are ~1/N of the original byte size.
PUBLISH_VIDEO_SIZE_RATIO = float(os.getenv("PUBLISH_VIDEO_SIZE_RATIO") or "5")
_COMPRESS_MARKER = ".aish-pub3"


def s3_enabled() -> bool:
    return bool(os.getenv("S3_ACCESS_KEY") and os.getenv("S3_SECRET_KEY") and os.getenv("S3_BUCKET"))


def _s3_client():
    import boto3
    from botocore.client import Config

    return boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT") or "https://storage.yandexcloud.net",
        region_name=os.getenv("S3_REGION") or "ru-central1",
        aws_access_key_id=os.getenv("S3_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("S3_SECRET_KEY"),
        config=Config(signature_version="s3v4"),
    )


def upload_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    if not s3_enabled():
        # local fallback under media/
        root = os.path.join(os.path.dirname(__file__), "media")
        os.makedirs(os.path.dirname(os.path.join(root, key)), exist_ok=True)
        path = os.path.join(root, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return f"/media/{key}"
    client = _s3_client()
    bucket = os.getenv("S3_BUCKET")
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    return f"s3://{bucket}/{key}"


def presign(key_or_url: str, expires: int = 3600) -> str:
    if key_or_url.startswith("/media/"):
        return key_or_url
    if not key_or_url.startswith("s3://") or not s3_enabled():
        return key_or_url
    _, _, rest = key_or_url.partition("s3://")
    bucket, _, key = rest.partition("/")
    client = _s3_client()
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires
    )


def watermark_image(src_bytes: bytes, handle: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    im = Image.open(io.BytesIO(src_bytes)).convert("RGBA")
    w, h = im.size
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    margin_x = int(w * 0.03)
    margin_y = int(h * 0.03)
    egg_w = max(24, int(w * 0.06))
    try:
        egg = Image.open(EGG_PATH).convert("RGBA")
        ratio = egg_w / egg.width
        egg = egg.resize((egg_w, max(1, int(egg.height * ratio))), Image.Resampling.LANCZOS)
    except Exception:
        egg = Image.new("RGBA", (egg_w, egg_w), (255, 200, 80, 200))
    text1 = "{AI}-шница"
    text2 = f"@{handle or 'creator'} · {DOMAIN}"
    try:
        font1 = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", max(12, egg_w // 3))
        font2 = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", max(10, egg_w // 4))
    except Exception:
        font1 = ImageFont.load_default()
        font2 = font1
    tx = w - margin_x - egg_w - 8 - max(draw.textlength(text1, font=font1), draw.textlength(text2, font=font2))
    ty = h - margin_y - egg.height
    # soft shadow
    for dx, dy in ((1, 1), (2, 2)):
        draw.text((tx + egg_w + 8 + dx, ty + dy), text1, fill=(0, 0, 0, 90), font=font1)
        draw.text((tx + egg_w + 8 + dx, ty + egg_w // 2 + dy), text2, fill=(0, 0, 0, 90), font=font2)
    draw.text((tx + egg_w + 8, ty), text1, fill=(255, 255, 255, 180), font=font1)
    draw.text((tx + egg_w + 8, ty + egg_w // 2), text2, fill=(255, 255, 255, 180), font=font2)
    overlay.paste(egg, (int(tx), int(ty)), egg)
    out = Image.alpha_composite(im, overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def watermark_video(src_path: str, handle: str, out_path: str) -> bool:
    """Burn watermark using ffmpeg if available; else copy original."""
    if not shutil.which("ffmpeg"):
        shutil.copyfile(src_path, out_path)
        return False
    # Create a small PNG overlay via Pillow then overlay with ffmpeg
    from PIL import Image, ImageDraw, ImageFont

    canvas = Image.new("RGBA", (640, 120), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    try:
        egg = Image.open(EGG_PATH).convert("RGBA").resize((48, 48), Image.Resampling.LANCZOS)
    except Exception:
        egg = Image.new("RGBA", (48, 48), (255, 200, 80, 200))
    canvas.paste(egg, (8, 36), egg)
    try:
        font1 = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 22)
        font2 = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 16)
    except Exception:
        font1 = ImageFont.load_default()
        font2 = font1
    draw.text((64, 28), "{AI}-шница", fill=(255, 255, 255, 180), font=font1)
    draw.text((64, 58), f"@{handle or 'creator'} · {DOMAIN}", fill=(255, 255, 255, 180), font=font2)
    overlay_path = out_path + ".wm.png"
    canvas.save(overlay_path)
    cmd = [
        "ffmpeg", "-y", "-i", src_path, "-i", overlay_path,
        "-filter_complex", "overlay=W-w-W*0.03:H-h-H*0.03",
        "-codec:a", "copy", out_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        return True
    except Exception:
        shutil.copyfile(src_path, out_path)
        return False
    finally:
        try:
            os.remove(overlay_path)
        except OSError:
            pass


def download_url_to_bytes(url: str) -> Optional[bytes]:
    if not url:
        return None
    if url.startswith("/media/"):
        path = os.path.join(os.path.dirname(__file__), url.lstrip("/"))
        with open(path, "rb") as fh:
            return fh.read()
    import requests

    r = requests.get(presign(url) if url.startswith("s3://") else url, timeout=60)
    r.raise_for_status()
    return r.content


def _ffprobe_json(path: str) -> dict:
    if not shutil.which("ffprobe"):
        return {}
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration,bit_rate,size",
                "-show_entries", "stream=codec_type,codec_name,bit_rate,width,height",
                "-of", "json", path,
            ],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if proc.returncode != 0:
            return {}
        return json.loads(proc.stdout or "{}")
    except Exception:
        return {}


def _has_audio_stream(probe: dict) -> bool:
    for s in probe.get("streams") or []:
        if (s or {}).get("codec_type") == "audio":
            return True
    return False


def compress_video_for_publish(
    src_path: str,
    out_path: str,
    size_ratio: float | None = None,
) -> bool:
    """Re-encode so output is about 1/size_ratio of source bytes.

    Returns True if out_path was written (compressed or copied as fallback).
    Does not modify src_path. Skips work if a sibling marker says already done
    and out_path == src_path (in-place batch); for distinct out_path always encodes.
    """
    ratio = float(size_ratio if size_ratio is not None else PUBLISH_VIDEO_SIZE_RATIO)
    if ratio < 1.2:
        ratio = 1.2
    if not os.path.isfile(src_path):
        return False
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if not shutil.which("ffmpeg"):
        if os.path.abspath(src_path) != os.path.abspath(out_path):
            shutil.copyfile(src_path, out_path)
        return False

    src_size = os.path.getsize(src_path)
    probe = _ffprobe_json(src_path)
    fmt = probe.get("format") or {}
    try:
        duration = float(fmt.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0.05:
        duration = 1.0

    # Target average bitrate for the whole file (bits/s), then reserve audio.
    target_total_bps = max(200_000, int(src_size * 8 / duration / ratio))
    audio_bps = 96_000 if _has_audio_stream(probe) else 0
    video_bps = max(180_000, target_total_bps - audio_bps)

    ext = os.path.splitext(out_path)[1].lower() or ".mp4"
    # Keep a real media extension so ffmpeg can pick a muxer (not "*.mp4.tmp").
    tmp_out = out_path + ".aish-tmp" + ext
    try:
        if ext == ".webm":
            cmd = [
                "ffmpeg", "-y", "-i", src_path,
                "-c:v", "libvpx-vp9", "-b:v", str(video_bps),
                "-row-mt", "1", "-deadline", "good", "-cpu-used", "2",
            ]
            if audio_bps:
                cmd += ["-c:a", "libopus", "-b:a", str(audio_bps)]
            else:
                cmd += ["-an"]
            cmd.append(tmp_out)
        else:
            cmd = [
                "ffmpeg", "-y", "-i", src_path,
                "-c:v", "libx264", "-preset", "medium",
                "-b:v", str(video_bps),
                "-maxrate", str(int(video_bps * 1.35)),
                "-bufsize", str(int(video_bps * 2.5)),
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
            ]
            if audio_bps:
                cmd += ["-c:a", "aac", "-b:a", str(audio_bps)]
            else:
                cmd += ["-an"]
            cmd.append(tmp_out)

        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        if not os.path.isfile(tmp_out) or os.path.getsize(tmp_out) < 1024:
            raise RuntimeError("empty compress output")
        # Only keep if we actually saved space (or matched target band).
        new_size = os.path.getsize(tmp_out)
        if new_size >= src_size * 0.92:
            # Already compact — keep source bytes for out.
            if os.path.abspath(src_path) != os.path.abspath(out_path):
                shutil.copyfile(src_path, out_path)
            try:
                os.remove(tmp_out)
            except OSError:
                pass
            return True
        os.replace(tmp_out, out_path)
        return True
    except Exception:
        try:
            if os.path.isfile(tmp_out):
                os.remove(tmp_out)
        except OSError:
            pass
        if os.path.abspath(src_path) != os.path.abspath(out_path):
            shutil.copyfile(src_path, out_path)
            return True
        return False


def compress_video_bytes(src_bytes: bytes, size_ratio: float | None = None, suffix: str = ".mp4") -> bytes:
    """Compress in-memory video for publish; returns compressed bytes (or original on failure)."""
    if not src_bytes:
        return src_bytes
    with tempfile.TemporaryDirectory(prefix="aish-vpub-") as td:
        src = os.path.join(td, "src" + (suffix if suffix.startswith(".") else "." + suffix))
        out = os.path.join(td, "out.mp4" if suffix.lower() != ".webm" else "out.webm")
        with open(src, "wb") as fh:
            fh.write(src_bytes)
        ok = compress_video_for_publish(src, out, size_ratio=size_ratio)
        if ok and os.path.isfile(out):
            with open(out, "rb") as fh:
                return fh.read()
        return src_bytes


def _marker_original_bytes(marker_path: str) -> int | None:
    """Read original (pre-compress) byte size from sibling marker, if present."""
    if not os.path.isfile(marker_path):
        return None
    try:
        text = open(marker_path, encoding="utf-8").read()
    except OSError:
        return None
    for part in text.replace("\n", " ").split():
        if part.startswith("old="):
            try:
                return int(part.split("=", 1)[1])
            except ValueError:
                return None
    return None


def compress_video_file_inplace(path: str, size_ratio: float | None = None) -> tuple[bool, int, int]:
    """In-place compress for static showcase files. Returns (changed, old_size, new_size).

    Writes a sibling marker ``{path}.aish-pub3`` so re-runs are no-ops.
    """
    marker = path + _COMPRESS_MARKER
    if not os.path.isfile(path):
        return False, 0, 0
    old = os.path.getsize(path)
    if os.path.isfile(marker):
        return False, old, old
    ext = os.path.splitext(path)[1].lower() or ".mp4"
    tmp = path + ".aish-reenc" + ext
    ok = compress_video_for_publish(path, tmp, size_ratio=size_ratio)
    if not ok or not os.path.isfile(tmp):
        return False, old, old
    new = os.path.getsize(tmp)
    if new >= old * 0.92:
        try:
            os.remove(tmp)
        except OSError:
            pass
        # Still mark so we don't keep retrying already-compact files.
        try:
            with open(marker, "w", encoding="utf-8") as fh:
                fh.write(f"skip compact old={old}\n")
        except OSError:
            pass
        return False, old, old
    os.replace(tmp, path)
    try:
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(f"ratio={size_ratio or PUBLISH_VIDEO_SIZE_RATIO} old={old} new={new}\n")
    except OSError:
        pass
    return True, old, new


def retarget_showcase_video(path: str, size_ratio: float | None = None) -> tuple[bool, int, int, int]:
    """Nudge an already-compressed showcase file toward original/size_ratio.

    Uses marker ``old=`` as the true original size when present. Returns
    ``(changed, original_bytes, before, after)``.
    """
    ratio = float(size_ratio if size_ratio is not None else PUBLISH_VIDEO_SIZE_RATIO)
    if ratio < 1.2:
        ratio = 1.2
    marker = path + _COMPRESS_MARKER
    if not os.path.isfile(path):
        return False, 0, 0, 0
    before = os.path.getsize(path)
    original = _marker_original_bytes(marker) or before
    target = max(32_000, int(original / ratio))
    if before <= int(target * 1.08):
        try:
            with open(marker, "w", encoding="utf-8") as fh:
                fh.write(f"ratio={ratio} old={original} new={before}\n")
        except OSError:
            pass
        return False, original, before, before
    # Extra shrink factor from current file toward absolute target.
    pass_ratio = max(1.15, before / float(target))
    ext = os.path.splitext(path)[1].lower() or ".mp4"
    tmp = path + ".aish-reenc" + ext
    ok = compress_video_for_publish(path, tmp, size_ratio=pass_ratio)
    if not ok or not os.path.isfile(tmp):
        return False, original, before, before
    after = os.path.getsize(tmp)
    if after >= before * 0.97:
        try:
            os.remove(tmp)
        except OSError:
            pass
        try:
            with open(marker, "w", encoding="utf-8") as fh:
                fh.write(f"ratio={ratio} old={original} new={before}\n")
        except OSError:
            pass
        return False, original, before, before
    os.replace(tmp, path)
    try:
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(f"ratio={ratio} old={original} new={after}\n")
    except OSError:
        pass
    return True, original, before, after


# Alias (exists → inplace)

compress_video_file_exists = compress_video_file_inplace
