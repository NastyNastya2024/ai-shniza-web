"""Object storage helpers + watermark (Pillow/ffmpeg)."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from typing import Optional, Tuple
from urllib.parse import urlparse

DOMAIN = os.getenv("DOMAIN") or "ai-shniza.ru"
EGG_PATH = os.path.join(os.path.dirname(__file__), "img", "egg-logo-glazunya-v3.png")


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
