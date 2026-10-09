from __future__ import annotations

import logging
import math
import os
import re
import json
import time
from dataclasses import dataclass
from typing import List, Tuple

import requests
from flask import Flask, jsonify, redirect, request, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy

from auth import load_env, register_auth
from security import configure_security, apply_rate_limits, ensure_csrf_token
from pricing import list_pricing_public, price_rub_media, get_usd_rub_rate
from assistant_rules import recommend as assistant_recommend
from product_routes import register_product
from uploads import UploadError, register_uploads, resolve_generate_media
from chat_history import register_chat_history
from generation_works import register_generation_works

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "app.db")
load_env(BASE_DIR)

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
configure_security(app)

db = SQLAlchemy(app)

# Models
class Model(db.Model):
    __tablename__ = "models"
    id = db.Column(db.Integer, primary_key=True)
    vendor = db.Column(db.String(120), nullable=False)
    name = db.Column(db.String(200), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500), nullable=False)

class Tag(db.Model):
    __tablename__ = "tags"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)

class ModelTag(db.Model):
    __tablename__ = "model_tags"
    model_id = db.Column(db.Integer, db.ForeignKey("models.id"), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey("tags.id"), primary_key=True)

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    provider = db.Column(db.String(40), nullable=False, default="password")
    provider_id = db.Column(db.String(255), nullable=True, index=True)
    name = db.Column(db.String(200), nullable=True)

# Seed helper - различные изображения для разных типов моделей
SAMPLE_IMAGE = "https://images.unsplash.com/photo-1519681393784-d120267933ba?q=80&w=1600&auto=format&fit=crop"

# Изображения для генерации изображений
IMAGE_GEN_IMAGES = [
    "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?q=80&w=1600&auto=format&fit=crop",  # AI art
    "https://images.unsplash.com/photo-1547036967-23d11aacaee0?q=80&w=1600&auto=format&fit=crop",  # Digital art
    "https://images.unsplash.com/photo-1518709268805-4e9042af2176?q=80&w=1600&auto=format&fit=crop",  # Creative design
    "https://images.unsplash.com/photo-1558618047-3c8c76ca7d13?q=80&w=1600&auto=format&fit=crop",  # Abstract art
]

# Изображения для генерации видео
VIDEO_GEN_IMAGES = [
    "https://images.unsplash.com/photo-1523580494863-6f3031224c94?q=80&w=1600&auto=format&fit=crop",  # Video production
    "https://images.unsplash.com/photo-1574717024653-61fd2cf4d44d?q=80&w=1600&auto=format&fit=crop",  # Film making
    "https://images.unsplash.com/photo-1492691527719-9d1e07e534b4?q=80&w=1600&auto=format&fit=crop",  # Motion graphics
    "https://images.unsplash.com/photo-1578662996442-48f60103fc96?q=80&w=1600&auto=format&fit=crop",  # Video editing
]

# Изображения для генерации музыки
MUSIC_GEN_IMAGES = [
    "https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?q=80&w=1600&auto=format&fit=crop",  # Music production
    "https://images.unsplash.com/photo-1493225457124-a3eb161ffa5f?q=80&w=1600&auto=format&fit=crop",  # Audio mixing
    "https://images.unsplash.com/photo-1571019613454-1cb2f99b2d8b?q=80&w=1600&auto=format&fit=crop",  # Sound design
    "https://images.unsplash.com/photo-1493225457124-a3eb161ffa5f?q=80&w=1600&auto=format&fit=crop",  # Music studio
]

# Изображения для текстовых моделей
TEXT_MODEL_IMAGES = [
    "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?q=80&w=1600&auto=format&fit=crop",  # Writing
    "https://images.unsplash.com/photo-1516321318423-f06f85e504b3?q=80&w=1600&auto=format&fit=crop",  # Text processing
    "https://images.unsplash.com/photo-1434030216411-0b793f4b4173?q=80&w=1600&auto=format&fit=crop",  # Language
]

# Изображения для 3D моделей
THREE_D_IMAGES = [
    "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?q=80&w=1600&auto=format&fit=crop",  # 3D modeling
    "https://images.unsplash.com/photo-1558618047-3c8c76ca7d13?q=80&w=1600&auto=format&fit=crop",  # 3D rendering
    "https://images.unsplash.com/photo-1635070041078-e363dbe005cb?q=80&w=1600&auto=format&fit=crop",  # 3D graphics
]

# Изображения для игровых моделей
GAME_MODEL_IMAGES = [
    "https://images.unsplash.com/photo-1493711662062-fa541adb3fc8?q=80&w=1600&auto=format&fit=crop",  # Game development
    "https://images.unsplash.com/photo-1511512578047-dfb367046420?q=80&w=1600&auto=format&fit=crop",  # Gaming
    "https://images.unsplash.com/photo-1556438064-2d7646166914?q=80&w=1600&auto=format&fit=crop",  # Virtual world
]

DEFAULT_TAGS = [
    "text-to-video", "image-to-video", "1080p", "multi-shot", "video-generation", "audio",
    "game-world-creation", "lip-sync", "text-to-image", "image-generation", "inpainting",
    "text-rendering", "design", "music-generation"
]

# Featured priorities (vendor, name)
FEATURED_MODELS = set()

def get_or_create_tag(name: str) -> Tag:
    existing = Tag.query.filter_by(name=name).first()
    if existing:
        return existing
    t = Tag(name=name)
    db.session.add(t)
    db.session.flush()
    return t

def get_image_for_model(tags: List[str], vendor: str, name: str) -> str:
    """Выбирает подходящее изображение на основе тегов модели"""
    import hashlib
    
    # Создаем детерминированный хеш для консистентности
    model_id = f"{vendor}/{name}"
    hash_obj = hashlib.md5(model_id.encode())
    hash_int = int(hash_obj.hexdigest(), 16)
    
    tag_set = set(tags)
    
    # Приоритет выбора изображения по тегам
    if any(tag in tag_set for tag in ["video-generation", "text-to-video", "image-to-video"]):
        return VIDEO_GEN_IMAGES[hash_int % len(VIDEO_GEN_IMAGES)]
    elif any(tag in tag_set for tag in ["music-generation", "audio"]):
        return MUSIC_GEN_IMAGES[hash_int % len(MUSIC_GEN_IMAGES)]
    elif any(tag in tag_set for tag in ["image-generation", "text-to-image", "inpainting"]):
        return IMAGE_GEN_IMAGES[hash_int % len(IMAGE_GEN_IMAGES)]
    elif any(tag in tag_set for tag in ["3d", "game-world-creation"]):
        if "game-world-creation" in tag_set:
            return GAME_MODEL_IMAGES[hash_int % len(GAME_MODEL_IMAGES)]
        else:
            return THREE_D_IMAGES[hash_int % len(THREE_D_IMAGES)]
    elif any(tag in tag_set for tag in ["text-rendering", "design"]):
        return TEXT_MODEL_IMAGES[hash_int % len(TEXT_MODEL_IMAGES)]
    else:
        # Fallback к дефолтному изображению
        return SAMPLE_IMAGE


def add_model_record(vendor: str, name: str, tag_names: List[str], description: str | None = None, image_url: str | None = None) -> Tuple[Model, bool]:
    """Create model if not exists. Returns (model, created)."""
    found = Model.query.filter_by(vendor=vendor, name=name).first()
    if found:
        return found, False
    
    # Выбираем изображение на основе тегов, если не указано конкретное
    if not image_url:
        image_url = get_image_for_model(tag_names, vendor, name)
    
    m = Model(
        vendor=vendor,
        name=name,
        description=(
            description
            or "A pro version of Seedance that offers text-to-video and image-to-video support for 5s or 10s videos, at 480p and 1080p resolution"
        ),
        image_url=image_url,
    )
    db.session.add(m)
    db.session.flush()
    for t in tag_names:
        tag = get_or_create_tag(t)
        db.session.add(ModelTag(model_id=m.id, tag_id=tag.id))
    return m, True


def seed():
    if Model.query.count() > 0:
        return
    db.create_all()

    for name in DEFAULT_TAGS:
        get_or_create_tag(name)

    # Existing demo models
    demo = [
        ("bytedance", "seedance-1-pro", ["text-to-video", "1080p", "multi-shot"], None, None),
        ("bytedance", "seedance-1-lite", ["text-to-video", "image-to-video"], None, None),
        ("openai", "sora-x", ["video-generation", "text-to-video", "1080p"], None, None),
        ("stability", "stable-video", ["image-to-video", "lip-sync"], None, None),
        ("meta", "vidpress", ["video-generation", "audio"], None, None),
        ("runway", "gen3", ["text-to-video", "1080p", "lip-sync"], None, None),
        ("nvidia", "omni-v", ["game-world-creation", "image-generation"], None, None),
        ("google", "imagen-video", ["text-to-image", "image-to-video", "1080p"], None, None),
        ("bytedance", "seedance-1-max", ["text-to-video", "inpainting"], None, None),
        ("bytedance", "seedance-1-mini", ["design", "text-rendering"], None, None),
        ("anthropic", "claude-vision-video", ["video-generation", "audio"], None, None),
        ("xai", "grok-video", ["text-to-video", "1080p"], None, None),
        ("ideogram", "ideogram", ["image-generation"], "Ideogram — image generation model", IMAGE_GEN_IMAGES[0]),
        ("google", "imagen-4", ["image-generation"], "Imagen-4 — image generation model", IMAGE_GEN_IMAGES[1]),
        ("black-forest-labs", "flux-kontext", ["image-generation"], "FluxKontext — image generation model", IMAGE_GEN_IMAGES[2]),
        ("kling", "kling-v2.1", ["video-generation", "text-to-video"], "Kling v2.1 — video generation", VIDEO_GEN_IMAGES[0]),
        ("minimax", "minimax-video", ["video-generation"], "Minimax Video — video generation", VIDEO_GEN_IMAGES[1]),
        ("bytedance", "seedance", ["video-generation", "text-to-video"], "Seedance — video generation", VIDEO_GEN_IMAGES[2]),
        ("google", "veo3-8s", ["video-generation"], "Veo3 (8 секунд) — video generation", VIDEO_GEN_IMAGES[3]),
        ("minimax", "minimax-music", ["music-generation", "audio"], "Minimax Music — music generation", MUSIC_GEN_IMAGES[0]),
        ("meta", "musicgen", ["music-generation", "audio"], "MusicGen — music generation", MUSIC_GEN_IMAGES[1]),
        ("chatterbox", "chatterbox", ["music-generation", "audio"], "Chatterbox — music generation", MUSIC_GEN_IMAGES[2]),
    ]
    for vendor, name, tag_list, desc, img in demo:
        add_model_record(vendor, name, tag_list, desc, img)

    db.session.commit()

# Helpers to normalize tags from Replicate
CANONICAL_MAP = {
    "image": "image-generation",
    "images": "image-generation",
    "text-to-image": "text-to-image",
    "video": "video-generation",
    "videos": "video-generation",
    "text-to-video": "text-to-video",
    "image-to-video": "image-to-video",
    "music": "music-generation",
    "audio": "audio",
}

def derive_tags_from_model_payload(model: dict) -> List[str]:
    tags: set[str] = set()
    for key in ("categories", "modalities", "tags"):
        vals = model.get(key)
        if isinstance(vals, list):
            for raw in vals:
                if not isinstance(raw, str):
                    continue
                s = raw.strip().lower()
                canonical = CANONICAL_MAP.get(s, s)
                tags.add(canonical)
    # Fallbacks by description
    desc = (model.get("description") or "").lower()
    if "video" in desc:
        tags.add("video-generation")
    if "image" in desc:
        tags.add("image-generation")
    if "music" in desc or "audio" in desc:
        tags.add("music-generation")
    return list(tags)

# Serializers

def model_to_dict(m: Model):
    tag_rows = db.session.query(Tag.name).join(ModelTag, Tag.id == ModelTag.tag_id).filter(ModelTag.model_id == m.id).all()
    tags = [t[0] for t in tag_rows if t[0] != "replicate"]
    return {
        "id": m.id,
        "title": m.name,
        "vendor": m.vendor,
        "name": m.name,
        "description": m.description,
        "image_url": m.image_url,
        "tags": tags,
    }

# API Endpoints
@app.route("/api/tags")
def api_tags():
    rows = Tag.query.filter(Tag.name != "replicate").order_by(Tag.name.asc()).all()
    return jsonify([{"id": t.id, "name": t.name} for t in rows])

@app.route("/api/admin/cleanup-replicate-tag", methods=["POST"])
def cleanup_replicate_tag():
    rep = Tag.query.filter_by(name="replicate").first()
    if not rep:
        return jsonify({"removed": 0})
    # delete relations first
    ModelTag.query.filter_by(tag_id=rep.id).delete()
    db.session.delete(rep)
    db.session.commit()
    return jsonify({"removed": 1})

@app.route("/api/models")
def api_models():
    q = request.args.get("q", "").strip().lower()
    tags = request.args.get("tags", "").strip()
    tag_list = [t for t in tags.split(",") if t]
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 12)), 1), 60)

    query = Model.query

    if q:
        like = f"%{q}%"
        query = query.filter((Model.vendor.ilike(like)) | (Model.name.ilike(like)) | (Model.description.ilike(like)))

    if tag_list:
        query = query.join(ModelTag, Model.id == ModelTag.model_id).join(Tag, Tag.id == ModelTag.tag_id).filter(Tag.name.in_(tag_list)).group_by(Model.id)

    # First get all IDs for sorting in Python by quality
    total = query.count()
    rows = query.order_by(Model.vendor.asc(), Model.name.asc()).all()

    def quality_score(m: Model) -> int:
        md = model_to_dict(m)
        tags = md["tags"]
        tag_set = set(tags)
        generic_desc = (m.description or "").strip().lower() in ("", "model from replicate")
        
        # -2 = highest priority - модели с тегом image-generation
        if "image-generation" in tag_set:
            return -2
        
        # -1 = second priority - модели с Replicate изображениями
        if "replicate" in (m.image_url or ""):
            return -1
        
        # 0 = good cards (no 'official', meaningful tags)
        if tags and not generic_desc and "official" not in tag_set:
            return 0
        
        # 1 = contains 'official' anywhere
        if "official" in tag_set:
            return 1
        
        # 2 = worst (no tags OR generic desc)
        return 2

    rows.sort(key=quality_score)
    # paginate after sorting
    start = (page - 1) * per_page
    page_rows = rows[start:start + per_page]
    return jsonify({
        "items": [model_to_dict(m) for m in page_rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    })

@app.route("/api/sync/replicate", methods=["POST"])
def sync_replicate():
    token = os.getenv("REPLICATE_API_TOKEN") or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not token:
        return jsonify({"error": "Missing REPLICATE_API_TOKEN"}), 400

    limit = int(request.args.get("limit", 200))
    imported = 0
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    next_url = "https://api.replicate.com/v1/models"

    while imported < limit and next_url:
        resp = requests.get(next_url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return jsonify({"error": "Replicate API error", "status": resp.status_code, "body": resp.text}), 502
        data = resp.json()
        models = data.get("results", [])
        next_url = data.get("next")  # absolute URL

        for model in models:
            if imported >= limit:
                break
            owner = model.get("owner") or "unknown"
            name = model.get("name") or "model"
            desc = model.get("description") or "Model from Replicate"
            tag_names = derive_tags_from_model_payload(model)
            # Prefer Replicate cover image
            cover = model.get("cover_image_url") or model.get("cover_image")
            # choose image by tags if no cover
            img = cover or SAMPLE_IMAGE
            if not cover:
                if any(t in tag_names for t in ["video-generation", "text-to-video"]):
                    img = VIDEO_GEN_IMAGE
                elif any(t in tag_names for t in ["music-generation", "audio"]):
                    img = MUSIC_GEN_IMAGE
                elif any(t in tag_names for t in ["image-generation", "text-to-image"]):
                    img = IMAGE_GEN_IMAGE

            add_model_record(owner, name, tag_names, desc, img)
            imported += 1

    db.session.commit()
    return jsonify({"imported": imported})

@app.route("/api/sync/replicate/images", methods=["POST"])
def sync_replicate_images():
    """Backfill images for existing models using Replicate cover_image_url."""
    token = os.getenv("REPLICATE_API_TOKEN") or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not token:
        return jsonify({"error": "Missing REPLICATE_API_TOKEN"}), 400
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    updated = 0
    # update only models that have placeholder unsplash images
    candidates = Model.query.all()
    for m in candidates:
        # skip if already seems like a replicate image (heuristic)
        if "replicate" in (m.image_url or ""):
            continue
        try:
            resp = requests.get(f"https://api.replicate.com/v1/models/{m.vendor}/{m.name}", headers=headers, timeout=15)
            if resp.status_code != 200:
                continue
            cover = resp.json().get("cover_image_url") or resp.json().get("cover_image")
            if cover and cover != m.image_url:
                m.image_url = cover
                updated += 1
        except Exception:
            continue
    db.session.commit()
    return jsonify({"updated": updated})

@app.route("/api/admin/update-images", methods=["POST"])
def update_model_images():
    """Обновить изображения для всех моделей на основе их тегов"""
    updated = 0
    models = Model.query.all()
    
    for model in models:
        # Получаем теги модели
        tag_rows = db.session.query(Tag.name).join(ModelTag, Tag.id == ModelTag.tag_id).filter(ModelTag.model_id == model.id).all()
        tags = [t[0] for t in tag_rows if t[0] != "replicate"]
        
        # Выбираем новое изображение на основе тегов
        new_image = get_image_for_model(tags, model.vendor, model.name)
        
        if new_image != model.image_url:
            model.image_url = new_image
            updated += 1
    
    db.session.commit()
    return jsonify({"updated": updated, "total": len(models)})

@app.route("/api/admin/retag-missing", methods=["POST"])
def retag_missing():
    token = os.getenv("REPLICATE_API_TOKEN") or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"} if token else None

    # find models with no tags
    subq = db.session.query(ModelTag.model_id).subquery()
    missing = Model.query.filter(~Model.id.in_(subq)).all()

    updated = 0
    for m in missing:
        tag_names: List[str] = []
        # Try Replicate API if token present
        if headers:
            try:
                resp = requests.get(f"https://api.replicate.com/v1/models/{m.vendor}/{m.name}", headers=headers, timeout=15)
                if resp.status_code == 200:
                    tag_names = derive_tags_from_model_payload(resp.json())
            except Exception:
                pass
        # Text fallbacks
        text = f"{m.vendor} {m.name} {m.description}".lower()
        if "video" in text:
            tag_names.append("video-generation")
        if "image" in text or "imagen" in text:
            tag_names.append("image-generation")
        if "music" in text or "audio" in text:
            tag_names.append("music-generation")
        tag_names = list({t for t in tag_names})
        if not tag_names:
            continue
        for t in tag_names:
            tag = get_or_create_tag(t)
            db.session.add(ModelTag(model_id=m.id, tag_id=tag.id))
        updated += 1
    db.session.commit()
    return jsonify({"retagged_models": updated, "checked": len(missing)})

@app.route("/api/admin/enrich", methods=["POST"])
def admin_enrich():
    token = os.getenv("REPLICATE_API_TOKEN") or request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not token:
        return jsonify({"error": "Missing REPLICATE_API_TOKEN"}), 400
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    KEYWORDS = {
        "photoreal": "photoreal",
        "photo": "photoreal",
        "realistic": "photoreal",
        "anime": "anime",
        "cartoon": "cartoon",
        "3d": "3d",
        "portrait": "portrait",
        "character": "characters",
        "face": "portrait",
        "style": "style",
        "upscale": "upscaler",
        "nsfw": "nsfw",
        "text": "text-rendering",
        "audio": "audio",
        "music": "music-generation",
        "video": "video-generation",
        "image": "image-generation",
    }

    def keywords_to_tags(text: str) -> List[str]:
        text = (text or "").lower()
        found = set()
        for k, tag in KEYWORDS.items():
            if k in text:
                found.add(tag)
        return list(found)

    updated = 0
    for m in Model.query.all():
        try:
            r = requests.get(f"https://api.replicate.com/v1/models/{m.vendor}/{m.name}", headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            payload = r.json()
            # Update description if payload has one and ours is generic/short
            desc = (payload.get("description") or "").strip()
            if desc and (m.description.lower().strip() == "model from replicate" or len(m.description) < 40):
                # take first 220 chars
                short = desc[:220].rstrip()
                m.description = short
            # Tags from payload + keywords
            new_tags = set(derive_tags_from_model_payload(payload)) | set(keywords_to_tags(desc))
            # Add visibility/official if present
            vis = (payload.get("visibility") or "").lower()
            if vis in ("public", "verified", "official"):
                new_tags.add("official")
            for t in new_tags:
                tag = get_or_create_tag(t)
                exists = ModelTag.query.filter_by(model_id=m.id, tag_id=tag.id).first()
                if not exists:
                    db.session.add(ModelTag(model_id=m.id, tag_id=tag.id))
            updated += 1
        except Exception:
            continue
    db.session.commit()
    return jsonify({"enriched": updated})


CHAT_SYSTEM_PROMPT = """
Ты — навигатор «{AI}-шница»: помогаешь выбрать модель из каталога, доработать промпт и не переплатить.

Язык (жёстко):
- Отвечай ТОЛЬКО на языке последнего сообщения пользователя.
- Никогда не переключайся на английский и не смешивай языки.
- Запрещено писать рассуждения, план ответа, цитаты системных правил, фразы вроде
  «According to instructions», «User wants», «We need to ask», «We have already asked».

Длина:
- Рекомендация: максимум 12 коротких строк.
- Не больше 2 моделей. Не больше 1 короткого уточнения за ответ (и только после рекомендации).

Главное при нехватке данных:
- НЕ зацикливайся на вопросах и не повторяй одни и те же 3 пункта.
- Сразу дай 1–2 ближайшие модели из каталога по действию (картинка/видео/музыка)
  и по цене (бесплатно / дешевле → в приоритете).
- Если сказано «бесплатно» / free — бери бесплатные или самые дешёвые с нужным выходом.
- Стартовый промпт обязателен даже при общей теме.

Формат (обязательно):
- ЗАПРЕЩЕНО писать всё одним абзацем.
- Каждый пункт с новой строки. Между блоками — пустая строка.
- Короткий Markdown: ###, списки -.

Шаблон:

Кратко: что делаем (1 строка).

### 1. Название · цена
- Исходники: …
- Почему: …

### 2. Название · цена
- Исходники: …
- Почему: …

## Промпт
1–2 строки стартового промпта

## Дальше
какую модель нажать в боковой панели

Каталог:
- Только модели из блока «КАТАЛОГ LIVE-МОДЕЛЕЙ» ниже.
- Не называй Midjourney / ChatGPT / Sora «снаружи» и сети вне списка.

Оркестрация UI:
- Если выбрана медиа-модель и пользователь ЯВНО просит сгенерировать — в конце строкой:
  GENERATE_NOW: <финальный промпт>
- Для советов GENERATE_NOW не добавляй. Маркер не объясняй.

Этика: отказ от насилия, суицида, экстремизма, буллинга.
При подавленности: 8-800-2000-122 и https://www.iasp.info/suicidalthoughts/ , затем созидание.
""".strip()


def _catalog_for_prompt(max_chars: int = 9000) -> str:
    """Compact live catalog for the navigator system prompt."""
    prices = _integration_prices()
    lines = [
        "КАТАЛОГ LIVE-МОДЕЛЕЙ (рекомендуй только отсюда; поля: id | name | in | out | price):"
    ]
    for spec in INTEGRATED_MODELS.values():
        # Не предлагаем «выбрать ассистента» — чат всегда Omni→резерв
        if spec.get("group") == "assistants" or spec.get("kind") in {"chat", "llm"}:
            continue
        if not _is_studio_visible(spec):
            continue
        mid = spec["id"]
        price = prices.get(mid) or "н/д"
        inputs = ",".join(spec.get("inputs") or [])
        outputs = ",".join(spec.get("outputs") or [])
        lines.append(
            f"- {mid} | {spec.get('name') or mid} | "
            f"in:{inputs} | out:{outputs} | {price}"
        )
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[: max_chars - 20] + "\n… (каталог обрезан)"
    return text


def _build_chat_system_prompt() -> str:
    return f"{CHAT_SYSTEM_PROMPT}\n\n{_catalog_for_prompt()}"


def _with_assistant_persona(user_prompt: str) -> str:
    """Накладывает роль навигатора на любой LLM-ассистент (не только /api/chat)."""
    text = (user_prompt or "").strip()
    return (
        f"[СИСТЕМНАЯ РОЛЬ — соблюдай всегда]\n{_build_chat_system_prompt()}\n\n"
        f"[СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ]\n{text or '(пусто)'}"
    )


def _chat_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False  # не использовать системный HTTP(S)_PROXY
    return session


def _split_generate_now(reply: str) -> tuple[str, str | None]:
    """Strip GENERATE_NOW marker from assistant reply; return (visible_text, prompt|None)."""
    text = (reply or "").strip()
    if not text:
        return "", None
    match = re.search(r"(?im)^GENERATE_NOW:\s*(.+)\s*$", text)
    if not match:
        return text, None
    prompt = (match.group(1) or "").strip() or None
    visible = (text[: match.start()] + text[match.end() :]).strip()
    return visible, prompt


def _compact_chat_reply(reply: str, max_chars: int = 900) -> str:
    """Keep replies short for studio chat UI."""
    text = (reply or "").strip()
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1]
    # Prefer cutting on paragraph / line boundary
    for sep in ("\n\n", "\n", ". ", "! ", "? "):
        idx = cut.rfind(sep)
        if idx >= int(max_chars * 0.55):
            cut = cut[: idx + len(sep)].rstrip()
            break
    return cut.rstrip() + "…"


def _looks_like_chain_of_thought(text: str) -> bool:
    """Reject leaked model reasoning / English meta about the system prompt."""
    t = (text or "").strip()
    if not t:
        return True
    low = t.lower()
    markers = (
        "according to instructions",
        "user wants",
        "we need to",
        "we have already",
        "we should",
        "clarifying questions",
        "system prompt",
        "chain of thought",
    )
    hits = sum(1 for m in markers if m in low)
    if hits >= 2:
        return True
    # Long English reasoning without Cyrillic product answer
    cyr = sum(1 for ch in t if "а" <= ch.lower() <= "я" or ch.lower() == "ё")
    latin = sum(1 for ch in t if "a" <= ch.lower() <= "z")
    if latin > 80 and cyr < 20 and hits >= 1:
        return True
    if t.startswith("User wants") or t.startswith("We need") or t.startswith("The user"):
        return True
    return False


def _extract_chat_message_text(message: dict) -> str:
    """Prefer visible content; never expose reasoning/CoT as the user reply."""
    if not isinstance(message, dict):
        return ""
    content = (message.get("content") or "").strip()
    if content and not _looks_like_chain_of_thought(content):
        return content
    return ""


def _safe_chat_fallback_ru() -> str:
    return (
        "Кратко: подберу ближайшие модели по задаче и цене.\n\n"
        "### 1. Самая дешёвая / бесплатная из каталога\n"
        "- Почему: минимальная цена под ваш формат\n\n"
        "## Промпт\n"
        "Опишите сцену в 1–2 фразах — доработаю под выбранную модель.\n\n"
        "## Дальше\n"
        "Напишите: картинка / видео / музыка и бюджет (можно «бесплатно»)."
    )


def _ui_model_context(data: dict) -> str:
    """Extra system context: which generate model is selected in the UI."""
    mid = (data.get("selected_model_id") or "").strip()
    if not mid:
        return (
            "КОНТЕКСТ UI: медиа-модель в Generate не выбрана. "
            "Помогай выбрать модель; строку GENERATE_NOW не добавляй."
        )
    spec = INTEGRATED_MODELS.get(mid) or {}
    name = (data.get("selected_model_name") or spec.get("name") or mid).strip()
    provider = spec.get("provider") or "?"
    kind = spec.get("kind") or "?"
    return (
        f"КОНТЕКСТ UI: выбрана медиа-модель «{name}» (id={mid}, channel={provider}, kind={kind}). "
        "Учитывай её в советах. Если пользователь явно просит сгенерировать — "
        "добавь в конце GENERATE_NOW: <промпт>. Если просит совет/выбор — без GENERATE_NOW."
    )


@app.route("/api/chat", methods=["POST"])
def api_chat():
    load_env(BASE_DIR)
    data = request.get_json(silent=True) or {}
    raw_messages = data.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        return jsonify({"error": "empty"}), 400

    messages = []
    for item in raw_messages[-20:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        messages.append({"role": role, "content": text[:4000]})

    if not messages or messages[-1]["role"] != "user":
        return jsonify({"error": "invalid"}), 400

    system_prompt = f"{_build_chat_system_prompt()}\n\n{_ui_model_context(data)}"
    chat_messages = [{"role": "system", "content": system_prompt}, *messages]
    http = _chat_session()
    last_detail = ""
    last_status = 502
    deadline = time.monotonic() + float(os.getenv("CHAT_DEADLINE_SEC") or "45")

    def _left() -> float:
        return deadline - time.monotonic()

    def _budget(cap: float) -> float:
        return max(2.0, min(cap, _left() - 1.0))

    def _chat_ok(reply: str, used_model: str, channel: str):
        if _looks_like_chain_of_thought(reply):
            reply = _safe_chat_fallback_ru()
        visible, generate_prompt = _split_generate_now(reply)
        visible = _compact_chat_reply(visible or reply)
        if _looks_like_chain_of_thought(visible):
            visible = _safe_chat_fallback_ru()
        payload = {"reply": visible or reply, "model": used_model, "channel": channel}
        if generate_prompt:
            payload["generate_prompt"] = generate_prompt
            mid = (data.get("selected_model_id") or "").strip()
            if mid:
                payload["generate_model"] = mid
        return jsonify(payload)

    # Fast path: Groq first (Omni free routes currently fail slowly)
    groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
    prefer_groq = (os.getenv("CHAT_PREFER_GROQ") or "1").strip().lower() not in {"0", "false", "no"}
    if groq_key and prefer_groq:
        groq_models = []
        for candidate in (
            (os.getenv("GROQ_CHAT_MODEL") or "").strip(),
            (os.getenv("GROQ_MODEL") or "").strip(),
            "openai/gpt-oss-20b",
        ):
            if candidate and candidate not in groq_models:
                groq_models.append(candidate)
        for groq_model in groq_models:
            if _left() < 4:
                break
            try:
                resp = http.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": groq_model,
                        "messages": chat_messages,
                        "temperature": 0.35,
                        "max_tokens": 420,
                        "stream": False,
                    },
                    timeout=_budget(25),
                )
            except requests.RequestException as exc:
                last_detail = str(exc)
                last_status = 502
                continue
            if resp.status_code >= 400:
                try:
                    err = resp.json().get("error") or {}
                    last_detail = err.get("message") if isinstance(err, dict) else (err or resp.text[:300])
                except Exception:
                    last_detail = resp.text[:300]
                last_status = resp.status_code
                continue
            try:
                body = resp.json()
                message = body["choices"][0]["message"]
                reply = _extract_chat_message_text(message)
                used_model = body.get("model") or groq_model
            except (ValueError, KeyError, IndexError, TypeError):
                last_detail = "bad_groq_response"
                last_status = 502
                continue
            if reply:
                return _chat_ok(reply, used_model, "groq")
            last_detail = "empty groq reply"
            last_status = 502

    # OmniRoute: few attempts, short timeout (free routes often 502)
    omni_key = _omniroute_key()
    if omni_key:
        preferred = (os.getenv("OMNIROUTE_CHAT_MODEL") or "auto/chat").strip()
        omni_models = []
        for candidate in (preferred, "auto/chat", "auto/cheap"):
            if candidate and candidate not in omni_models:
                omni_models.append(candidate)
        omni_timeout = float(os.getenv("OMNIROUTE_CHAT_TIMEOUT") or "8")
        for model in omni_models[:2]:
            if _left() < 4:
                break
            payload = {
                "model": model,
                "messages": chat_messages,
                "temperature": 0.35,
                "max_tokens": 420,
                "stream": False,
            }
            try:
                resp = http.post(
                    f"{_omniroute_base()}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {omni_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=_budget(omni_timeout),
                )
            except requests.RequestException as exc:
                last_detail = str(exc.__class__.__name__)
                last_status = 502
                continue
            if resp.status_code >= 400:
                try:
                    err = resp.json().get("error") or {}
                    last_detail = err.get("message") if isinstance(err, dict) else (err or resp.text[:300])
                except Exception:
                    last_detail = resp.text[:300]
                last_status = resp.status_code
                continue
            try:
                body = resp.json()
                reply = body["choices"][0]["message"]["content"]
                used_model = body.get("model") or model
            except (ValueError, KeyError, IndexError, TypeError):
                return jsonify({"error": "bad_response"}), 502
            return _chat_ok(reply, used_model, "omniroute")

    # Late Groq if prefer_groq was off or earlier attempt failed
    if groq_key and not prefer_groq and _left() >= 4:
        groq_model = (
            (os.getenv("GROQ_CHAT_MODEL") or "").strip()
            or (os.getenv("GROQ_MODEL") or "").strip()
            or "openai/gpt-oss-20b"
        )
        try:
            resp = http.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": groq_model,
                    "messages": chat_messages,
                    "temperature": 0.35,
                    "max_tokens": 420,
                    "stream": False,
                },
                timeout=_budget(25),
            )
            if resp.status_code < 400:
                body = resp.json()
                message = body["choices"][0]["message"]
                reply = _extract_chat_message_text(message)
                if reply:
                    return _chat_ok(reply, body.get("model") or groq_model, "groq")
            try:
                err = resp.json().get("error") or {}
                last_detail = err.get("message") if isinstance(err, dict) else (err or resp.text[:300])
            except Exception:
                last_detail = resp.text[:300]
            last_status = resp.status_code
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            last_detail = str(exc)
            last_status = 502

    # Fallback: DeepSeek on Replicate if OmniRoute / Groq unavailable
    if _replicate_token() and _left() >= 15:
        deepseek_model = (
            os.getenv("CHAT_FALLBACK_REPLICATE_MODEL") or "deepseek-ai/deepseek-v3.1"
        ).strip()
        history_lines = []
        for item in messages[-12:]:
            who = "Пользователь" if item["role"] == "user" else "Ассистент"
            history_lines.append(f"{who}: {item['content']}")
        prompt = (
            f"{system_prompt}\n\n"
            + "\n".join(history_lines)
            + "\nАссистент:"
        )
        result = _run_replicate_prediction(
            deepseek_model,
            {"prompt": prompt},
            wait_seconds=int(max(5, min(60, (_left() - 6) / 2))),
        )
        if result.get("ok"):
            prediction = result["prediction"]
            outputs = _flatten_output(prediction.get("output"))
            reply = "\n".join(outputs).strip() or str(prediction.get("output") or "")
            if reply:
                return _chat_ok(reply, deepseek_model, "replicate")
            last_detail = "empty deepseek reply"
            last_status = 502
        else:
            last_detail = str(result.get("detail") or result.get("error") or "deepseek_failed")
            last_status = int(result.get("status") or 502)

    if not omni_key and not groq_key and not _replicate_token():
        return jsonify({"error": "not_configured"}), 503
    return jsonify({"error": "upstream", "status": last_status, "detail": last_detail or "Forbidden"}), 502


# --- Replicate integrations (live generate path) ---

INTEGRATED_MODELS = {
    # Convention:
    # - provider: "replicate" | "fal" | "groq" | "omniroute"
    # - replicate models use replicate_model; fal models use fal_model;
    #   omniroute models use omniroute_model (OpenAI-compatible id)
    # - same capability on both providers = two separate entries (do not replace),
    #   e.g. "flux-2-pro" (replicate) and "flux-2-pro-fal" (fal)
    "assistant": {
        "id": "assistant",
        "name": "Ассистент",
        "provider": "omniroute",
        "kind": "chat",
        "group": "assistants",
        "replicate_model": None,
        "inputs": ["text"],
        "outputs": ["text"],
    },
    "deepseek-v3-1": {
        "id": "deepseek-v3-1",
        "name": "DeepSeek V3.1",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "deepseek-ai/deepseek-v3.1",
        "inputs": ["text"],
        "outputs": ["text"],
        "notes": "hybrid thinking · $0.672/1M in · $2.016/1M out",
    },
    "deepseek-v3": {
        "id": "deepseek-v3",
        "name": "DeepSeek V3",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "deepseek-ai/deepseek-v3",
        "inputs": ["text"],
        "outputs": ["text"],
    },
    "claude-sonnet-5": {
        "id": "claude-sonnet-5",
        "name": "Claude Sonnet 5",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "anthropic/claude-sonnet-5",
        "inputs": ["text"],
        "outputs": ["text"],
    },
    "claude-4-5-haiku": {
        "id": "claude-4-5-haiku",
        "name": "Claude Haiku 4.5",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "anthropic/claude-4.5-haiku",
        "inputs": ["text"],
        "outputs": ["text"],
    },
    "claude-opus-4-7": {
        "id": "claude-opus-4-7",
        "name": "Claude Opus 4.7",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "anthropic/claude-opus-4.7",
        "inputs": ["text", "image"],
        "outputs": ["text"],
    },
    "gemini-3-5-flash": {
        "id": "gemini-3-5-flash",
        "name": "Gemini 3.5 Flash",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "google/gemini-3.5-flash",
        "inputs": ["text"],
        "outputs": ["text"],
    },
    "gemini-3-1-pro": {
        "id": "gemini-3-1-pro",
        "name": "Gemini 3.1 Pro",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "google/gemini-3.1-pro",
        "inputs": ["text", "image"],
        "outputs": ["text"],
        "notes": "thinking_level: low|medium|high",
    },
    "gpt-5-4": {
        "id": "gpt-5-4",
        "name": "GPT-5.4",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "openai/gpt-5.4",
        "inputs": ["text", "image"],
        "outputs": ["text"],
    },
    "gpt-5-6-sol": {
        "id": "gpt-5-6-sol",
        "name": "GPT-5.6 Sol",
        "provider": "replicate",
        "kind": "llm",
        "group": "generative",
        "replicate_model": "openai/gpt-5.6-sol",
        "inputs": ["text", "image"],
        "outputs": ["text"],
        "notes": "50% off until Sept 18",
    },
    "runway-gen-4-5": {
        "id": "runway-gen-4-5",
        "name": "Runway Gen-4.5",
        "provider": "replicate",
        "kind": "video",
        "group": "generative",
        "replicate_model": "runwayml/gen-4.5",
        "inputs": ["text", "image"],
        "outputs": ["video"],
    },
    "gen4-turbo": {
        "id": "gen4-turbo",
        "name": "Gen-4 Turbo",
        "provider": "replicate",
        "kind": "video",
        "group": "video",
        "replicate_model": "runwayml/gen4-turbo",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "i2v · image required · 5/10 с · 720p",
    },
    "veo-3-1-lite": {
        "id": "veo-3-1-lite",
        "name": "Veo 3.1 Lite",
        "provider": "replicate",
        "kind": "video",
        "group": "generative",
        "replicate_model": "google/veo-3.1-lite",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "listed": False,
    },
    "veo-3-1": {
        "id": "veo-3-1",
        "name": "Veo 3.1",
        "provider": "replicate",
        "kind": "video",
        "group": "video",
        "replicate_model": "google/veo-3.1",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "notes": "t2v/i2v · звук · 720p/1080p · 4/6/8 с",
    },
    "veo-3-1-fast": {
        "id": "veo-3-1-fast",
        "name": "Veo 3.1 Fast",
        "provider": "replicate",
        "kind": "video",
        "group": "video",
        "replicate_model": "google/veo-3.1-fast",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "notes": "быстрый t2v/i2v · звук · 720p/1080p · 4/6/8 с",
    },
    "sora-2": {
        "id": "sora-2",
        "name": "Sora 2",
        "provider": "replicate",
        "kind": "video",
        "group": "generative",
        "replicate_model": "openai/sora-2",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "notes": "discontinued after 2026-09-24",
    },
    "hailuo-2-3-fast": {
        "id": "hailuo-2-3-fast",
        "name": "Hailuo 2.3 Fast",
        "provider": "replicate",
        "kind": "video",
        "group": "generative",
        "replicate_model": "minimax/hailuo-2.3-fast",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "image required (i2v)",
    },
    "hailuo-02": {
        "id": "hailuo-02",
        "name": "Hailuo 02",
        "provider": "replicate",
        "kind": "video",
        "group": "video",
        "replicate_model": "minimax/hailuo-02",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "notes": "t2v/i2v · 512p/768p/1080p · 6/10 с · физика",
    },
    "dreamactor-m2": {
        "id": "dreamactor-m2",
        "name": "DreamActor M2.0",
        "provider": "replicate",
        "kind": "video",
        "group": "video",
        "replicate_model": "bytedance/dreamactor-m2.0",
        "inputs": ["image", "video"],
        "outputs": ["video"],
        "notes": "image+video required",
    },
    "nano-banana-pro": {
        "id": "nano-banana-pro",
        "name": "Nano Banana Pro",
        "provider": "replicate",
        "kind": "image",
        "group": "generative",
        "replicate_model": "google/nano-banana-pro",
        "inputs": ["text", "image"],
        "outputs": ["image"],
    },
    "nano-banana-2": {
        "id": "nano-banana-2",
        "name": "Nano Banana 2",
        "provider": "replicate",
        "kind": "image",
        "group": "generative",
        "replicate_model": "google/nano-banana-2",
        "inputs": ["text", "image"],
        "outputs": ["image"],
        "notes": "t2i/edit · 1K/2K/4K · до 14 референсов",
    },
    "nano-banana-2-lite": {
        "id": "nano-banana-2-lite",
        "name": "Nano Banana 2 Lite",
        "provider": "replicate",
        "kind": "image",
        "group": "generative",
        "replicate_model": "google/nano-banana-2-lite",
        "inputs": ["text", "image"],
        "outputs": ["image"],
    },
    "gemini-3-1-flash-tts": {
        "id": "gemini-3-1-flash-tts",
        "name": "Gemini 3.1 Flash TTS",
        "provider": "replicate",
        "kind": "audio",
        "group": "audio",
        "replicate_model": "google/gemini-3.1-flash-tts",
        "inputs": ["text"],
        "outputs": ["audio"],
    },
    "elevenlabs-v3": {
        "id": "elevenlabs-v3",
        "name": "ElevenLabs v3",
        "provider": "replicate",
        "kind": "audio",
        "group": "audio",
        "replicate_model": "elevenlabs/v3",
        "inputs": ["text"],
        "outputs": ["audio"],
    },
    "elevenlabs-music": {
        "id": "elevenlabs-music",
        "name": "ElevenLabs Music",
        "provider": "replicate",
        "kind": "audio",
        "group": "audio",
        "replicate_model": "elevenlabs/music",
        "inputs": ["text"],
        "outputs": ["audio"],
        "notes": "text→music · до 5 мин · vocals/instrumental",
    },
    "stable-audio-2-5": {
        "id": "stable-audio-2-5",
        "name": "Stable Audio 2.5",
        "provider": "replicate",
        "kind": "audio",
        "group": "audio",
        "replicate_model": "stability-ai/stable-audio-2.5",
        "inputs": ["text"],
        "outputs": ["audio"],
        "notes": "text→music/SFX · до 190 с · $0.20/трек",
    },
    "lyria-2": {
        "id": "lyria-2",
        "name": "Lyria 2",
        "provider": "replicate",
        "kind": "audio",
        "group": "audio",
        "replicate_model": "google/lyria-2",
        "inputs": ["text"],
        "outputs": ["audio"],
        "notes": "30s 48kHz stereo",
    },
    "minimax-music-01": {
        "id": "minimax-music-01",
        "name": "MiniMax Music-01",
        "provider": "replicate",
        "kind": "audio",
        "group": "audio",
        "replicate_model": "minimax/music-01",
        "inputs": ["text", "audio"],
        "outputs": ["audio"],
        "notes": "audio required (ref track)",
    },
    "ace-step": {
        "id": "ace-step",
        "name": "ACE-Step",
        "provider": "replicate",
        "kind": "audio",
        "group": "audio",
        "replicate_model": "lucataco/ace-step",
        "inputs": ["text"],
        "outputs": ["audio"],
        "notes": "tags→music · ~60 с · instrumental",
    },
    "flux-music": {
        "id": "flux-music",
        "name": "Flux Music",
        "provider": "replicate",
        "kind": "audio",
        "group": "audio",
        "replicate_model": "zsxkib/flux-music",
        "inputs": ["text"],
        "outputs": ["audio"],
        "notes": "~10s text→music",
    },
    "minimax-music-2-5": {
        "id": "minimax-music-2-5",
        "name": "MiniMax Music 2.5",
        "provider": "replicate",
        "kind": "audio",
        "group": "audio",
        "replicate_model": "minimax/music-2.5",
        "inputs": ["text"],
        "outputs": ["audio"],
        "notes": "lyrics→full song ~5min",
    },
    "elevenlabs-scribe-v2": {
        "id": "elevenlabs-scribe-v2",
        "name": "ElevenLabs Scribe v2",
        "provider": "replicate",
        "kind": "stt",
        "group": "audio",
        "replicate_model": "elevenlabs/scribe-v2",
        "inputs": ["audio"],
        "outputs": ["text"],
        "notes": "audio required (speech→text)",
    },
    "flux-2-pro": {
        "id": "flux-2-pro",
        "name": "Flux 2 Pro",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "black-forest-labs/flux-2-pro",
        "inputs": ["text", "image"],
        "outputs": ["image"],
    },
    "flux-1-1-pro": {
        "id": "flux-1-1-pro",
        "name": "Flux 1.1 Pro",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "black-forest-labs/flux-1.1-pro",
        "inputs": ["text", "image"],
        "outputs": ["image"],
    },
    "flux-kontext-pro": {
        "id": "flux-kontext-pro",
        "name": "Flux Kontext Pro",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "black-forest-labs/flux-kontext-pro",
        "inputs": ["text", "image"],
        "outputs": ["image"],
        "notes": "image required (text edit)",
    },
    "grok-imagine-image-2": {
        "id": "grok-imagine-image-2",
        "name": "Grok Imagine Image 2",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "xai/grok-imagine-image-2",
        "inputs": ["text", "image"],
        "outputs": ["image"],
    },
    "pasd-magnify": {
        "id": "pasd-magnify",
        "name": "PASD Magnify",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "lucataco/pasd-magnify",
        "inputs": ["image", "text"],
        "outputs": ["image"],
        "notes": "image required; non-commercial license",
    },
    "ideogram-v3-turbo": {
        "id": "ideogram-v3-turbo",
        "name": "Ideogram v3 Turbo",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "ideogram-ai/ideogram-v3-turbo",
        "inputs": ["text", "image"],
        "outputs": ["image"],
        "notes": "t2i · текст в кадре · style ref · $0.03",
    },
    "gen4-image": {
        "id": "gen4-image",
        "name": "Gen-4 Image",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "runwayml/gen4-image",
        "inputs": ["text", "image"],
        "outputs": ["image"],
        "notes": "optional refs @ref",
    },
    "z-image-turbo": {
        "id": "z-image-turbo",
        "name": "Z-Image Turbo",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "prunaai/z-image-turbo",
        "inputs": ["text"],
        "outputs": ["image"],
        "notes": "fast photoreal + text",
    },
    "hidream-l1-fast": {
        "id": "hidream-l1-fast",
        "name": "HiDream L1 Fast",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "prunaai/hidream-l1-fast",
        "inputs": ["text"],
        "outputs": ["image"],
        "notes": "fast multi-style t2i",
    },
    "gpt-image-2": {
        "id": "gpt-image-2",
        "name": "GPT Image 2",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "openai/gpt-image-2",
        "inputs": ["text", "image"],
        "outputs": ["image"],
        "notes": "текст/редактирование · low/medium/high",
    },
    "gpt-image-2-5-flare": {
        "id": "gpt-image-2-5-flare",
        "name": "GPT Image 2.5 Flare",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "openai/gpt-image-2.5-flare",
        "inputs": ["text", "image"],
        "outputs": ["image"],
        "notes": "быстрый t2i/edit · low→max",
    },
    "gpt-image-2-5-sunburst": {
        "id": "gpt-image-2-5-sunburst",
        "name": "GPT Image 2.5 Sunburst",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "openai/gpt-image-2.5-sunburst",
        "inputs": ["text", "image"],
        "outputs": ["image"],
        "notes": "точный t2i/edit · low→max",
    },
    "wan-3-0": {
        "id": "wan-3-0",
        "name": "Wan 3.0",
        "provider": "replicate",
        "kind": "video",
        "group": "video",
        "replicate_model": "alibaba/wan-3",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "notes": "480p/720p/1080p · до 30 с · text/image→video",
    },
    "grok-imagine-video-1-5": {
        "id": "grok-imagine-video-1-5",
        "name": "Grok Imagine Video 1.5",
        "provider": "replicate",
        "kind": "video",
        "group": "video",
        "replicate_model": "xai/grok-imagine-video-1.5",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "image→video · звук · 480p/720p · до 15 с",
    },
    "seedance-2-5": {
        "id": "seedance-2-5",
        "name": "Seedance 2.5",
        "provider": "replicate",
        "kind": "video",
        "group": "video",
        "replicate_model": "bytedance/seedance-2.5",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "notes": "текст/фото→видео · звук · 480p/720p · до 30 с",
    },
    # Higgsfield channel (queue + worker) — parallel to Replicate/fal, not a replacement
    "seedance-2-5-hf": {
        "id": "seedance-2-5-hf",
        "name": "Seedance 2.5 HF",
        "provider": "higgsfield",
        "kind": "video",
        "group": "video",
        "higgsfield_model": "bytedance/seedance-2.5/text-to-video",
        "higgsfield_model_i2v": "bytedance/seedance-2.5/image-to-video",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "notes": "Higgsfield · текст/фото→видео · 720p · до 30 с · звук",
        "wait_sec": 300,
    },
    "kling-v2-5-turbo-pro-hf": {
        "id": "kling-v2-5-turbo-pro-hf",
        "name": "Kling 2.5 Turbo Pro HF",
        "provider": "higgsfield",
        "kind": "video",
        "group": "video",
        "higgsfield_model": "kling-video/v2.5-turbo/pro/text-to-video",
        "higgsfield_model_i2v": "kling-video/v2.5-turbo/pro/image-to-video",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "notes": "Higgsfield · t2v/i2v · 5/10 с",
        "wait_sec": 300,
    },
    "kling-v3-0-hf": {
        "id": "kling-v3-0-hf",
        "name": "Kling 3.0",
        "provider": "higgsfield",
        "kind": "video",
        "group": "video",
        "higgsfield_model": "kling-video/v3.0/pro/text-to-video",
        "higgsfield_model_i2v": "kling-video/v3.0/pro/image-to-video",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "notes": "Higgsfield · Pro · t2v/i2v · звук · до 15 с",
        "wait_sec": 300,
    },
    "veo-3-1-hf": {
        "id": "veo-3-1-hf",
        "name": "Veo 3.1 HF",
        "provider": "higgsfield",
        "kind": "video",
        "group": "video",
        "higgsfield_model": "veo3.1/text-to-video",
        "higgsfield_model_i2v": "veo3.1/image-to-video",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "notes": "Higgsfield · t2v/i2v · звук (endpoint may be disabled upstream)",
        "wait_sec": 300,
    },
    "seedance-2-0": {
        "id": "seedance-2-0",
        "name": "Seedance 2.0",
        "provider": "replicate",
        "kind": "video",
        "group": "video",
        "replicate_model": "bytedance/seedance-2.0",
        "inputs": ["text"],
        "outputs": ["video"],
        "listed": False,
    },
    "happy-horse-1-1-t2v-fal": {
        "id": "happy-horse-1-1-t2v-fal",
        "name": "Happy Horse 1.1 T2V",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "alibaba/happy-horse/v1.1/text-to-video",
        "inputs": ["text"],
        "outputs": ["video"],
        "notes": "native audio + lip-sync",
    },
    "gemini-omni-flash-fal": {
        "id": "gemini-omni-flash-fal",
        "name": "Gemini Omni Flash",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "google/gemini-omni-flash",
        "inputs": ["text"],
        "outputs": ["video"],
        "notes": "synced audio",
    },
    "grok-imagine-video-1-5-i2v-fal": {
        "id": "grok-imagine-video-1-5-i2v-fal",
        "name": "Grok Imagine Video 1.5 I2V",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "xai/grok-imagine-video/v1.5/image-to-video",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "image required (i2v)",
        # Covered by replicate grok-imagine-video-1-5 — hide duplicate from studio sidebar
        "listed": False,
        "backup_for": "grok-imagine-video-1-5",
        "wait_sec": 300,
    },
    "seedance-2-0-t2v-fal": {
        "id": "seedance-2-0-t2v-fal",
        "name": "Seedance 2.0 T2V",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "bytedance/seedance-2.0/text-to-video",
        "inputs": ["text"],
        "outputs": ["video"],
        "notes": "native audio",
        "listed": False,
    },
    "kling-o3-standard-i2v-fal": {
        "id": "kling-o3-standard-i2v-fal",
        "name": "Kling O3 Standard I2V",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/kling-video/o3/standard/image-to-video",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "image required (i2v)",
        "listed": False,
    },
    "kling-v2-5-turbo-pro": {
        "id": "kling-v2-5-turbo-pro",
        "name": "Kling 2.5 Turbo Pro",
        "provider": "replicate",
        "kind": "video",
        "group": "video",
        "replicate_model": "kwaivgi/kling-v2.5-turbo-pro",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "notes": "t2v/i2v · 5/10 с · cinematic",
    },
    "p-video": {
        "id": "p-video",
        "name": "P-Video",
        "provider": "replicate",
        "kind": "video",
        "group": "video",
        "replicate_model": "prunaai/p-video",
        "inputs": ["text", "image", "audio"],
        "outputs": ["video"],
        "notes": "t2v/i2v/a2v · draft · звук · 720p/1080p · до 20 с",
    },
    "minimax-h3-ref-to-video-fal": {
        "id": "minimax-h3-ref-to-video-fal",
        "name": "MiniMax H3 Ref→Video",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "minimax/h3/reference-to-video",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "notes": "optional ref image(s)",
    },
    "wan-3-0-t2v-fal": {
        "id": "wan-3-0-t2v-fal",
        "name": "Wan 3.0 T2V",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "alibaba/wan-3.0/text-to-video",
        "inputs": ["text"],
        "outputs": ["video"],
        "notes": "native audio",
        # Covered by replicate wan-3-0 (text+image) — hide duplicate from studio sidebar
        "listed": False,
        "backup_for": "wan-3-0",
        "wait_sec": 300,
    },
    "wan-3-0-i2v-fal": {
        "id": "wan-3-0-i2v-fal",
        "name": "Wan 3.0 I2V",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "alibaba/wan-3.0/image-to-video",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "image required (i2v)",
        "listed": False,
        "backup_for": "wan-3-0",
        "wait_sec": 300,
    },
    "ltx-2-3-t2v-fal": {
        "id": "ltx-2-3-t2v-fal",
        "name": "LTX 2.3 T2V",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/ltx-2.3/text-to-video",
        "inputs": ["text"],
        "outputs": ["video"],
        "notes": "native audio",
    },
    "ltx-2-3-t2v-fast-fal": {
        "id": "ltx-2-3-t2v-fast-fal",
        "name": "LTX 2.3 T2V Fast",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/ltx-2.3/text-to-video/fast",
        "inputs": ["text"],
        "outputs": ["video"],
        "notes": "fast + native audio",
    },
    "ltx-2-3-i2v-fal": {
        "id": "ltx-2-3-i2v-fal",
        "name": "LTX 2.3 I2V",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/ltx-2.3/image-to-video",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "image required (i2v)",
    },
    "ltx-2-3-i2v-fast-fal": {
        "id": "ltx-2-3-i2v-fast-fal",
        "name": "LTX 2.3 I2V Fast",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/ltx-2.3/image-to-video/fast",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "image required (i2v)",
    },
    "ltx-2-3-a2v-fal": {
        "id": "ltx-2-3-a2v-fal",
        "name": "LTX 2.3 A2V",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/ltx-2.3/audio-to-video",
        "inputs": ["audio", "text", "image"],
        "outputs": ["video"],
        "notes": "audio required (a2v)",
    },
    "pixverse-v6-t2v-fal": {
        "id": "pixverse-v6-t2v-fal",
        "name": "PixVerse V6 T2V",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/pixverse/v6/text-to-video",
        "inputs": ["text"],
        "outputs": ["video"],
        "notes": "optional audio",
        "listed": False,
        "backup_for": "pixverse-v6",
        "wait_sec": 300,
    },
    "pixverse-v6-i2v-fal": {
        "id": "pixverse-v6-i2v-fal",
        "name": "PixVerse V6 I2V",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/pixverse/v6/image-to-video",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "image required (i2v)",
        "listed": False,
        "backup_for": "pixverse-v6",
        "wait_sec": 300,
    },
    "pixverse-v6": {
        "id": "pixverse-v6",
        "name": "PixVerse V6",
        "provider": "replicate",
        "kind": "video",
        "group": "video",
        "replicate_model": "pixverse/pixverse-v6",
        "inputs": ["text", "image"],
        "outputs": ["video"],
        "notes": "t2v/i2v · звук · multi-shot · до 15 с",
    },
    "seedream-5-pro": {
        "id": "seedream-5-pro",
        "name": "Seedream 5.0 Pro",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "bytedance/seedream-5-pro",
        "inputs": ["text", "image"],
        "outputs": ["image"],
        "notes": "текст/референсы→картинка · 1K/2K",
    },
    "seedream-5-lite-edit-fal": {
        "id": "seedream-5-lite-edit-fal",
        "name": "Seedream 5.0 Lite Edit",
        "provider": "fal",
        "kind": "image",
        "group": "image",
        "fal_model": "fal-ai/bytedance/seedream/v5/lite/edit",
        "inputs": ["image", "text"],
        "outputs": ["image"],
        "notes": "image required",
        "listed": False,
    },
    "seedream-5-lite-t2i-fal": {
        "id": "seedream-5-lite-t2i-fal",
        "name": "Seedream 5.0 Lite T2I",
        "provider": "fal",
        "kind": "image",
        "group": "image",
        "fal_model": "fal-ai/bytedance/seedream/v5/lite/text-to-image",
        "inputs": ["text"],
        "outputs": ["image"],
        "notes": "fast t2i",
        "listed": False,
    },
    "seedream-5-pro-t2i-fal": {
        "id": "seedream-5-pro-t2i-fal",
        "name": "Seedream 5.0 Pro T2I",
        "provider": "fal",
        "kind": "image",
        "group": "image",
        "fal_model": "bytedance/seedream/v5/pro/text-to-image",
        "inputs": ["text"],
        "outputs": ["image"],
        "notes": "deep-thinking t2i",
        # Covered by replicate seedream-5-pro
        "listed": False,
        "backup_for": "seedream-5-pro",
    },
    "seedream-5-pro-edit-fal": {
        "id": "seedream-5-pro-edit-fal",
        "name": "Seedream 5.0 Pro Edit",
        "provider": "fal",
        "kind": "image",
        "group": "image",
        "fal_model": "bytedance/seedream/v5/pro/edit",
        "inputs": ["image", "text"],
        "outputs": ["image"],
        "listed": False,
        "notes": "image required",
        "backup_for": "seedream-5-pro",
    },
    "seedance-2-5-t2v-fal": {
        "id": "seedance-2-5-t2v-fal",
        "name": "Seedance 2.5 T2V (fal)",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "bytedance/seedance-2.5/text-to-video",
        "inputs": ["text"],
        "outputs": ["video"],
        "notes": "backup for seedance-2-5",
        "listed": False,
        "backup_for": "seedance-2-5",
        "wait_sec": 300,
    },
    "seedance-2-5-ref2v-fal": {
        "id": "seedance-2-5-ref2v-fal",
        "name": "Seedance 2.5 Ref→Video (fal)",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "bytedance/seedance-2.5/reference-to-video",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "backup for seedance-2-5 (image)",
        "listed": False,
        "backup_for": "seedance-2-5",
        "wait_sec": 300,
    },
    "veo-3-1-t2v-fal": {
        "id": "veo-3-1-t2v-fal",
        "name": "Veo 3.1 T2V (fal)",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/veo3.1",
        "inputs": ["text"],
        "outputs": ["video"],
        "notes": "backup for veo-3-1",
        "listed": False,
        "backup_for": "veo-3-1",
        "wait_sec": 300,
    },
    "veo-3-1-i2v-fal": {
        "id": "veo-3-1-i2v-fal",
        "name": "Veo 3.1 I2V (fal)",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/veo3.1/image-to-video",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "backup for veo-3-1 (image)",
        "listed": False,
        "backup_for": "veo-3-1",
        "wait_sec": 300,
    },
    "veo-3-1-fast-t2v-fal": {
        "id": "veo-3-1-fast-t2v-fal",
        "name": "Veo 3.1 Fast T2V (fal)",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/veo3.1/fast",
        "inputs": ["text"],
        "outputs": ["video"],
        "notes": "backup for veo-3-1-fast",
        "listed": False,
        "backup_for": "veo-3-1-fast",
        "wait_sec": 300,
    },
    "veo-3-1-fast-i2v-fal": {
        "id": "veo-3-1-fast-i2v-fal",
        "name": "Veo 3.1 Fast I2V (fal)",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/veo3.1/fast/image-to-video",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "backup for veo-3-1-fast (image)",
        "listed": False,
        "backup_for": "veo-3-1-fast",
        "wait_sec": 300,
    },
    "kling-v2-5-turbo-pro-t2v-fal": {
        "id": "kling-v2-5-turbo-pro-t2v-fal",
        "name": "Kling v2.5 Turbo Pro T2V (fal)",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/kling-video/v2.5-turbo/pro/text-to-video",
        "inputs": ["text"],
        "outputs": ["video"],
        "notes": "backup for kling-v2-5-turbo-pro",
        "listed": False,
        "backup_for": "kling-v2-5-turbo-pro",
        "wait_sec": 300,
    },
    "kling-v2-5-turbo-pro-i2v-fal": {
        "id": "kling-v2-5-turbo-pro-i2v-fal",
        "name": "Kling v2.5 Turbo Pro I2V (fal)",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/kling-video/v2.5-turbo/pro/image-to-video",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "backup for kling-v2-5-turbo-pro (image)",
        "listed": False,
        "backup_for": "kling-v2-5-turbo-pro",
        "wait_sec": 300,
    },
    "hailuo-02-t2v-fal": {
        "id": "hailuo-02-t2v-fal",
        "name": "Hailuo 02 T2V (fal)",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/minimax/hailuo-02/standard/text-to-video",
        "inputs": ["text"],
        "outputs": ["video"],
        "notes": "backup for hailuo-02 (768p standard)",
        "listed": False,
        "backup_for": "hailuo-02",
        "wait_sec": 300,
    },
    "hailuo-02-i2v-fal": {
        "id": "hailuo-02-i2v-fal",
        "name": "Hailuo 02 I2V (fal)",
        "provider": "fal",
        "kind": "video",
        "group": "video",
        "fal_model": "fal-ai/minimax/hailuo-02/standard/image-to-video",
        "inputs": ["image", "text"],
        "outputs": ["video"],
        "notes": "backup for hailuo-02 (image)",
        "listed": False,
        "backup_for": "hailuo-02",
        "wait_sec": 300,
    },
    "gpt-image-2-fal": {
        "id": "gpt-image-2-fal",
        "name": "GPT Image 2 (fal)",
        "provider": "fal",
        "kind": "image",
        "group": "image",
        "fal_model": "openai/gpt-image-2",
        "inputs": ["text"],
        "outputs": ["image"],
        "notes": "backup for gpt-image-2",
        "listed": False,
        "backup_for": "gpt-image-2",
    },
    "gpt-image-2-edit-fal": {
        "id": "gpt-image-2-edit-fal",
        "name": "GPT Image 2 Edit (fal)",
        "provider": "fal",
        "kind": "image",
        "group": "image",
        "fal_model": "openai/gpt-image-2/edit",
        "inputs": ["image", "text"],
        "outputs": ["image"],
        "notes": "backup for gpt-image-2 (image)",
        "listed": False,
        "backup_for": "gpt-image-2",
    },
    "gpt-image-2-5-flare-fal": {
        "id": "gpt-image-2-5-flare-fal",
        "name": "GPT Image 2.5 Flare (fal)",
        "provider": "fal",
        "kind": "image",
        "group": "image",
        "fal_model": "openai/gpt-image-2.5/flare/text-to-image",
        "inputs": ["text"],
        "outputs": ["image"],
        "notes": "backup for gpt-image-2-5-flare",
        "listed": False,
        "backup_for": "gpt-image-2-5-flare",
    },
    "gpt-image-2-5-sunburst-fal": {
        "id": "gpt-image-2-5-sunburst-fal",
        "name": "GPT Image 2.5 Sunburst (fal)",
        "provider": "fal",
        "kind": "image",
        "group": "image",
        "fal_model": "openai/gpt-image-2.5/sunburst/text-to-image",
        "inputs": ["text"],
        "outputs": ["image"],
        "notes": "backup for gpt-image-2-5-sunburst",
        "listed": False,
        "backup_for": "gpt-image-2-5-sunburst",
    },
    "nano-banana-2-fal": {
        "id": "nano-banana-2-fal",
        "name": "Nano Banana 2 (fal)",
        "provider": "fal",
        "kind": "image",
        "group": "image",
        "fal_model": "fal-ai/nano-banana-2",
        "inputs": ["text"],
        "outputs": ["image"],
        "notes": "backup for nano-banana-2",
        "listed": False,
        "backup_for": "nano-banana-2",
    },
    "nano-banana-2-edit-fal": {
        "id": "nano-banana-2-edit-fal",
        "name": "Nano Banana 2 Edit (fal)",
        "provider": "fal",
        "kind": "image",
        "group": "image",
        "fal_model": "fal-ai/nano-banana-2/edit",
        "inputs": ["image", "text"],
        "outputs": ["image"],
        "notes": "backup for nano-banana-2 (image)",
        "listed": False,
        "backup_for": "nano-banana-2",
    },
    "ideogram-v3-turbo-fal": {
        "id": "ideogram-v3-turbo-fal",
        "name": "Ideogram V3 Turbo (fal)",
        "provider": "fal",
        "kind": "image",
        "group": "image",
        "fal_model": "fal-ai/ideogram/v3",
        "inputs": ["text"],
        "outputs": ["image"],
        "notes": "backup for ideogram-v3-turbo",
        "listed": False,
        "backup_for": "ideogram-v3-turbo",
    },
    "ace-step-fal": {
        "id": "ace-step-fal",
        "name": "ACE-Step (fal)",
        "provider": "fal",
        "kind": "audio",
        "group": "audio",
        "fal_model": "fal-ai/ace-step",
        "inputs": ["text"],
        "outputs": ["audio"],
        "notes": "backup for ace-step",
        "listed": False,
        "backup_for": "ace-step",
        "wait_sec": 180,
    },
    "elevenlabs-music-fal": {
        "id": "elevenlabs-music-fal",
        "name": "ElevenLabs Music (fal)",
        "provider": "fal",
        "kind": "audio",
        "group": "audio",
        "fal_model": "fal-ai/elevenlabs/music",
        "inputs": ["text"],
        "outputs": ["audio"],
        "notes": "backup for elevenlabs-music",
        "listed": False,
        "backup_for": "elevenlabs-music",
        "wait_sec": 180,
    },
    "stable-audio-2-5-fal": {
        "id": "stable-audio-2-5-fal",
        "name": "Stable Audio 2.5 (fal)",
        "provider": "fal",
        "kind": "audio",
        "group": "audio",
        "fal_model": "fal-ai/stable-audio-25/text-to-audio",
        "inputs": ["text"],
        "outputs": ["audio"],
        "notes": "backup for stable-audio-2-5",
        "listed": False,
        "backup_for": "stable-audio-2-5",
        "wait_sec": 180,
    },
    # --- OmniRoute channel (OpenAI-compatible /v1) ---
    "omni-auto": {
        "id": "omni-auto",
        "name": "Авто · чат",
        "provider": "omniroute",
        "kind": "llm",
        "group": "assistants",
        "omniroute_model": "auto/chat",
        "inputs": ["text"],
        "outputs": ["text"],
        "notes": "",
    },
    "omni-auto-free": {
        "id": "omni-auto-free",
        "name": "Авто · free",
        "provider": "omniroute",
        "kind": "llm",
        "group": "assistants",
        "omniroute_model": "auto/coding:free",
        "inputs": ["text"],
        "outputs": ["text"],
        "notes": "бесплатно",
    },
}


# Studio sidebar / public catalog: only nets onboarded like Wan
# (logo + example + vitrina + Replicate wiring).
STUDIO_ONBOARD_IDS = frozenset({
    "wan-3-0",
    "grok-imagine-video-1-5",
    "seedance-2-5",
    "seedance-2-5-hf",
    "veo-3-1",
    "veo-3-1-hf",
    "veo-3-1-fast",
    "kling-v2-5-turbo-pro",
    "kling-v2-5-turbo-pro-hf",
    "kling-v3-0-hf",
    "pixverse-v6",
    "p-video",
    "seedream-5-pro",
    "gpt-image-2",
    "gpt-image-2-5-flare",
    "gpt-image-2-5-sunburst",
    "nano-banana-2",
    "gen4-turbo",
    "hailuo-02",
    "ideogram-v3-turbo",
    "ace-step",
    "elevenlabs-music",
    "stable-audio-2-5",
    # текст / LLM — вкладка «Текст» и чат с моделью
    "deepseek-v3-1",
    "deepseek-v3",
    "claude-sonnet-5",
    "claude-4-5-haiku",
    "claude-opus-4-7",
    "gemini-3-5-flash",
    "gemini-3-1-pro",
    "gpt-5-4",
    "gpt-5-6-sol",
    "omni-auto",
    "omni-auto-free",
})

# Replicate primary id → fal backup id by mode: "t" text-only, "i" with input image.
FAILOVER_MAP: dict[str, dict[str, str]] = {
    "wan-3-0": {"t": "wan-3-0-t2v-fal", "i": "wan-3-0-i2v-fal"},
    "grok-imagine-video-1-5": {"i": "grok-imagine-video-1-5-i2v-fal"},
    "seedance-2-5": {"t": "seedance-2-5-t2v-fal", "i": "seedance-2-5-ref2v-fal"},
    "veo-3-1": {"t": "veo-3-1-t2v-fal", "i": "veo-3-1-i2v-fal"},
    "veo-3-1-fast": {"t": "veo-3-1-fast-t2v-fal", "i": "veo-3-1-fast-i2v-fal"},
    "kling-v2-5-turbo-pro": {"t": "kling-v2-5-turbo-pro-t2v-fal", "i": "kling-v2-5-turbo-pro-i2v-fal"},
    "pixverse-v6": {"t": "pixverse-v6-t2v-fal", "i": "pixverse-v6-i2v-fal"},
    "hailuo-02": {"t": "hailuo-02-t2v-fal", "i": "hailuo-02-i2v-fal"},
    "seedream-5-pro": {"t": "seedream-5-pro-t2i-fal", "i": "seedream-5-pro-edit-fal"},
    "gpt-image-2": {"t": "gpt-image-2-fal", "i": "gpt-image-2-edit-fal"},
    "gpt-image-2-5-flare": {"t": "gpt-image-2-5-flare-fal"},
    "gpt-image-2-5-sunburst": {"t": "gpt-image-2-5-sunburst-fal"},
    "nano-banana-2": {"t": "nano-banana-2-fal", "i": "nano-banana-2-edit-fal"},
    "ideogram-v3-turbo": {"t": "ideogram-v3-turbo-fal"},
    "ace-step": {"t": "ace-step-fal"},
    "elevenlabs-music": {"t": "elevenlabs-music-fal"},
    "stable-audio-2-5": {"t": "stable-audio-2-5-fal"},
}


def _failover_target(model_id: str, has_image: bool) -> str | None:
    """Return fal backup model id for a Replicate primary (B2 routing uses this)."""
    modes = FAILOVER_MAP.get(model_id)
    if not modes:
        return None
    key = "i" if has_image else "t"
    backup_id = modes.get(key)
    if not backup_id:
        return None
    spec = INTEGRATED_MODELS.get(backup_id)
    if not spec or spec.get("provider") != "fal":
        return None
    return backup_id


def _validate_failover_map() -> None:
    log = logging.getLogger(__name__)
    for primary, modes in FAILOVER_MAP.items():
        prim = INTEGRATED_MODELS.get(primary)
        if not prim or prim.get("provider") != "replicate":
            log.error("FAILOVER_MAP primary %s missing or not replicate", primary)
            continue
        for _mode, backup_id in modes.items():
            bak = INTEGRATED_MODELS.get(backup_id)
            if not bak or bak.get("provider") != "fal":
                log.error("FAILOVER_MAP backup %s invalid for %s", backup_id, primary)
                continue
            if bak.get("backup_for") != primary:
                log.error(
                    "FAILOVER_MAP backup %s backup_for=%s expected %s",
                    backup_id,
                    bak.get("backup_for"),
                    primary,
                )


_validate_failover_map()

_FAL_I2V_BACKUP_IDS = frozenset(
    bid
    for modes in FAILOVER_MAP.values()
    for mode, bid in modes.items()
    if mode == "i"
)


def _is_studio_visible(spec: dict) -> bool:
    """Hide nets until they are onboarded via the Replicate scheme."""
    if spec.get("listed") is False:
        return False
    mid = str(spec.get("id") or "")
    return mid in STUDIO_ONBOARD_IDS


def _replicate_token() -> str:
    load_env(BASE_DIR)
    return (os.getenv("REPLICATE_API_TOKEN") or "").strip()


def _fal_key() -> str:
    load_env(BASE_DIR)
    return (os.getenv("FAL_KEY") or "").strip()


def _omniroute_base() -> str:
    load_env(BASE_DIR)
    return (os.getenv("OMNIROUTE_BASE_URL") or "http://127.0.0.1:20128").rstrip("/")


def _omniroute_key() -> str:
    load_env(BASE_DIR)
    return (os.getenv("OMNIROUTE_API_KEY") or "").strip()


def _higgsfield_key() -> str:
    load_env(BASE_DIR)
    return (os.getenv("HF_KEY") or "").strip()


def _provider_model_ref(spec: dict, *, has_image: bool = False) -> str | None:
    if spec.get("provider") == "fal":
        return spec.get("fal_model")
    if spec.get("provider") == "omniroute":
        return spec.get("omniroute_model")
    if spec.get("provider") == "higgsfield":
        if has_image and spec.get("higgsfield_model_i2v"):
            return spec.get("higgsfield_model_i2v")
        return spec.get("higgsfield_model")
    return spec.get("replicate_model")


def _flatten_output(output) -> list[str]:
    if output is None:
        return []
    if isinstance(output, str):
        return [output]
    if isinstance(output, (list, tuple)):
        items: list[str] = []
        for part in output:
            items.extend(_flatten_output(part))
        return items
    # FileOutput-like / dict with url
    if isinstance(output, dict):
        for key in ("url", "href", "wav", "audio", "file", "mp3"):
            val = output.get(key)
            if isinstance(val, str) and val and (
                val.startswith("http") or val.startswith("data:") or val.startswith("/")
            ):
                return [val]
        return []
    text = str(output)
    return [text] if text else []


def _fal_extract_outputs(data, kind: str) -> list[str]:
    """Normalize fal.ai result payloads into URL/text strings."""
    if data is None:
        return []
    if isinstance(data, str):
        return [data]
    if not isinstance(data, dict):
        return _flatten_output(data)

    if kind in {"llm", "stt"}:
        for key in ("text", "output", "response", "transcript"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return [val]
            if isinstance(val, list):
                joined = "\n".join(str(x) for x in val if x is not None).strip()
                if joined:
                    return [joined]
        return [str(data)]

    urls: list[str] = []

    def _push(value):
        if isinstance(value, str) and value.startswith("http"):
            urls.append(value)
        elif isinstance(value, dict):
            u = value.get("url") or value.get("href")
            if isinstance(u, str) and u.startswith("http"):
                urls.append(u)

    for key in ("images", "image", "video", "audio", "audio_file", "audio_url", "output", "outputs"):
        val = data.get(key)
        if val is None:
            continue
        if isinstance(val, list):
            for item in val:
                _push(item)
        else:
            _push(val)

    if urls:
        return urls
    return _flatten_output(data)


def _build_replicate_input(
    spec: dict,
    prompt: str,
    image_data_url: str | None,
    audio_data_url: str | None = None,
    video_data_url: str | None = None,
) -> dict:
    model_id = spec["id"]
    prompt = (prompt or "").strip()
    image = (image_data_url or "").strip() or None
    audio = (audio_data_url or "").strip() or None
    video = (video_data_url or "").strip() or None

    if model_id in {"claude-sonnet-5", "claude-4-5-haiku"}:
        return {"prompt": prompt}

    if model_id == "deepseek-v3-1":
        return {"prompt": prompt}

    if model_id == "deepseek-v3":
        return {"prompt": prompt}

    if model_id == "claude-opus-4-7":
        payload = {"prompt": prompt}
        if image:
            payload["image"] = image
        return payload

    if model_id == "gemini-3-5-flash":
        return {"prompt": prompt}

    if model_id == "gemini-3-1-pro":
        payload = {
            "prompt": prompt,
            "thinking_level": "medium",
        }
        if image:
            payload["images"] = [image]
        return payload

    if model_id in {"gpt-5-4", "gpt-5-6-sol"}:
        payload = {
            "prompt": prompt,
            "reasoning_effort": "none",
            "verbosity": "medium",
        }
        if image:
            payload["image_input"] = [image]
        return payload

    if model_id == "gemini-3-1-flash-tts":
        lang = "ru-RU" if any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in prompt) else "en-US"
        return {
            "text": prompt[:4000],
            "voice": "Kore",
            "prompt": "Say the following naturally.",
            "language_code": lang,
        }

    if model_id == "elevenlabs-v3":
        lang = "ru" if any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in prompt) else "en"
        return {
            "prompt": prompt[:5000],
            "voice": "Rachel",
            "language_code": lang,
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0,
            "speed": 1,
        }

    if model_id == "elevenlabs-music":
        return {
            "prompt": prompt[:4000],
            "music_length_ms": 30000,
            "force_instrumental": False,
            "output_format": "mp3_standard",
        }

    if model_id == "stable-audio-2-5":
        return {
            "prompt": prompt,
            "duration": 30,
            "steps": 8,
            "cfg_scale": 7,
        }

    if model_id == "lyria-2":
        return {
            "prompt": prompt,
        }

    if model_id == "minimax-music-01":
        if not audio:
            raise ValueError("MiniMax Music-01 requires a reference song (.mp3/.wav, >15s)")
        lyrics = prompt[:400]
        if not lyrics:
            raise ValueError("MiniMax Music-01 requires lyrics in the prompt")
        return {
            "lyrics": lyrics,
            "song_file": audio,
            "sample_rate": 44100,
            "bitrate": 256000,
        }

    if model_id == "ace-step":
        return {
            "tags": prompt,
            "lyrics": "[instrumental]",
            "duration": 60,
            "number_of_steps": 27,
            "seed": -1,
            "scheduler": "euler",
            "guidance_type": "apg",
            "guidance_scale": 15,
            "tag_guidance_scale": 5,
            "lyric_guidance_scale": 1.5,
        }

    if model_id == "flux-music":
        return {
            "prompt": prompt,
            "negative_prompt": "low quality, gentle",
            "guidance_scale": 7,
            "model_version": "base",
            "steps": 50,
            "save_spectrogram": False,
        }

    if model_id == "minimax-music-2-5":
        lyrics = prompt[:3500]
        if not lyrics:
            raise ValueError("MiniMax Music 2.5 requires lyrics in the prompt")
        return {
            "lyrics": lyrics,
            "prompt": "well-produced song, clear vocals, modern mix",
            "sample_rate": 44100,
            "bitrate": 256000,
            "audio_format": "mp3",
        }

    if model_id == "elevenlabs-scribe-v2":
        if not audio:
            raise ValueError("Scribe v2 requires an attached audio or video file")
        payload = {
            "audio": audio,
            "language_code": "auto",
            "diarize": False,
            "timestamps_granularity": "word",
            "tag_audio_events": True,
            "no_verbatim": False,
        }
        if prompt:
            payload["keyterms"] = prompt[:2000]
        return payload

    if model_id == "flux-2-pro":
        payload = {
            "prompt": prompt,
            "aspect_ratio": "match_input_image" if image else "1:1",
            "resolution": "match_input_image" if image else "1 MP",
            "output_format": "webp",
            "output_quality": 80,
            "safety_tolerance": 2,
        }
        if image:
            payload["input_images"] = [image]
        return payload

    if model_id == "flux-1-1-pro":
        payload = {
            "prompt": prompt,
            "aspect_ratio": "1:1",
            "output_format": "webp",
            "output_quality": 80,
            "safety_tolerance": 2,
            "prompt_upsampling": False,
        }
        if image:
            payload["image_prompt"] = image
        return payload

    if model_id == "flux-kontext-pro":
        if not image:
            raise ValueError("Flux Kontext Pro requires an attached image to edit")
        return {
            "prompt": prompt,
            "input_image": image,
            "aspect_ratio": "match_input_image",
            "output_format": "png",
            "safety_tolerance": 2,
            "prompt_upsampling": False,
        }

    if model_id == "grok-imagine-image-2":
        payload = {
            "prompt": prompt,
            "quality": "medium",
            "resolution": "2k",
        }
        if image:
            payload["image"] = image
        else:
            payload["aspect_ratio"] = "1:1"
        return payload

    if model_id == "pasd-magnify":
        if not image:
            raise ValueError("PASD Magnify requires an attached image")
        return {
            "image": image,
            "prompt": prompt or "clean, high-resolution, 8k, best quality, masterpiece",
            "n_prompt": "dotted, noise, blur, lowres, oversmooth, worst quality, low quality",
            "denoise_steps": 20,
            "upsample_scale": 2,
            "conditioning_scale": 1.1,
            "guidance_scale": 7.5,
        }

    if model_id == "ideogram-v3-turbo":
        payload = {
            "prompt": prompt,
            "aspect_ratio": "1:1",
            "magic_prompt_option": "Auto",
            "style_type": "Auto",
        }
        if image:
            payload["style_reference_images"] = [image]
        return payload

    if model_id == "gen4-image":
        payload = {
            "prompt": prompt,
            "aspect_ratio": "16:9",
            "resolution": "1080p",
        }
        if image:
            payload["reference_images"] = [image]
            payload["reference_tags"] = ["ref"]
        return payload

    if model_id == "z-image-turbo":
        return {
            "prompt": prompt,
            "width": 1024,
            "height": 1024,
            "num_inference_steps": 9,
            "guidance_scale": 0,
            "output_format": "jpg",
            "output_quality": 90,
        }

    if model_id == "hidream-l1-fast":
        return {
            "prompt": prompt,
            "model_type": "fast",
            "speed_mode": "Lightly Juiced \U0001f34a (more consistent)",
            "resolution": "1024 \u00d7 1024 (Square)",
            "output_format": "webp",
            "output_quality": 100,
        }

    if model_id == "gpt-image-2":
        payload = {
            "prompt": prompt,
            "quality": "medium",
            "aspect_ratio": "1:1",
            "output_format": "webp",
            "number_of_images": 1,
            "background": "auto",
            "moderation": "auto",
            "output_compression": 90,
        }
        if image:
            payload["input_images"] = [image]
        return payload

    if model_id == "gpt-image-2-5-flare":
        payload = {
            "prompt": prompt,
            "quality": "medium",
            "aspect_ratio": "1:1",
            "output_format": "webp",
            "number_of_images": 1,
            "background": "auto",
            "moderation": "auto",
            "output_compression": 90,
        }
        if image:
            payload["input_images"] = [image]
        return payload

    if model_id == "gpt-image-2-5-sunburst":
        payload = {
            "prompt": prompt,
            "quality": "medium",
            "aspect_ratio": "1:1",
            "output_format": "webp",
            "number_of_images": 1,
            "background": "auto",
            "moderation": "auto",
            "output_compression": 90,
        }
        if image:
            payload["input_images"] = [image]
        return payload

    if model_id == "nano-banana-pro":
        payload = {
            "prompt": prompt,
            "aspect_ratio": "match_input_image" if image else "1:1",
            "resolution": "2K",
            "output_format": "jpg",
        }
        if image:
            payload["image_input"] = [image]
        return payload

    if model_id == "nano-banana-2":
        payload = {
            "prompt": prompt,
            "aspect_ratio": "match_input_image" if image else "1:1",
            "resolution": "1K",
            "output_format": "jpg",
        }
        if image:
            payload["image_input"] = [image]
        return payload

    if model_id == "nano-banana-2-lite":
        payload = {
            "prompt": prompt,
            "aspect_ratio": "match_input_image" if image else "1:1",
            "output_format": "jpg",
        }
        if image:
            payload["image_input"] = [image]
        return payload

    if model_id == "wan-3-0":
        payload = {
            "prompt": prompt,
            "resolution": "720p",
            "aspect_ratio": "adaptive",
            "duration": 5,
            "enable_prompt_expansion": True,
            "negative_prompt": "",
        }
        if image:
            payload["image"] = image
            # aspect_ratio ignored when image is set
            payload.pop("aspect_ratio", None)
        return payload

    if model_id == "grok-imagine-video-1-5":
        if not image:
            raise ValueError("Grok Imagine Video 1.5 requires an attached image")
        return {
            "prompt": prompt,
            "image": image,
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "auto",
        }

    if model_id == "seedance-2-5":
        payload = {
            "prompt": prompt,
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "adaptive" if image else "16:9",
            "generate_audio": True,
            "output_format": "mp4",
            "watermark": False,
        }
        if image:
            payload["image"] = image
        return payload

    if model_id == "seedance-2-5-hf":
        # Higgsfield Seedance 2.5 — t2v or image-to-video
        if image:
            return {
                "prompt": prompt or "Animate this image.",
                "image_url": image,
                "duration": 5,
                "resolution": "720p",
                "generate_audio": True,
            }
        return {
            "prompt": prompt,
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "output_format": "mp4",
            "generate_audio": True,
        }

    if model_id == "kling-v2-5-turbo-pro-hf":
        payload = {
            "prompt": prompt,
            "duration": 5,
            "cfg_scale": 0.5,
            "negative_prompt": "",
        }
        if image:
            payload["image_url"] = image
        return payload

    if model_id == "kling-v3-0-hf":
        payload = {
            "prompt": prompt,
            "duration": 5,
            "sound": "on",
            "cfg_scale": 0.5,
            "aspect_ratio": "16:9",
        }
        if image:
            payload["image_url"] = image
            payload.pop("aspect_ratio", None)
        return payload

    if model_id == "veo-3-1-hf":
        payload = {
            "prompt": prompt,
            "duration": 8,
            "aspect_ratio": "16:9",
            "generate_audio": True,
        }
        if image:
            payload["image_url"] = image
        return payload

    if model_id == "seedance-2-0":
        return {"prompt": prompt}

    if model_id == "happy-horse-1-1-t2v-fal":
        return {
            "prompt": prompt[:2500],
            "aspect_ratio": "16:9",
            "resolution": "1080p",
            "duration": 5,
            "enable_safety_checker": True,
        }

    if model_id == "gemini-omni-flash-fal":
        return {
            "prompt": prompt,
            "aspect_ratio": "16:9",
            "duration": 8,
        }

    if model_id == "grok-imagine-video-1-5-i2v-fal":
        if not image:
            raise ValueError("Grok Imagine Video 1.5 I2V requires an attached image")
        return {
            "prompt": prompt,
            "image_url": image,
            "duration": 6,
            "resolution": "720p",
        }

    if model_id == "seedance-2-0-t2v-fal":
        return {
            "prompt": prompt,
            "resolution": "720p",
            "duration": "5",
            "aspect_ratio": "16:9",
            "generate_audio": True,
            "bitrate_mode": "standard",
        }

    if model_id == "kling-o3-standard-i2v-fal":
        if not image:
            raise ValueError("Kling O3 Standard I2V requires an attached start-frame image")
        return {
            "prompt": prompt,
            "image_url": image,
            "duration": "5",
            "generate_audio": False,
        }

    if model_id == "minimax-h3-ref-to-video-fal":
        payload = {
            "prompt": prompt,
            "duration": 5,
            "resolution": "768P",
            "aspect_ratio": "16:9",
            "prompt_expansion_mode": "fast",
            "enable_safety_checker": True,
        }
        if image:
            payload["reference_image_urls"] = [image]
        return payload

    if model_id == "wan-3-0-t2v-fal":
        return {
            "prompt": prompt,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "duration": 5,
            "audio": True,
            "enable_prompt_expansion": True,
            "enable_safety_checker": True,
        }

    if model_id == "wan-3-0-i2v-fal":
        if not image:
            raise ValueError("Wan 3.0 I2V requires an attached start-frame image")
        payload = {
            "start_image_url": image,
            "resolution": "720p",
            "aspect_ratio": "adaptive",
            "duration": 5,
            "audio": True,
            "enable_prompt_expansion": True,
            "enable_safety_checker": True,
        }
        if prompt:
            payload["prompt"] = prompt
        return payload

    if model_id in {"ltx-2-3-t2v-fal", "ltx-2-3-t2v-fast-fal"}:
        return {
            "prompt": prompt,
            "duration": 6,
            "resolution": "1080p",
            "aspect_ratio": "16:9",
            "fps": 25,
            "generate_audio": True,
        }

    if model_id in {"ltx-2-3-i2v-fal", "ltx-2-3-i2v-fast-fal"}:
        if not image:
            raise ValueError("LTX 2.3 I2V requires an attached start-frame image")
        if not prompt:
            raise ValueError("LTX 2.3 I2V requires a prompt")
        return {
            "image_url": image,
            "prompt": prompt,
            "duration": 6,
            "resolution": "1080p",
            "aspect_ratio": "auto",
            "fps": 25,
            "generate_audio": True,
        }

    if model_id == "ltx-2-3-a2v-fal":
        if not audio:
            raise ValueError("LTX 2.3 A2V requires an attached audio (or video) file")
        if not prompt and not image:
            raise ValueError("LTX 2.3 A2V requires a prompt or an attached image")
        payload = {
            "audio_url": audio,
            "aspect_ratio": "auto",
        }
        if image:
            payload["image_url"] = image
        if prompt:
            payload["prompt"] = prompt
        return payload

    if model_id == "pixverse-v6":
        payload = {
            "prompt": prompt,
            "duration": 5,
            "quality": "720p",
            "aspect_ratio": "16:9",
            "generate_audio_switch": True,
            "generate_multi_clip_switch": False,
            "negative_prompt": "",
        }
        if image:
            payload["image"] = image
            payload.pop("aspect_ratio", None)
        return payload

    if model_id == "pixverse-v6-t2v-fal":
        return {
            "prompt": prompt,
            "aspect_ratio": "16:9",
            "resolution": "720p",
            "duration": 5,
            "generate_audio_switch": True,
            "generate_multi_clip_switch": False,
            "thinking_type": "auto",
        }

    if model_id == "pixverse-v6-i2v-fal":
        if not image:
            raise ValueError("PixVerse V6 I2V requires an attached start-frame image")
        if not prompt:
            raise ValueError("PixVerse V6 I2V requires a prompt")
        return {
            "prompt": prompt,
            "image_url": image,
            "resolution": "720p",
            "duration": 5,
            "generate_audio_switch": True,
            "generate_multi_clip_switch": False,
            "thinking_type": "auto",
        }

    if model_id == "seedream-5-lite-edit-fal":
        if not image:
            raise ValueError("Seedream 5.0 Lite Edit requires an attached image")
        if not prompt:
            raise ValueError("Seedream 5.0 Lite Edit requires a prompt")
        return {
            "prompt": prompt,
            "image_urls": [image],
            "image_size": "auto_2K",
            "num_images": 1,
            "max_images": 1,
            "enable_safety_checker": True,
        }

    if model_id == "seedream-5-pro":
        payload = {
            "prompt": prompt,
            "size": "2K",
            "aspect_ratio": "match_input_image" if image else "1:1",
            "output_format": "png",
            "layer_decomposition": False,
        }
        if image:
            payload["image_input"] = [image]
        return payload

    if model_id == "seedream-5-lite-t2i-fal":
        return {
            "prompt": prompt,
            "image_size": "auto_2K",
            "num_images": 1,
            "max_images": 1,
            "enable_safety_checker": True,
        }

    if model_id == "seedream-5-pro-t2i-fal":
        return {
            "prompt": prompt,
            "image_size": "auto_2K",
            "num_images": 1,
            "output_format": "png",
            "enable_safety_checker": True,
        }

    if model_id == "seedream-5-pro-edit-fal":
        if not image:
            raise ValueError("Seedream 5.0 Pro Edit requires an attached image")
        if not prompt:
            raise ValueError("Seedream 5.0 Pro Edit requires a prompt")
        return {
            "prompt": prompt,
            "image_urls": [image],
            "image_size": "auto_2K",
            "num_images": 1,
            "output_format": "png",
            "enable_safety_checker": True,
        }

    if model_id == "runway-gen-4-5":
        payload = {
            "prompt": prompt,
            "duration": 5,
            "aspect_ratio": "16:9",
        }
        if image:
            payload["image"] = image
        return payload

    if model_id == "gen4-turbo":
        if not image:
            raise ValueError("Gen-4 Turbo requires an attached start-frame image")
        return {
            "prompt": prompt,
            "image": image,
            "duration": 5,
            "aspect_ratio": "16:9",
        }

    if model_id == "veo-3-1":
        payload = {
            "prompt": prompt,
            "duration": 8,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "generate_audio": True,
        }
        if image:
            payload["image"] = image
        return payload

    if model_id == "veo-3-1-fast":
        payload = {
            "prompt": prompt,
            "duration": 8,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "generate_audio": True,
        }
        if image:
            payload["image"] = image
        return payload

    if model_id == "veo-3-1-lite":
        payload = {
            "prompt": prompt,
            "duration": 8,
            "resolution": "720p",
            "aspect_ratio": "16:9",
        }
        if image:
            payload["image"] = image
        return payload

    if model_id == "kling-v2-5-turbo-pro":
        payload = {
            "prompt": prompt,
            "duration": 5,
            "aspect_ratio": "16:9",
            "negative_prompt": "",
        }
        if image:
            payload["start_image"] = image
            payload.pop("aspect_ratio", None)
        return payload

    if model_id == "p-video":
        payload = {
            "prompt": prompt,
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "fps": 24,
            "draft": False,
            "prompt_upsampling": True,
            "save_audio": True,
        }
        if image:
            payload["image"] = image
            payload.pop("aspect_ratio", None)
        if audio:
            payload["audio"] = audio
            payload.pop("duration", None)
        return payload

    if model_id == "sora-2":
        payload = {
            "prompt": prompt,
            "seconds": 4,
            "aspect_ratio": "landscape",
        }
        if image:
            payload["input_reference"] = image
        return payload

    if model_id == "hailuo-2-3-fast":
        if not image:
            raise ValueError("Hailuo 2.3 Fast requires an attached image (image-to-video)")
        return {
            "prompt": prompt,
            "first_frame_image": image,
            "duration": 6,
            "resolution": "768p",
            "prompt_optimizer": True,
        }

    if model_id == "hailuo-02":
        payload = {
            "prompt": prompt,
            "duration": 6,
            "resolution": "768p",
            "prompt_optimizer": True,
        }
        if image:
            payload["first_frame_image"] = image
        return payload

    if model_id == "dreamactor-m2":
        if not image:
            raise ValueError("DreamActor M2.0 requires a character image")
        if not video:
            raise ValueError("DreamActor M2.0 requires a driving video")
        return {
            "image": image,
            "video": video,
            "cut_first_second": True,
        }

    if model_id == "seedance-2-5-t2v-fal":
        return {
            "prompt": prompt,
            "resolution": "720p",
            "duration": "5",
            "aspect_ratio": "16:9",
            "generate_audio": True,
            "bitrate_mode": "standard",
        }

    if model_id == "seedance-2-5-ref2v-fal":
        if not image:
            raise ValueError("Seedance 2.5 Ref→Video requires an attached image")
        payload = {
            "prompt": prompt or "animate the reference",
            "image_urls": [image],
            "resolution": "720p",
            "duration": "5",
            "aspect_ratio": "16:9",
            "generate_audio": True,
            "task": "reference",
        }
        return payload

    if model_id in {"veo-3-1-t2v-fal", "veo-3-1-fast-t2v-fal"}:
        return {
            "prompt": prompt,
            "duration": "8s",
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "generate_audio": True,
        }

    if model_id in {"veo-3-1-i2v-fal", "veo-3-1-fast-i2v-fal"}:
        if not image:
            raise ValueError("Veo 3.1 I2V requires an attached start-frame image")
        return {
            "prompt": prompt,
            "image_url": image,
            "duration": "8s",
            "resolution": "720p",
            "generate_audio": True,
        }

    if model_id == "kling-v2-5-turbo-pro-t2v-fal":
        return {
            "prompt": prompt,
            "duration": "5",
            "aspect_ratio": "16:9",
            "negative_prompt": "",
            "cfg_scale": 0.5,
        }

    if model_id == "kling-v2-5-turbo-pro-i2v-fal":
        if not image:
            raise ValueError("Kling v2.5 Turbo Pro I2V requires an attached start-frame image")
        return {
            "prompt": prompt,
            "image_url": image,
            "duration": "5",
            "negative_prompt": "blur, distort, and low quality",
            "cfg_scale": 0.5,
        }

    if model_id == "hailuo-02-t2v-fal":
        return {
            "prompt": prompt,
            "duration": "6",
            "prompt_optimizer": True,
        }

    if model_id == "hailuo-02-i2v-fal":
        if not image:
            raise ValueError("Hailuo 02 I2V requires an attached image")
        return {
            "prompt": prompt,
            "image_url": image,
            "duration": "6",
            "resolution": "768P",
            "prompt_optimizer": True,
        }

    if model_id == "gpt-image-2-fal":
        return {
            "prompt": prompt,
            "quality": "medium",
            "image_size": "square_hd",
            "num_images": 1,
            "output_format": "webp",
            "background": "auto",
        }

    if model_id == "gpt-image-2-edit-fal":
        if not image:
            raise ValueError("GPT Image 2 Edit requires an attached image")
        return {
            "prompt": prompt,
            "image_urls": [image],
            "image_size": "auto",
            "quality": "medium",
            "num_images": 1,
            "output_format": "webp",
            "background": "auto",
        }

    if model_id in {"gpt-image-2-5-flare-fal", "gpt-image-2-5-sunburst-fal"}:
        return {
            "prompt": prompt,
            "quality": "medium",
            "image_size": "square_hd",
            "num_images": 1,
            "output_format": "png",
            "background": "auto",
        }

    if model_id == "nano-banana-2-fal":
        return {
            "prompt": prompt,
            "aspect_ratio": "auto",
            "resolution": "1K",
            "output_format": "jpeg",
        }

    if model_id == "nano-banana-2-edit-fal":
        if not image:
            raise ValueError("Nano Banana 2 Edit requires an attached image")
        return {
            "prompt": prompt,
            "image_urls": [image],
            "aspect_ratio": "auto",
            "resolution": "1K",
            "output_format": "jpeg",
        }

    if model_id == "ideogram-v3-turbo-fal":
        return {
            "prompt": prompt,
            "rendering_speed": "TURBO",
            "image_size": "square_hd",
            "expand_prompt": True,
            "num_images": 1,
        }

    if model_id == "ace-step-fal":
        return {
            "tags": prompt,
            "lyrics": "[instrumental]",
            "duration": 60,
            "number_of_steps": 27,
            "seed": -1,
            "scheduler": "euler",
            "guidance_type": "apg",
            "guidance_scale": 15,
            "tag_guidance_scale": 5,
            "lyric_guidance_scale": 1.5,
        }

    if model_id == "elevenlabs-music-fal":
        return {
            "prompt": prompt[:4000],
            "music_length_ms": 30000,
            "force_instrumental": False,
            "output_format": "mp3_44100_128",
        }

    if model_id == "stable-audio-2-5-fal":
        return {
            "prompt": prompt,
            "seconds_total": 30,
            "num_inference_steps": 8,
            "guidance_scale": 7,
        }

    raise ValueError(f"unknown model {model_id}")


def _build_provider_input(
    spec: dict,
    prompt: str,
    image_data_url: str | None,
    audio_data_url: str | None = None,
    video_data_url: str | None = None,
) -> dict:
    """Build provider-specific input. Replicate and fal models keep separate ids even if similar."""
    # Все ассистенты (любая LLM-модель в группе assistants) — роль Навигатора.
    # Роль «навигатора студии» — только у модели-ассистента. Текстовые модели (DeepSeek, Claude, GPT, Gemini…)
    # человек выбирает, чтобы говорить с ними напрямую, — им роль не навязываем.
    if spec.get("kind") in {"llm", "chat"} and (spec.get("id") == "assistant" or spec.get("navigator")):
        prompt = _with_assistant_persona(prompt)
    if spec.get("provider") == "omniroute":
        return {"prompt": prompt}
    return _build_replicate_input(spec, prompt, image_data_url, audio_data_url, video_data_url)


def _replicate_submit(replicate_model: str, input_payload: dict) -> dict:
    """POST prediction without long Prefer:wait. Returns prediction_id + get_url."""
    token = _replicate_token()
    if not token:
        return {"ok": False, "error": "not_configured", "status": 503, "phase": "submit"}

    owner, name = replicate_model.split("/", 1)
    url = f"https://api.replicate.com/v1/models/{owner}/{name}/predictions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "wait=1",
    }
    try:
        resp = requests.post(url, headers=headers, json={"input": input_payload}, timeout=30)
    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": "upstream",
            "detail": str(exc.__class__.__name__),
            "status": 502,
            "phase": "submit",
        }

    try:
        body = resp.json()
    except ValueError:
        return {
            "ok": False,
            "error": "bad_response",
            "detail": resp.text[:300],
            "status": 502,
            "phase": "submit",
        }

    if resp.status_code >= 400:
        detail = body.get("detail") or body.get("error") or resp.text[:300]
        return {
            "ok": False,
            "error": "upstream",
            "detail": detail,
            "status": resp.status_code,
            "body": body,
            "phase": "submit",
        }

    prediction_id = body.get("id")
    get_url = (body.get("urls") or {}).get("get") or (
        f"https://api.replicate.com/v1/predictions/{prediction_id}" if prediction_id else None
    )
    if not prediction_id or not get_url:
        return {
            "ok": False,
            "error": "bad_response",
            "detail": "missing prediction id",
            "status": 502,
            "body": body,
            "phase": "submit",
        }

    status = body.get("status")
    if status in {"failed", "canceled"}:
        return {
            "ok": False,
            "error": "failed",
            "detail": body.get("error") or status,
            "status": 502,
            "prediction": body,
            "prediction_id": prediction_id,
            "get_url": get_url,
            "phase": "run",
        }

    return {
        "ok": True,
        "prediction_id": prediction_id,
        "get_url": get_url,
        "prediction": body,
        "phase": "submit",
    }


def _replicate_wait(get_url: str, deadline: float) -> dict:
    token = _replicate_token()
    if not token:
        return {"ok": False, "error": "not_configured", "status": 503, "phase": "run"}
    headers = {"Authorization": f"Bearer {token}"}
    last_body = None
    while time.time() < deadline:
        time.sleep(2)
        try:
            poll = requests.get(get_url, headers=headers, timeout=20)
            pdata = poll.json()
            last_body = pdata
        except (requests.RequestException, ValueError) as exc:
            if time.time() >= deadline:
                return {
                    "ok": False,
                    "error": "upstream",
                    "detail": str(exc.__class__.__name__),
                    "status": 502,
                    "phase": "run",
                }
            continue
        st = pdata.get("status")
        if st == "succeeded":
            return {"ok": True, "prediction": pdata, "phase": "run"}
        if st in {"failed", "canceled"}:
            return {
                "ok": False,
                "error": "failed",
                "detail": pdata.get("error") or st,
                "status": 502,
                "prediction": pdata,
                "phase": "run",
            }
    return {
        "ok": False,
        "error": "timeout",
        "detail": "prediction still running",
        "status": 504,
        "prediction": last_body,
        "phase": "run",
    }


def _replicate_cancel(prediction_id: str | None) -> None:
    if not prediction_id:
        return
    token = _replicate_token()
    if not token:
        return
    try:
        requests.post(
            f"https://api.replicate.com/v1/predictions/{prediction_id}/cancel",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except requests.RequestException:
        pass


def _run_replicate_prediction(replicate_model: str, input_payload: dict, wait_seconds: int = 120) -> dict:
    submitted = _replicate_submit(replicate_model, input_payload)
    if not submitted.get("ok"):
        return submitted
    prediction = submitted.get("prediction") or {}
    if prediction.get("status") == "succeeded":
        return {"ok": True, "prediction": prediction}
    deadline = time.time() + max(int(wait_seconds or 60), 5)
    result = _replicate_wait(submitted["get_url"], deadline)
    if result.get("error") == "timeout":
        _replicate_cancel(submitted.get("prediction_id"))
    return result


def _fal_submit(fal_model: str, input_payload: dict) -> dict:
    key = _fal_key()
    if not key:
        return {"ok": False, "error": "not_configured", "status": 503, "phase": "submit"}

    headers = {
        "Authorization": f"Key {key}",
        "Content-Type": "application/json",
    }
    submit_url = f"https://queue.fal.run/{fal_model.lstrip('/')}"
    try:
        resp = requests.post(submit_url, headers=headers, json=input_payload, timeout=30)
    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": "upstream",
            "detail": str(exc.__class__.__name__),
            "status": 502,
            "phase": "submit",
        }

    try:
        body = resp.json()
    except ValueError:
        return {
            "ok": False,
            "error": "bad_response",
            "detail": resp.text[:300],
            "status": 502,
            "phase": "submit",
        }

    if resp.status_code >= 400:
        detail = body.get("detail") or body.get("error") or resp.text[:300]
        return {
            "ok": False,
            "error": "upstream",
            "detail": detail,
            "status": resp.status_code,
            "body": body,
            "phase": "submit",
        }

    status_url = body.get("status_url")
    response_url = body.get("response_url")
    request_id = body.get("request_id")
    if not status_url or not response_url:
        if any(k in body for k in ("images", "image", "video", "audio", "output", "text")):
            return {
                "ok": True,
                "request_id": request_id,
                "status_url": status_url,
                "response_url": response_url,
                "prediction": body,
                "phase": "submit",
            }
        return {
            "ok": False,
            "error": "bad_response",
            "detail": "missing fal queue urls",
            "status": 502,
            "body": body,
            "phase": "submit",
        }

    return {
        "ok": True,
        "request_id": request_id,
        "status_url": status_url,
        "response_url": response_url,
        "prediction": body,
        "phase": "submit",
    }


def _fal_wait(status_url: str, response_url: str, deadline: float) -> dict:
    key = _fal_key()
    if not key:
        return {"ok": False, "error": "not_configured", "status": 503, "phase": "run"}
    headers = {
        "Authorization": f"Key {key}",
        "Content-Type": "application/json",
    }
    last_body = None
    request_id = None
    while time.time() < deadline:
        try:
            poll = requests.get(f"{status_url}?logs=0", headers=headers, timeout=20)
            pdata = poll.json()
            last_body = pdata
        except (requests.RequestException, ValueError) as exc:
            if time.time() >= deadline:
                return {
                    "ok": False,
                    "error": "upstream",
                    "detail": str(exc.__class__.__name__),
                    "status": 502,
                    "phase": "run",
                }
            time.sleep(2)
            continue

        status = pdata.get("status")
        request_id = pdata.get("request_id") or request_id
        if status == "COMPLETED":
            try:
                result = requests.get(response_url, headers=headers, timeout=60)
                rbody = result.json()
            except (requests.RequestException, ValueError) as exc:
                return {
                    "ok": False,
                    "error": "upstream",
                    "detail": str(exc.__class__.__name__),
                    "status": 502,
                    "phase": "run",
                }
            if result.status_code >= 400:
                return {
                    "ok": False,
                    "error": "upstream",
                    "detail": rbody.get("detail") or rbody.get("error") or result.text[:300],
                    "status": result.status_code,
                    "body": rbody,
                    "phase": "run",
                }
            if isinstance(rbody, dict):
                rbody.setdefault("request_id", request_id)
            return {"ok": True, "prediction": rbody, "phase": "run"}
        if status in {"FAILED", "CANCELLED", "CANCELED"}:
            return {
                "ok": False,
                "error": "failed",
                "detail": pdata.get("error") or status,
                "status": 502,
                "prediction": pdata,
                "phase": "run",
            }
        time.sleep(2)

    return {
        "ok": False,
        "error": "timeout",
        "detail": "fal request still running",
        "status": 504,
        "prediction": last_body,
        "phase": "run",
    }


def _fal_cancel(fal_model: str | None = None, request_id: str | None = None, **_kwargs) -> None:
    """Best-effort cancel for fal queue; ignore errors if unsupported."""
    if not fal_model or not request_id:
        return
    key = _fal_key()
    if not key:
        return
    try:
        requests.put(
            f"https://queue.fal.run/{fal_model.lstrip('/')}/requests/{request_id}/cancel",
            headers={"Authorization": f"Key {key}"},
            timeout=10,
        )
    except requests.RequestException:
        pass


def _run_fal_prediction(fal_model: str, input_payload: dict, wait_seconds: int = 120) -> dict:
    """Submit to fal.ai queue and poll until COMPLETED (or timeout)."""
    submitted = _fal_submit(fal_model, input_payload)
    if not submitted.get("ok"):
        return submitted
    prediction = submitted.get("prediction") or {}
    if any(k in prediction for k in ("images", "image", "video", "audio", "output", "text")) and not submitted.get(
        "status_url"
    ):
        return {"ok": True, "prediction": prediction}
    if not submitted.get("status_url") or not submitted.get("response_url"):
        return {"ok": True, "prediction": prediction}
    deadline = time.time() + max(int(wait_seconds or 60), 30)
    result = _fal_wait(submitted["status_url"], submitted["response_url"], deadline)
    if result.get("error") == "timeout":
        _fal_cancel(fal_model, submitted.get("request_id"))
    return result


def _higgsfield_extract_outputs(prediction: dict, kind: str) -> list[str]:
    """Normalize Higgsfield result payload into media URLs."""
    if not isinstance(prediction, dict):
        return []
    urls: list[str] = []

    def _media_url(item) -> str | None:
        if isinstance(item, dict):
            u = item.get("url") or item.get("uri")
            return u if isinstance(u, str) and u else None
        if isinstance(item, str) and item:
            return item
        return None

    for key in ("video", "audio"):
        u = _media_url(prediction.get(key))
        if u:
            urls.append(u)
    for key in ("images", "audios"):
        items = prediction.get(key)
        if isinstance(items, list):
            for item in items:
                u = _media_url(item)
                if u:
                    urls.append(u)
    if not urls:
        urls.extend(_flatten_output(prediction.get("output")))
    return urls


def _higgsfield_submit(hf_model: str, input_payload: dict) -> dict:
    """Submit to Higgsfield queue via official SDK (server-side HF_KEY)."""
    if not _higgsfield_key():
        return {"ok": False, "error": "not_configured", "status": 503, "phase": "submit"}
    try:
        import higgsfield_client as hf
        from higgsfield_client.exceptions import CredentialsMissedError, HiggsfieldClientError
    except ImportError:
        return {
            "ok": False,
            "error": "not_configured",
            "detail": "higgsfield-client not installed",
            "status": 503,
            "phase": "submit",
        }
    try:
        ctrl = hf.submit(hf_model, input_payload or {})
    except CredentialsMissedError:
        return {"ok": False, "error": "not_configured", "status": 503, "phase": "submit"}
    except HiggsfieldClientError as exc:
        detail = str(exc)[:400]
        low = detail.lower()
        if "not_enough_credits" in low or "insufficient" in low:
            return {
                "ok": False,
                "error": "insufficient_credits",
                "detail": detail,
                "status": 402,
                "phase": "submit",
            }
        return {
            "ok": False,
            "error": "upstream",
            "detail": detail,
            "status": 502,
            "phase": "submit",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": "upstream",
            "detail": str(exc.__class__.__name__),
            "status": 502,
            "phase": "submit",
        }
    return {
        "ok": True,
        "request_id": getattr(ctrl, "request_id", None),
        "status_url": getattr(ctrl, "status_url", None),
        "response_url": getattr(ctrl, "response_url", None),
        "cancel_url": getattr(ctrl, "cancel_url", None),
        "prediction": {},
        "phase": "submit",
    }


def _higgsfield_wait(request_id: str | None, deadline: float) -> dict:
    if not request_id:
        return {"ok": False, "error": "bad_response", "detail": "missing request_id", "status": 502, "phase": "run"}
    if not _higgsfield_key():
        return {"ok": False, "error": "not_configured", "status": 503, "phase": "run"}
    try:
        import higgsfield_client as hf
        from higgsfield_client import Cancelled, Completed, Failed, NSFW
        from higgsfield_client.exceptions import HiggsfieldClientError
    except ImportError:
        return {
            "ok": False,
            "error": "not_configured",
            "detail": "higgsfield-client not installed",
            "status": 503,
            "phase": "run",
        }
    last_status = None
    while time.time() < deadline:
        try:
            st = hf.status(request_id=request_id)
            last_status = type(st).__name__
        except HiggsfieldClientError as exc:
            return {
                "ok": False,
                "error": "upstream",
                "detail": str(exc)[:400],
                "status": 502,
                "phase": "run",
            }
        except Exception as exc:  # noqa: BLE001
            if time.time() >= deadline:
                return {
                    "ok": False,
                    "error": "upstream",
                    "detail": str(exc.__class__.__name__),
                    "status": 502,
                    "phase": "run",
                }
            time.sleep(2)
            continue

        if isinstance(st, Completed):
            try:
                body = hf.result(request_id=request_id)
            except Exception as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "error": "upstream",
                    "detail": str(exc)[:400],
                    "status": 502,
                    "phase": "run",
                }
            if not isinstance(body, dict):
                body = {"raw": body}
            body.setdefault("request_id", request_id)
            body.setdefault("status", "completed")
            return {"ok": True, "prediction": body, "phase": "run"}

        if isinstance(st, NSFW):
            return {
                "ok": False,
                "error": "moderated",
                "detail": "content moderated",
                "status": 422,
                "phase": "run",
            }
        if isinstance(st, Cancelled):
            return {
                "ok": False,
                "error": "cancelled",
                "detail": "request cancelled",
                "status": 499,
                "phase": "run",
            }
        if isinstance(st, Failed):
            return {
                "ok": False,
                "error": "failed",
                "detail": last_status or "failed",
                "status": 502,
                "phase": "run",
            }
        time.sleep(2)

    return {
        "ok": False,
        "error": "timeout",
        "detail": f"higgsfield still {last_status or 'running'}",
        "status": 504,
        "phase": "run",
    }


def _higgsfield_cancel(request_id: str | None) -> None:
    if not request_id or not _higgsfield_key():
        return
    try:
        import higgsfield_client as hf
        hf.cancel(request_id=request_id)
    except Exception:  # noqa: BLE001
        pass


def _run_higgsfield_prediction(hf_model: str, input_payload: dict, wait_seconds: int = 120) -> dict:
    submitted = _higgsfield_submit(hf_model, input_payload)
    if not submitted.get("ok"):
        return submitted
    prediction = submitted.get("prediction") or {}
    if prediction.get("video"):
        return {"ok": True, "prediction": prediction}
    deadline = time.time() + max(int(wait_seconds or 60), 30)
    result = _higgsfield_wait(submitted.get("request_id"), deadline)
    if result.get("error") == "timeout":
        _higgsfield_cancel(submitted.get("request_id"))
    return result


def _groq_chat_completion(messages: list, wait_seconds: int = 60) -> dict:
    """Прямой вызов Groq — запасной путь, когда OmniRoute free-роуты не отвечают."""
    groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not groq_key:
        return {"error": "not_configured", "detail": "GROQ_API_KEY missing", "status": 503}
    models: list[str] = []
    for candidate in (
        (os.getenv("GROQ_CHAT_MODEL") or "").strip(),
        (os.getenv("GROQ_MODEL") or "").strip(),
        "openai/gpt-oss-20b",
        "llama-3.1-8b-instant",
    ):
        if candidate and candidate not in models:
            models.append(candidate)
    last: dict = {"error": "upstream", "detail": "groq_failed", "status": 502}
    for model in models:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": messages, "temperature": 0.4, "max_tokens": 1024, "stream": False},
                timeout=max(15, min(wait_seconds, 90)),
            )
        except requests.RequestException as exc:
            last = {"error": "upstream", "detail": str(exc.__class__.__name__), "status": 502}
            continue
        try:
            data = resp.json()
        except ValueError:
            last = {"error": "bad_response", "detail": resp.text[:300], "status": 502}
            continue
        if resp.status_code >= 400:
            detail = data.get("error") or data.get("detail") or resp.text[:300]
            if isinstance(detail, dict):
                detail = detail.get("message") or detail
            last = {"error": "upstream", "detail": detail, "status": resp.status_code, "body": data}
            continue
        text = ""
        choices = data.get("choices") if isinstance(data, dict) else None
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict):
                text = _extract_chat_message_text(msg)
            if not text and isinstance(choices[0], dict):
                text = str(choices[0].get("text") or "")
        if not str(text).strip():
            last = {"error": "upstream", "detail": "empty groq reply", "status": 502}
            continue
        return {
            "ok": True,
            "prediction": {
                "id": data.get("id") if isinstance(data, dict) else None,
                "status": "succeeded",
                "output": text,
                "raw": data,
                "via": "groq",
                "model": data.get("model") or model,
            },
        }
    return last


def _run_omniroute_prediction(omni_model: str, input_payload: dict, wait_seconds: int = 120) -> dict:
    """Call OmniRoute OpenAI-compatible /v1/chat/completions."""
    key = _omniroute_key()
    prompt = ""
    if isinstance(input_payload, dict):
        prompt = (input_payload.get("prompt") or input_payload.get("text") or "").strip()
        if not prompt and isinstance(input_payload.get("messages"), list):
            # already chat-shaped
            messages = input_payload["messages"]
        else:
            messages = [{"role": "user", "content": prompt}]
    else:
        messages = [{"role": "user", "content": str(input_payload)}]

    if not messages or not str(messages[-1].get("content") or "").strip():
        return {"error": "empty", "detail": "prompt required", "status": 400}

    omni_err: dict | None = None
    groq_key = (os.getenv("GROQ_API_KEY") or "").strip()
    # auto/coding:free и подобные free-роуты OmniRoute часто 10–20с 403 — для них сразу Groq
    free_omni = "free" in str(omni_model or "").lower()
    if free_omni and groq_key:
        fallback = _groq_chat_completion(messages, wait_seconds=min(wait_seconds, 45))
        if fallback.get("ok"):
            return fallback

    if key:
        base = _omniroute_base()
        url = f"{base}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": omni_model,
            "messages": messages,
            "stream": False,
        }
        # free-роуты не ждём долго — всё равно уйдём на Groq
        omni_timeout = 12 if free_omni else (wait_seconds + 30)
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=omni_timeout)
        except requests.RequestException as exc:
            omni_err = {"error": "upstream", "detail": str(exc.__class__.__name__), "status": 502}
        else:
            try:
                data = resp.json()
            except ValueError:
                omni_err = {"error": "bad_response", "detail": resp.text[:300], "status": 502}
            else:
                if resp.status_code >= 400:
                    detail = data.get("error") or data.get("detail") or resp.text[:300]
                    if isinstance(detail, dict):
                        detail = detail.get("message") or detail
                    omni_err = {"error": "upstream", "detail": detail, "status": resp.status_code, "body": data}
                else:
                    # Normalize to prediction-like object used by formatters.
                    text = ""
                    choices = data.get("choices") if isinstance(data, dict) else None
                    if isinstance(choices, list) and choices:
                        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
                        if isinstance(msg, dict):
                            content = msg.get("content")
                            if isinstance(content, str):
                                text = content
                            elif isinstance(content, list):
                                parts = []
                                for part in content:
                                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                                        parts.append(part["text"])
                                    elif isinstance(part, str):
                                        parts.append(part)
                                text = "\n".join(parts)
                        if not text and isinstance(choices[0], dict):
                            text = str(choices[0].get("text") or "")

                    prediction = {
                        "id": data.get("id") if isinstance(data, dict) else None,
                        "status": "succeeded",
                        "output": text,
                        "raw": data,
                    }
                    return {"ok": True, "prediction": prediction}
    else:
        omni_err = {"error": "not_configured", "detail": "OMNIROUTE_API_KEY missing", "status": 503}

    # Free-роуты OmniRoute часто 403/502 (OpenCode only) — отвечаем через Groq, если ключ есть.
    if (os.getenv("GROQ_API_KEY") or "").strip():
        fallback = _groq_chat_completion(messages, wait_seconds=wait_seconds)
        if fallback.get("ok"):
            return fallback
        if omni_err is None:
            return fallback
    return omni_err or {"error": "upstream", "detail": "omniroute_failed", "status": 502}


@app.route("/api/channels/health", methods=["GET"])
def api_channels_health():
    try:
        from queue_runtime.health import read_all_health
        from queue_runtime import (
            CHANNELS,
            PROCESSING_BY_CHANNEL,
            QUEUE_BY_CHANNEL,
            QUEUE_INBOUND,
            get_redis,
            inflight_key,
        )

        r = get_redis()
        queues = {
            "inbound": int(r.llen(QUEUE_INBOUND) or 0),
        }
        for ch, key in QUEUE_BY_CHANNEL.items():
            queues[ch] = int(r.llen(key) or 0)
        processing = {
            ch: int(r.llen(PROCESSING_BY_CHANNEL[ch]) or 0) for ch in CHANNELS
        }
        inflight = {
            ch: int(r.get(inflight_key(ch)) or 0) for ch in CHANNELS
        }
        return jsonify({
            "channels": read_all_health(),
            "queues": queues,
            "processing": processing,
            "inflight": inflight,
        })
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "health_unavailable", "detail": str(exc)}), 503


@app.route("/api/admin/queues", methods=["GET"])
def api_admin_queues():
    emails = {
        e.strip().lower()
        for e in (os.getenv("ADMIN_EMAILS") or "").split(",")
        if e.strip()
    }
    user_email = ""
    try:
        uid = session.get("user_id")
        if uid:
            u = User.query.get(uid)
            user_email = (u.email or "").lower() if u else ""
    except Exception:  # noqa: BLE001
        user_email = ""
    if user_email not in emails:
        return jsonify({"error": "forbidden"}), 403
    return api_channels_health()


_INTEGRATION_PRICE_CACHE: dict[str, object] = {"mtime": None, "rate": None, "map": {}}
_USD_RUB_CACHE: dict[str, object] = {"rate": None, "fetched_at": 0.0}


def _usd_rub_rate() -> float:
    """Current USD→RUB rate (CBR), cached ~6h. Override: USD_RUB_RATE."""
    env = (os.getenv("USD_RUB_RATE") or "").strip()
    if env:
        try:
            return float(env.replace(",", "."))
        except ValueError:
            pass
    now = time.time()
    cached = _USD_RUB_CACHE.get("rate")
    fetched_at = float(_USD_RUB_CACHE.get("fetched_at") or 0)
    if isinstance(cached, (int, float)) and cached > 0 and (now - fetched_at) < 6 * 3600:
        return float(cached)
    rate = 86.47  # fallback ≈ ЦБ 2026-09-09
    try:
        resp = requests.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=6)
        if resp.status_code < 400:
            val = resp.json().get("Valute", {}).get("USD", {}).get("Value")
            if val is not None:
                rate = float(val)
    except Exception:  # noqa: BLE001
        pass
    _USD_RUB_CACHE["rate"] = rate
    _USD_RUB_CACHE["fetched_at"] = now
    return rate


def _format_rub(amount_rub: float) -> str:
    if amount_rub <= 0:
        return "0 ₽"
    if amount_rub < 1:
        s = f"{amount_rub:.2f}".rstrip("0").rstrip(".")
        return s.replace(".", ",") + " ₽"
    if amount_rub < 20:
        s = f"{amount_rub:.1f}".rstrip("0").rstrip(".")
        return s.replace(".", ",") + " ₽"
    n = int(round(amount_rub))
    # 12 345 ₽
    grouped = f"{n:,}".replace(",", " ")
    return f"{grouped} ₽"


def _price_usd_to_rub(price: str, rate: float | None = None) -> str:
    """Replace $ amounts in a price string with ₽ at the given USD rate."""
    text = (price or "").strip()
    if not text:
        return ""
    if "$" not in text:
        # free-tier и прочее без долларов — слегка русифицируем
        low = text.lower()
        if "free" in low:
            return "бесплатно"
        return text
    fx = rate if rate is not None else _usd_rub_rate()

    def repl(match: re.Match[str]) -> str:
        raw = match.group(1).replace(",", "")
        try:
            usd = float(raw)
        except ValueError:
            return match.group(0)
        return _format_rub(usd * fx)

    out = re.sub(r"\$\s*(\d+(?:[.,]\d+)?)", repl, text)
    # подчистить англ. хвосты вокруг уже сконвертированных сумм
    out = out.replace(" per million input tokens", " / млн входных токенов")
    out = out.replace(" per million output tokens", " / млн выходных токенов")
    out = out.replace(" per thousand output tokens", " / тыс. выходных токенов")
    out = out.replace(" per thousand input tokens", " / тыс. входных токенов")
    out = out.replace(" per second of output video", " / сек видео")
    out = out.replace(" per output video", " / видео")
    out = out.replace(" per output image", " / изображение")
    out = out.replace(" per input image megapixel", " / Мп входа")
    out = out.replace(" per image megapixel", " / Мп")
    out = out.replace(" megapixel", " Мп")
    out = out.replace(" per image", " / изображение")
    out = out.replace(" per video", " / видео")
    out = out.replace(" per megapixel", " / Мп")
    out = out.replace(" per second", " / сек")
    out = out.replace(" per run", " / запуск")
    out = out.replace(" per prediction", " / генерацию")
    out = out.replace(" per 1M tokens", " / млн токенов")
    out = out.replace(" per million tokens", " / млн токенов")
    out = re.sub(r"\s*\(or around [^)]+\)", "", out, flags=re.I)
    out = re.sub(r"\s*\(or [^)]+\)", "", out, flags=re.I)
    out = re.sub(r"\s{2,}", " ", out).strip(" ·")
    return out


def _short_price_label(price: str) -> str:
    text = (price or "").strip()
    if not text:
        return ""
    part = text.split("·")[0].strip()
    if len(part) > 72:
        return part[:69] + "…"
    return part


def _integration_prices() -> dict[str, str]:
    """Load short/full prices from catalog.json, converted USD→RUB."""
    path = os.path.join(BASE_DIR, "models_catalog", "catalog.json")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    rate = _usd_rub_rate()
    if (
        _INTEGRATION_PRICE_CACHE.get("mtime") == mtime
        and _INTEGRATION_PRICE_CACHE.get("rate") == rate
    ):
        return _INTEGRATION_PRICE_CACHE["map"]  # type: ignore[return-value]
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, str] = {}
    for row in data.get("models") or []:
        if not isinstance(row, dict):
            continue
        mid = row.get("id")
        price = row.get("price") or ""
        if not mid or not price:
            continue
        rub = _price_usd_to_rub(str(price), rate)
        out[str(mid)] = _short_price_label(rub)
        out[f"{mid}__full"] = rub
    out["__usd_rub_rate"] = f"{rate:.4f}".rstrip("0").rstrip(".")
    _INTEGRATION_PRICE_CACHE["mtime"] = mtime
    _INTEGRATION_PRICE_CACHE["rate"] = rate
    _INTEGRATION_PRICE_CACHE["map"] = out
    return out


def _integration_vitrine_tags(spec: dict) -> list[str]:
    """Russian filter tags for homepage / catalog cards."""
    tags: list[str] = []
    inputs = set(spec.get("inputs") or [])
    outputs = set(spec.get("outputs") or [])
    kind = (spec.get("kind") or "").lower()
    notes = (spec.get("notes") or "").lower()

    if kind == "image" or "image" in outputs:
        tags.append("генерация-изображений")
    if kind == "video" or "video" in outputs:
        tags.append("генерация-видео")
    if kind in {"audio", "stt"} or "audio" in outputs or "music" in outputs:
        tags.append("аудио")
    if "music" in outputs or "music" in notes or "музык" in notes:
        tags.append("генерация-музыки")
    if "text" in inputs and "image" in outputs:
        tags.append("текст-в-изображение")
    if "text" in inputs and "video" in outputs:
        tags.append("текст-в-видео")
    if "image" in inputs and "video" in outputs:
        tags.append("изображение-в-видео")
    if "image" in inputs and "image" in outputs and "upscale" in notes:
        tags.append("увеличение-разрешения")

    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _integration_vitrine_description(spec: dict) -> str:
    notes = (spec.get("notes") or "").strip()
    if notes and "required" not in notes.lower():
        return notes
    ins = ", ".join(spec.get("inputs") or []) or "текст"
    outs = ", ".join(spec.get("outputs") or []) or "результат"
    return f"{spec.get('name') or spec.get('id')}: {ins} → {outs}."


_COVERS_PATH = os.path.join(BASE_DIR, "models_catalog", "covers.json")
_COVERS_CACHE: dict | None = None
_COVER_FETCH_TRIED: set[str] = set()


def _load_covers() -> dict:
    global _COVERS_CACHE
    if _COVERS_CACHE is not None:
        return _COVERS_CACHE
    try:
        with open(_COVERS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _COVERS_CACHE = data if isinstance(data, dict) else {}
    except Exception:
        _COVERS_CACHE = {}
    return _COVERS_CACHE


def _save_covers(covers: dict) -> None:
    global _COVERS_CACHE
    _COVERS_CACHE = covers
    try:
        os.makedirs(os.path.dirname(_COVERS_PATH), exist_ok=True)
        with open(_COVERS_PATH, "w", encoding="utf-8") as f:
            json.dump(covers, f, ensure_ascii=False, indent=2)
    except Exception:
        pass



def _public_model_name(name: str) -> str:
    original = (name or "").strip()
    text = original
    text = re.sub(r"(?i)\bOmniRoute\b", "", text)
    text = re.sub(r"(?i)\bReplicate\b", "", text)
    text = re.sub(r"(?i)\bfal(?:\.ai)?\b", "", text)
    text = re.sub(r"^Ассистент\s*[·•\-—]\s*", "", text)
    text = re.sub(r"\s*[·•\-—]\s*$", "", text)
    text = re.sub(r"^\s*[·•\-—]\s*", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if text:
        return text
    if re.search(r"(?i)assistant|ассистент|omniroute", original):
        return "Ассистент"
    return "Модель"


def _public_notes(notes: str | None) -> str:
    text = (notes or "").strip()
    if not text:
        return ""
    if re.search(r"(?i)omniroute|replicate|fal\.ai|\bfal\b", text):
        return ""
    return text

def _is_media_url(value: str | None) -> bool:
    v = (value or "").strip()
    return bool(v) and (v.startswith("http://") or v.startswith("https://") or v.startswith("/assets/"))


def _fetch_replicate_cover(replicate_model: str) -> str | None:
    token = _replicate_token()
    if not token or "/" not in (replicate_model or ""):
        return None
    owner, name = replicate_model.split("/", 1)
    try:
        resp = requests.get(
            f"https://api.replicate.com/v1/models/{owner}/{name}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code >= 400:
            return None
        body = resp.json()
        cover = body.get("cover_image_url") or body.get("cover_image")
        # Prefer still images for UI thumbs; skip bare mp4 covers
        if isinstance(cover, str) and cover.startswith("http") and not cover.lower().endswith(".mp4"):
            return cover
        return None
    except Exception:
        return None


def _fetch_replicate_owner_logo(replicate_model: str) -> str | None:
    """Owner/org avatar from Replicate model page (the square logo next to owner/name)."""
    if "/" not in (replicate_model or ""):
        return None
    owner, name = replicate_model.split("/", 1)
    try:
        html = requests.get(
            f"https://replicate.com/{owner}/{name}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        ).text
    except Exception:
        return None
    # Prefer organization avatars hosted on replicate.delivery CDNs
    avatars = re.findall(
        r'https?://[^"\']+models_organizations_avatar[^"\']+\.(?:webp|png|jpg|jpeg)',
        html,
        flags=re.I,
    )
    if not avatars:
        avatars = re.findall(
            r'https?://[^"\']+(?:organizations_avatar|placeholder-avatar)[^"\']+\.(?:webp|png|jpg|jpeg|svg)',
            html,
            flags=re.I,
        )
    for url in avatars:
        if "placeholder" in url.lower():
            continue
        return url
    return avatars[0] if avatars else None


def _first_media_url(value) -> str | None:
    if isinstance(value, str) and value.startswith("http"):
        return value
    if isinstance(value, list):
        for item in value:
            found = _first_media_url(item)
            if found:
                return found
    if isinstance(value, dict):
        for key in ("url", "href", "video", "image", "output"):
            found = _first_media_url(value.get(key))
            if found:
                return found
    return None


def _fetch_replicate_preview_media(replicate_model: str) -> dict:
    """Pull default example output/preview from Replicate model API.

    Returns {image, video} URLs when available. For video models the cover is often
    an mp4 — that goes into video; still frames go into image.
    """
    token = _replicate_token()
    out: dict[str, str] = {}
    if not token or "/" not in (replicate_model or ""):
        return out
    owner, name = replicate_model.split("/", 1)
    try:
        resp = requests.get(
            f"https://api.replicate.com/v1/models/{owner}/{name}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        if resp.status_code >= 400:
            return out
        body = resp.json() if isinstance(resp.json(), dict) else {}
    except Exception:
        return out

    cover = body.get("cover_image_url") or body.get("cover_image")
    example = body.get("default_example") if isinstance(body.get("default_example"), dict) else {}
    output_url = _first_media_url(example.get("output")) if example else None

    for cand in (output_url, cover if isinstance(cover, str) else None):
        if not cand or not str(cand).startswith("http"):
            continue
        low = str(cand).lower()
        if any(low.endswith(ext) or f".{ext}?" in low for ext in ("mp4", "webm", "mov")):
            out.setdefault("video", str(cand))
        elif any(low.endswith(ext) or f".{ext}?" in low for ext in ("jpg", "jpeg", "png", "webp", "gif")):
            out.setdefault("image", str(cand))
        else:
            # unknown — treat as video if model looks video-ish via URL path, else image
            if "video" in low or "/tmp" in low:
                out.setdefault("video", str(cand))
            else:
                out.setdefault("image", str(cand))
    return out


def _download_url_to_assets(url: str, rel_under_assets: str, *, max_bytes: int = 40_000_000) -> str | None:
    """Download remote media into assets/ and return public /assets/... path."""
    if not url or not url.startswith("http"):
        return None
    rel = rel_under_assets.lstrip("/")
    if rel.startswith("assets/"):
        rel = rel[len("assets/"):]
    abs_path = os.path.join(BASE_DIR, "assets", rel)
    public = "/assets/" + rel.replace("\\", "/")
    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with requests.get(url, stream=True, timeout=120) as resp:
            if resp.status_code >= 400:
                return None
            total = 0
            chunks: list[bytes] = []
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    return None
                chunks.append(chunk)
            raw = b"".join(chunks)
        if abs_path.lower().endswith(".mp4") and len(raw) > 2_000_000:
            import shutil
            import subprocess
            import tempfile

            if shutil.which("ffmpeg"):
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                    tmp.write(raw)
                    src = tmp.name
                try:
                    proc = subprocess.run(
                        [
                            "ffmpeg", "-y", "-i", src,
                            "-vf", "scale='min(720,iw)':-2",
                            "-c:v", "libx264", "-crf", "28", "-preset", "fast", "-an",
                            abs_path,
                        ],
                        capture_output=True,
                        timeout=180,
                    )
                    if proc.returncode == 0 and os.path.isfile(abs_path) and os.path.getsize(abs_path) > 0:
                        return public
                except Exception:
                    pass
                finally:
                    try:
                        os.unlink(src)
                    except OSError:
                        pass
        with open(abs_path, "wb") as f:
            f.write(raw)
        return public
    except Exception:
        return None


def _extract_video_poster(video_public: str, poster_rel_under_assets: str) -> str | None:
    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        return None
    video_abs = os.path.join(BASE_DIR, video_public.lstrip("/"))
    rel = poster_rel_under_assets.lstrip("/")
    if rel.startswith("assets/"):
        rel = rel[len("assets/"):]
    poster_abs = os.path.join(BASE_DIR, "assets", rel)
    poster_public = "/assets/" + rel.replace("\\", "/")
    if not os.path.isfile(video_abs):
        return None
    try:
        os.makedirs(os.path.dirname(poster_abs), exist_ok=True)
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", video_abs, "-ss", "0.4", "-vframes", "1", poster_abs],
            capture_output=True,
            timeout=60,
        )
        if proc.returncode == 0 and os.path.isfile(poster_abs) and os.path.getsize(poster_abs) > 0:
            return poster_public
    except Exception:
        return None
    return None


def _ingest_replicate_preview(mid: str, replicate_model: str, *, force: bool = False) -> dict:
    """Download Replicate owner logo + default example output/preview into local assets."""
    covers = _load_covers()
    result: dict[str, str] = {}

    # Owner/org avatar → model logo thumb (what Replicate shows next to owner/name)
    if force or not covers.get(mid) or not str(covers.get(mid) or "").startswith("/assets/models/"):
        logo_url = _fetch_replicate_owner_logo(replicate_model)
        if logo_url:
            ext = ".webp"
            low = logo_url.lower()
            for e in (".png", ".jpg", ".jpeg", ".svg", ".webp"):
                if e in low:
                    ext = ".jpg" if e == ".jpeg" else e
                    break
            local_logo = _download_url_to_assets(logo_url, f"models/{mid}-logo{ext}")
            if local_logo:
                # also keep canonical thumb path without -logo suffix for older clients
                mirror = _download_url_to_assets(logo_url, f"models/{mid}{ext}")
                thumb = mirror or local_logo
                covers[mid] = thumb
                covers[replicate_model] = thumb
                covers[f"{mid}__logo"] = local_logo
                result["cover"] = thumb
                result["logo"] = local_logo

    if not force and covers.get(f"{mid}__example_video") and covers.get(f"{mid}__example"):
        result["example"] = str(covers.get(f"{mid}__example") or "")
        result["example_video"] = str(covers.get(f"{mid}__example_video") or "")
        if covers.get(mid):
            result.setdefault("cover", str(covers[mid]))
        if result:
            _save_covers(covers)
        return result

    media = _fetch_replicate_preview_media(replicate_model)
    video_url = media.get("video")
    image_url = media.get("image")

    if video_url:
        local_video = _download_url_to_assets(video_url, f"models/examples/{mid}.mp4")
        if local_video:
            covers[f"{mid}__example_video"] = local_video
            covers[f"{replicate_model}__example_video"] = local_video
            result["example_video"] = local_video
            poster = _extract_video_poster(local_video, f"models/examples/{mid}.jpg")
            if poster:
                covers[f"{mid}__example"] = poster
                covers[f"{replicate_model}__example"] = poster
                result["example"] = poster

    if image_url and not result.get("example"):
        ext = ".jpg"
        low = image_url.lower()
        for e in (".png", ".webp", ".gif", ".jpeg", ".jpg"):
            if e in low:
                ext = ".jpg" if e == ".jpeg" else e
                break
        local_img = _download_url_to_assets(image_url, f"models/examples/{mid}{ext}")
        if local_img:
            covers[f"{mid}__example"] = local_img
            covers[f"{replicate_model}__example"] = local_img
            result["example"] = local_img

    if result:
        _save_covers(covers)
    return result


def _integration_image(spec: dict, *, fetch_missing: bool = False) -> str:
    """Preview image: cached cover (http or /assets), else kind-based stock photo."""
    covers = _load_covers()
    mid = spec["id"]
    if _is_media_url(covers.get(mid)):
        return str(covers[mid]).strip()
    rep = (spec.get("replicate_model") or "").strip()
    if rep and _is_media_url(covers.get(rep)):
        return str(covers[rep]).strip()

    if fetch_missing and rep and rep not in _COVER_FETCH_TRIED:
        _COVER_FETCH_TRIED.add(rep)
        cover = _fetch_replicate_cover(rep)
        if cover:
            covers[mid] = cover
            covers[rep] = cover
            _save_covers(covers)
            return cover

    kind = (spec.get("kind") or "").lower()
    outputs = set(spec.get("outputs") or [])
    tag_names: list[str] = []
    if kind == "video" or "video" in outputs:
        tag_names.append("video-generation")
    elif kind == "image" or "image" in outputs:
        tag_names.append("image-generation")
    elif kind in {"audio", "stt"} or "audio" in outputs or "music" in outputs:
        tag_names.append("music-generation")
    else:
        tag_names.append("image-generation")
    return get_image_for_model(tag_names, spec.get("provider") or "model", mid)


def _integration_example(spec: dict) -> str:
    """Example generation still for model cards."""
    covers = _load_covers()
    mid = spec["id"]
    keys = [f"{mid}__example", mid]
    rep = (spec.get("replicate_model") or "").strip()
    if rep:
        keys.extend([f"{rep}__example", rep])
    # Share Wan preview across replicate + fal variants
    if re.search(r"(?i)wan[-_]?3", mid) or re.search(r"(?i)wan[-_]?3", rep):
        keys.extend([
            "wan-3-0__example",
            "alibaba/wan-3__example",
            "wan-3-0",
            "alibaba/wan-3",
        ])
    for key in keys:
        if _is_media_url(covers.get(key)):
            return str(covers[key]).strip()
    return _integration_image(spec, fetch_missing=False)


def _integration_example_video(spec: dict) -> str:
    """Locally cached Replicate default-example video (output/preview), if any."""
    covers = _load_covers()
    mid = spec["id"]
    keys = [f"{mid}__example_video"]
    rep = (spec.get("replicate_model") or "").strip()
    if rep:
        keys.append(f"{rep}__example_video")
    if re.search(r"(?i)wan[-_]?3", mid) or re.search(r"(?i)wan[-_]?3", rep):
        keys.extend(["wan-3-0__example_video", "alibaba/wan-3__example_video"])
    for key in keys:
        if _is_media_url(covers.get(key)):
            return str(covers[key]).strip()
    return ""


def _vitrine_catalog_items(*, fetch_covers: bool = False) -> list[dict]:
    """Public catalog cards from live INTEGRATED_MODELS (no assistants, no vendor prefix)."""
    try:
        from queue_runtime.health import is_channel_healthy
        healthy_fn = is_channel_healthy
    except Exception:  # noqa: BLE001
        healthy_fn = lambda _ch: True  # noqa: E731

    prices = _integration_prices()
    items: list[dict] = []
    for spec in INTEGRATED_MODELS.values():
        if spec.get("group") == "assistants" or spec.get("kind") in {"chat", "llm"}:
            continue
        if not _is_studio_visible(spec):
            continue
        provider = spec["provider"]
        if provider != "groq" and not healthy_fn(provider):
            continue
        mid = spec["id"]
        name = spec.get("name") or mid
        tags = _integration_vitrine_tags(spec)
        items.append({
            "id": mid,
            "title": name,
            "name": name,
            "vendor": "",
            "description": _integration_vitrine_description(spec),
            "image_url": _integration_image(spec, fetch_missing=fetch_covers),
            "tags": tags,
            "kind": spec.get("kind"),
            "group": spec.get("group") or spec.get("kind"),
            "provider": provider,
            "price": prices.get(mid) or "",
            "inputs": spec.get("inputs") or [],
            "outputs": spec.get("outputs") or [],
        })
    # Stable-ish order: image, video, audio, rest; then name
    kind_rank = {"image": 0, "video": 1, "audio": 2, "stt": 3}
    items.sort(key=lambda it: (kind_rank.get(it.get("kind") or "", 9), (it.get("name") or "").lower()))
    return items


@app.route("/api/catalog", methods=["GET"])
def api_catalog():
    """Homepage / catalog.html feed: live Generate models with previews."""
    load_env(BASE_DIR)
    fetch = request.args.get("fetch_covers") in {"1", "true", "yes"}
    items = _vitrine_catalog_items(fetch_covers=fetch)
    tag_names = sorted({t for it in items for t in (it.get("tags") or [])})
    rate = _integration_prices().get("__usd_rub_rate") or f"{_usd_rub_rate():.4f}".rstrip("0").rstrip(".")
    return jsonify({
        "items": items,
        "tags": [{"name": t} for t in tag_names],
        "total": len(items),
        "usd_rub_rate": rate,
    })


@app.route("/api/catalog/sync-covers", methods=["POST"])
def api_catalog_sync_covers():
    """Fill models_catalog/covers.json from Replicate (admin/ops).

    For video models downloads default_example.output (preview mp4) into
    /assets/models/examples/ and extracts a poster frame.
    """
    load_env(BASE_DIR)
    if not _replicate_token():
        return jsonify({"error": "not_configured"}), 503
    force = str((request.json or {}).get("force") or request.args.get("force") or "").lower() in {
        "1", "true", "yes",
    }
    updated = 0
    ingested = []
    for spec in INTEGRATED_MODELS.values():
        if spec.get("group") == "assistants":
            continue
        rep = (spec.get("replicate_model") or "").strip()
        if not rep:
            continue
        mid = spec["id"]
        covers = _load_covers()
        if not covers.get(mid):
            cover = _fetch_replicate_cover(rep)
            if cover:
                covers[mid] = cover
                covers[rep] = cover
                _save_covers(covers)
                updated += 1
        # Always try to pull preview video/image for examples
        outs = set(spec.get("outputs") or [])
        kind = (spec.get("kind") or "").lower()
        if kind == "video" or "video" in outs or force or not covers.get(f"{mid}__example"):
            got = _ingest_replicate_preview(mid, rep, force=force)
            if got:
                ingested.append({"id": mid, **got})
                updated += 1
    covers = _load_covers()
    return jsonify({
        "updated": updated,
        "ingested": ingested,
        "total_cached": len(covers),
    })


@app.route("/api/integrations", methods=["GET"])
def api_integrations():
    """List Generate models. Unhealthy channels are omitted (no UI, no requests)."""
    try:
        from queue_runtime.health import is_channel_healthy, read_all_health
        health = read_all_health()
        healthy_fn = is_channel_healthy
    except Exception:  # noqa: BLE001
        health = {}
        healthy_fn = lambda _ch: True  # noqa: E731

    prices = _integration_prices()
    items = []
    for spec in INTEGRATED_MODELS.values():
        if not _is_studio_visible(spec):
            continue
        provider = spec["provider"]
        if provider != "groq" and not healthy_fn(provider):
            continue
        mid = spec["id"]
        kind = (spec.get("kind") or "").lower()
        group = spec.get("group") or kind
        price = prices.get(mid) or ""
        price_full = prices.get(f"{mid}__full") or price
        # OmniRoute chat is always free for the user (fallback elsewhere)
        if mid == "assistant" or (provider == "omniroute" and kind in {"chat", "llm"}):
            price = price or "Бесплатно"
            price_full = price_full or price
        items.append({
            "id": mid,
            "name": _public_model_name(spec.get("name") or mid),
            "provider": provider,
            "kind": kind,
            "group": group,
            "replicate_model": spec.get("replicate_model"),
            "fal_model": spec.get("fal_model"),
            "inputs": spec["inputs"],
            "outputs": spec["outputs"],
            "notes": _public_notes(spec.get("notes")),
            "price": price,
            "price_full": price_full,
            **(_text_price_fields(mid) if kind in {"llm", "chat"} else {}),
            "image_url": _integration_image(spec, fetch_missing=False),
            "example_url": _integration_example(spec),
            "example_video_url": _integration_example_video(spec),
            "is_assistant": group == "assistants" or kind in {"chat", "llm"},
        })
    # Assistants first within text, then cheaper-ish by name
    items.sort(key=lambda it: (
        0 if it.get("is_assistant") else 1,
        {"image": 0, "video": 1, "audio": 2, "stt": 3, "llm": 4, "chat": 4}.get(it.get("kind") or "", 9),
        (it.get("name") or "").lower(),
    ))
    return jsonify({
        "items": items,
        "channels": health,
        "usd_rub_rate": prices.get("__usd_rub_rate") or f"{_usd_rub_rate():.4f}".rstrip("0").rstrip("."),
    })


_JOB_ID_RE = re.compile(r"^[a-f0-9]{16,64}$")


# Пока hold/estimate не учитывают duration/resolution/quality/size — в генерацию только «нейтральные» ключи.
_ASSIST_PARAMS_BILLING_NEUTRAL = frozenset({
    "aspect_ratio",
    "generate_audio",
    "generate_audio_switch",
    "style_type",
})


def _assist_params_for_generate(safe_params: dict | None) -> dict:
    if not safe_params:
        return {}
    if (os.getenv("ASSIST_BILLING_USE_PARAMS") or "").strip().lower() in {"1", "true", "yes"}:
        return dict(safe_params)
    return {k: v for k, v in safe_params.items() if k in _ASSIST_PARAMS_BILLING_NEUTRAL}


def _apply_assist_params(
    input_payload: dict,
    safe_params: dict | None,
    *,
    has_image: bool = False,
) -> dict:
    """Наложить белый список параметров ассистента на payload провайдера.

    Только ключи, уже присутствующие в payload (имя совпадает со схемой).
    Не трогаем match_input_image / adaptive, если есть картинка.
    """
    if not safe_params or not isinstance(input_payload, dict):
        return input_payload
    out = dict(input_payload)
    for key, value in safe_params.items():
        if key not in out:
            continue
        cur = out.get(key)
        if has_image and cur in {"match_input_image", "adaptive"}:
            continue
        out[key] = value
    return out


def _generate_job_fields(model_id: str, prompt: str, params: dict | None = None) -> dict | None:
    spec = INTEGRATED_MODELS.get(model_id)
    if not spec:
        return None
    payload = _build_provider_input(spec, prompt, None, None, None)
    safe: dict = {}
    if params:
        assist = app.config.get("ASSISTANT")
        card = getattr(getattr(assist, "d", None), "cards", {}).get(model_id) if assist else None
        if card is not None:
            from assistant.params import validate as _assist_params_validate
            safe = _assist_params_for_generate(_assist_params_validate(card, params))
    payload = _apply_assist_params(payload, safe, has_image=False)
    return {
        "model_id": model_id,
        "provider": spec["provider"],
        "kind": spec["kind"],
        "upstream_model": _provider_model_ref(spec),
        "replicate_model": spec.get("replicate_model"),
        "fal_model": spec.get("fal_model"),
        "input_payload": payload,
    }


@app.route("/api/generate/jobs/<job_id>", methods=["GET"])
def api_generate_job(job_id: str):
    if not _JOB_ID_RE.match(job_id or ""):
        return jsonify({"error": "not_found"}), 404
    try:
        from queue_runtime.jobs import generate_job_public, get_job

        job = get_job(job_id)
        if not job:
            return jsonify({"error": "not_found"}), 404
        owner = job.get("owner_id") or job.get("user_id")
        if owner and owner != session.get("user_id"):
            return jsonify({"error": "not_found"}), 404
        public = generate_job_public(job_id)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "queue_unavailable", "detail": str(exc)}), 503
    if not public:
        return jsonify({"error": "not_found"}), 404
    # Готово → работа в «Моих работах»: неопубликованная хранится 24 часа, в чате сразу предлагаем опубликовать
    if public.get("status") == "succeeded" and owner:
        try:
            gw = app.extensions.get("generation_works")
            work = gw["record"](job_id, public, owner, job.get("prompt") or "", job.get("params")) if gw else None
            if work is not None:
                public["work_id"] = work.id
                public["expires_at"] = gw["expires_iso"](work)
                public["published"] = work.status == "published"
        except Exception:  # noqa: BLE001
            db.session.rollback()
            app.logger.exception("record generation work failed")
    resp = jsonify(public)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _text_price_fields(model_id: str) -> dict:
    """Для текстовых моделей: понятная цена «≈ 0,19 ₽ за ответ» вместо «58 ₽/млн»."""
    rub = _text_answer_rub(model_id)
    if rub is None:
        return {}
    rub = math.ceil(rub * 100 - 1e-9) / 100 if rub > 0 else 0.0   # как спишет проверка баланса — вверх до копейки
    label = "бесплатно" if rub <= 0 else f"{_rub_label(rub)} за ответ"
    return {"price_answer_rub": round(rub, 4), "price_answer": label,
            "price_answer_hint": "ответ ~400 слов; длинные ответы и большой контекст стоят дороже"}


def _generate_require_auth() -> bool:
    """Генерация только для вошедших и только при достаточном балансе. Выключить можно лишь для тестов/локально."""
    return (os.getenv("GENERATE_REQUIRE_AUTH") or "1").strip().lower() not in {"0", "false", "no"}


TEXT_ANSWER_TOKENS_IN = 1500   # сообщение + немного истории диалога
TEXT_ANSWER_TOKENS_OUT = 600   # ответ средней длины (~400 слов)
_TOKEN_PRICE_RX = re.compile(r"(\d+(?:[.,]\d+)?)\s*₽\s*/\s*(млн|тыс\.?)\s*(входн|выходн)", re.I)


def _text_token_prices(model_id: str) -> tuple[float, float] | None:
    """₽ за 1 токен (вход, выход) из строки каталога «58 ₽ / млн входных токенов · 174 ₽ / млн выходных»."""
    full = _integration_prices().get(f"{model_id}__full") or _integration_prices().get(model_id) or ""
    if re.search(r"бесплат|free", full, re.I):
        return 0.0, 0.0
    found = {}
    for num, unit, side in _TOKEN_PRICE_RX.findall(full):
        per = float(num.replace(",", ".")) / (1_000_000 if unit.lower().startswith("млн") else 1_000)
        found["in" if side.lower().startswith("вход") else "out"] = per
    if not found:
        return None
    return found.get("in", found.get("out", 0.0)), found.get("out", found.get("in", 0.0))


def _text_answer_rub(model_id: str, prompt: str = "") -> float | None:
    """Примерная цена одного ответа текстовой модели в рублях."""
    prices = _text_token_prices(model_id)
    if prices is None:
        return None
    tin = max(TEXT_ANSWER_TOKENS_IN, len(prompt or "") // 3 + 200)
    return prices[0] * tin + prices[1] * TEXT_ANSWER_TOKENS_OUT


def _rub_label(rub: float) -> str:
    if rub <= 0:
        return "бесплатно"
    if rub < 0.01:
        rub = 0.01
    txt = f"{rub:.2f}" if rub < 10 else f"{rub:.0f}"
    return "≈ " + txt.rstrip("0").rstrip(".").replace(".", ",") + " ₽"


def _generate_cost_kop(model_id: str, params: dict | None = None, prompt: str = "") -> int | None:
    """Цена запуска в копейках по каталогу (_integration_prices) и длительности из params / по умолчанию.
    Это та же оценка, что показывает ассистент. None — цена неизвестна (не блокируем)."""
    spec = INTEGRATED_MODELS.get(model_id) or {}
    if (spec.get("kind") or "").lower() in {"llm", "chat"}:      # текст: цена за ответ, а не «за 1 млн токенов»
        rub = _text_answer_rub(model_id, prompt)
        return None if rub is None else int(math.ceil(rub * 100))
    try:
        from assistant.params import seconds as _sec, with_defaults as _wd
        from assistant.recommend import price_value as _pv
        from assistant.render import per_second as _ps, short_price as _sp

        price = _sp(_integration_prices().get(model_id))
        if not price:
            return None
        per = _ps(price)
        if per is not None:
            assist = app.config.get("ASSISTANT")
            card = assist.d.cards.get(model_id) if assist is not None else None
            sec = (_sec(card, _wd(card, dict(params or {}))) if card else None) or int((params or {}).get("duration") or 5)
            return int(math.ceil(per * sec * 100))
        v = _pv(price)
        return None if v is None else int(math.ceil(v * 100))
    except Exception:  # noqa: BLE001
        app.logger.exception("generate cost estimate failed")
        return None


def _generate_account() -> dict | None:
    """Вход и баланс текущего пользователя — для ассистента (вопросы перед запуском) и для проверки в /api/generate."""
    uid = session.get("user_id")
    if not uid:
        return {"authed": False, "available_kop": 0, "free_left": 0}
    models = app.extensions.get("product_models") or {}
    Balance = models.get("Balance")
    if Balance is None:
        return {"authed": True, "available_kop": 0, "free_left": 0}
    import billing as _billing

    bal = _billing.get_or_create_balance(db, Balance, uid)
    return {"authed": True, "available_kop": int(_billing.available_kop(bal)), "free_left": 0}


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(silent=True) or {}
    model_id = (data.get("model") or "assistant").strip()
    prompt = data.get("prompt") if isinstance(data.get("prompt"), str) else ""
    image_data_url = data.get("image") if isinstance(data.get("image"), str) else None
    audio_data_url = data.get("audio") if isinstance(data.get("audio"), str) else None
    video_data_url = data.get("video") if isinstance(data.get("video"), str) else None
    raw_params = data.get("params") if isinstance(data.get("params"), dict) else None

    spec = INTEGRATED_MODELS.get(model_id)
    if not spec:
        return jsonify({"error": "unknown_model", "detail": model_id}), 400

    safe_params: dict = {}
    assist = app.config.get("ASSISTANT")
    if assist is not None and raw_params:
        try:
            from assistant.params import validate as _assist_params_validate
            card = assist.d.cards.get(model_id)
            if card is not None:
                safe_params = _assist_params_for_generate(_assist_params_validate(card, raw_params))
        except Exception:
            safe_params = {}

    prompt = prompt.strip()
    if spec["kind"] == "stt":
        if not (audio_data_url or "").strip():
            return jsonify({"error": "bad_model", "detail": "audio required"}), 400
    elif model_id == "pasd-magnify":
        if not (image_data_url or "").strip():
            return jsonify({"error": "bad_model", "detail": "image required"}), 400
    elif model_id == "wan-3-0-i2v-fal":
        if not (image_data_url or "").strip():
            return jsonify({"error": "bad_model", "detail": "image required"}), 400
    elif model_id in {"grok-imagine-video-1-5", "gen4-turbo"} or model_id in _FAL_I2V_BACKUP_IDS:
        if not (image_data_url or "").strip():
            return jsonify({"error": "bad_model", "detail": "image required"}), 400
    elif model_id in {"seedance-2-5", "seedance-2-5-hf", "kling-v2-5-turbo-pro-hf", "kling-v3-0-hf", "veo-3-1-hf"}:
        if not prompt and not (image_data_url or "").strip():
            return jsonify({"error": "bad_model", "detail": "prompt or image required"}), 400
    elif model_id == "ltx-2-3-a2v-fal":
        if not (audio_data_url or "").strip():
            return jsonify({"error": "bad_model", "detail": "audio required"}), 400
        if not prompt and not (image_data_url or "").strip():
            return jsonify({"error": "bad_model", "detail": "prompt or image required"}), 400
    elif model_id == "minimax-music-01":
        if not (audio_data_url or "").strip():
            return jsonify({"error": "bad_model", "detail": "reference song required"}), 400
        if not prompt:
            return jsonify({"error": "bad_model", "detail": "lyrics required"}), 400
    elif model_id == "dreamactor-m2":
        if not (image_data_url or "").strip():
            return jsonify({"error": "bad_model", "detail": "image required"}), 400
        if not (video_data_url or "").strip():
            return jsonify({"error": "bad_model", "detail": "driving video required"}), 400
    elif not prompt:
        return jsonify({"error": "empty"}), 400

    # Legacy groq provider entries (if any) use /api/chat path
    if spec["provider"] == "groq":
        return jsonify({"error": "use_chat", "detail": "Use /api/chat for assistant"}), 400

    # Сначала вход, потом баланс — тот же порядок, что спрашивает ассистент в чате.
    if _generate_require_auth():
        acct = _generate_account()
        if not acct or not acct["authed"]:
            return jsonify({"error": "auth_required"}), 401
        need = _generate_cost_kop(model_id, safe_params, prompt)
        if need and acct["available_kop"] < need:
            return jsonify({"error": "insufficient_funds", "need_kop": need,
                            "available_kop": acct["available_kop"]}), 402

    provider = spec["provider"]
    if provider == "replicate":
        if not _replicate_token():
            return jsonify({"error": "not_configured", "detail": "REPLICATE_API_TOKEN missing"}), 503
    elif provider == "fal":
        if not _fal_key():
            return jsonify({"error": "not_configured", "detail": "FAL_KEY missing"}), 503
    elif provider == "omniroute":
        if not _omniroute_key():
            return jsonify({"error": "not_configured", "detail": "OMNIROUTE_API_KEY missing"}), 503
    elif provider == "higgsfield":
        if not _higgsfield_key():
            return jsonify({"error": "not_configured", "detail": "HF_KEY missing"}), 503
    else:
        return jsonify({"error": "unsupported_provider", "provider": provider}), 400

    try:
        from queue_runtime.health import is_channel_healthy
        if not is_channel_healthy(provider):
            return jsonify({
                "error": "channel_unavailable",
                "detail": f"{provider} is down; model hidden from routing",
                "provider": provider,
            }), 503
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "queue_unavailable", "detail": str(exc)}), 503

    # Скрепка: «upl_…» из /api/uploads → ссылка, которую скачает провайдер (S3 / сайт / data URL).
    # Файлы, которые модель не принимает (spec["inputs"]), отбрасываются.
    try:
        image_data_url, audio_data_url, video_data_url = resolve_generate_media(
            spec, image_data_url, audio_data_url, video_data_url
        )
    except UploadError as exc:
        return jsonify(exc.to_dict()), exc.status

    try:
        input_payload = _build_provider_input(
            spec, prompt, image_data_url, audio_data_url, video_data_url
        )
    except ValueError as exc:
        return jsonify({"error": "bad_model", "detail": str(exc)}), 400

    input_payload = _apply_assist_params(
        input_payload,
        safe_params,
        has_image=bool((image_data_url or "").strip()),
    )

    has_media_image = bool((image_data_url or "").strip())
    upstream_model = _provider_model_ref(spec, has_image=has_media_image)
    if not upstream_model and provider != "omniroute":
        return jsonify({"error": "bad_model", "detail": f"missing model ref for {provider}"}), 400

    use_queue = (os.getenv("GENERATE_USE_QUEUE") or "1").strip() not in {"0", "false", "no"}
    if use_queue:
        try:
            from queue_runtime.jobs import enqueue_inbound, wait_for_result
            job_id = enqueue_inbound({
                "model_id": model_id,
                "provider": provider,
                "kind": spec["kind"],
                "upstream_model": upstream_model,
                "replicate_model": spec.get("replicate_model"),
                "fal_model": spec.get("fal_model"),
                "higgsfield_model": upstream_model if provider == "higgsfield" else spec.get("higgsfield_model"),
                "input_payload": input_payload,
                "owner_id": session.get("user_id"),
                "prompt": prompt[:4000],          # для «Моих работ» и публикации на витрине
                "params": safe_params or None,
            })
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": "queue_unavailable", "detail": str(exc)}), 503

        # Default: async — return immediately so gunicorn workers stay free.
        # Opt-in sync wait for debugging: GENERATE_SYNC_WAIT=1
        sync_wait = (os.getenv("GENERATE_SYNC_WAIT") or "").strip().lower() in {"1", "true", "yes"}
        if not sync_wait:
            return jsonify({
                "job_id": job_id,
                "status": "queued",
                "model": model_id,
                "provider": provider,
                "kind": spec["kind"],
                "upstream_model": upstream_model,
                "poll_url": f"/api/generate/jobs/{job_id}",
                "poll_after_ms": 2000,
            }), 202

        try:
            result = wait_for_result(job_id)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": "queue_unavailable", "detail": str(exc), "job_id": job_id}), 503

        if not result.get("ok"):
            code = int(result.get("status") or 502)
            return jsonify({
                "error": result.get("error") or "upstream",
                "detail": result.get("detail"),
                "model": model_id,
                "provider": provider,
                "upstream_model": upstream_model,
                "job_id": result.get("job_id") or job_id,
            }), code

        # Worker already shaped the public payload.
        public = {k: v for k, v in result.items() if k not in {"ok", "status"}}
        return jsonify(public)

    # Legacy sync path (GENERATE_USE_QUEUE=0)
    wait = 300 if model_id in {
        "happy-horse-1-1-t2v-fal",
        "gemini-omni-flash-fal",
        "grok-imagine-video-1-5",
        "grok-imagine-video-1-5-i2v-fal",
        "seedance-2-0-t2v-fal",
        "kling-o3-standard-i2v-fal",
        "minimax-h3-ref-to-video-fal",
        "wan-3-0",
        "wan-3-0-t2v-fal",
        "wan-3-0-i2v-fal",
        "seedance-2-5",
        "seedance-2-5-hf",
        "kling-v2-5-turbo-pro-hf",
        "kling-v3-0-hf",
        "veo-3-1-hf",
        "ltx-2-3-t2v-fal",
        "ltx-2-3-t2v-fast-fal",
        "ltx-2-3-i2v-fal",
        "ltx-2-3-i2v-fast-fal",
        "ltx-2-3-a2v-fal",
        "pixverse-v6-t2v-fal",
        "pixverse-v6-i2v-fal",
        "minimax-music-2-5",
        "dreamactor-m2",
    } else (
        180 if spec["kind"] in {"video"} or model_id in {
            "elevenlabs-music",
            "lyria-2",
            "minimax-music-01",
            "ace-step",
            "flux-music",
        } else 120
    )

    if provider == "fal":
        result = _run_fal_prediction(upstream_model, input_payload, wait_seconds=wait)
    elif provider == "higgsfield":
        result = _run_higgsfield_prediction(upstream_model, input_payload, wait_seconds=wait)
    elif provider == "omniroute":
        result = _run_omniroute_prediction(upstream_model, input_payload, wait_seconds=wait)
    else:
        result = _run_replicate_prediction(upstream_model, input_payload, wait_seconds=wait)

    if not result.get("ok"):
        code = int(result.get("status") or 502)
        return jsonify({
            "error": result.get("error") or "upstream",
            "detail": result.get("detail"),
            "model": model_id,
            "provider": provider,
            "upstream_model": upstream_model,
            "replicate_model": spec.get("replicate_model"),
            "fal_model": spec.get("fal_model"),
            "higgsfield_model": spec.get("higgsfield_model"),
        }), code

    prediction = result["prediction"]
    kind = spec["kind"]
    if provider == "fal":
        outputs = _fal_extract_outputs(prediction, kind)
    elif provider == "higgsfield":
        outputs = _higgsfield_extract_outputs(prediction, kind)
    else:
        outputs = _flatten_output(prediction.get("output"))

    common = {
        "model": model_id,
        "provider": provider,
        "upstream_model": upstream_model,
        "replicate_model": spec.get("replicate_model"),
        "fal_model": spec.get("fal_model"),
        "higgsfield_model": spec.get("higgsfield_model"),
        "prediction_id": prediction.get("id") or prediction.get("request_id"),
    }

    if kind in {"llm", "stt"}:
        if kind == "stt" and isinstance(prediction.get("output"), dict):
            out = prediction["output"]
            reply = (out.get("text") or "").strip()
            lang = out.get("language_code")
            if reply and lang:
                reply = f"{reply}\n\n— язык: {lang}"
            elif not reply:
                reply = str(out)
        else:
            reply = "\n".join(outputs).strip() or str(prediction.get("output") or prediction.get("text") or "")
        return jsonify({"kind": "text", "reply": reply, **common})

    media_urls = [u for u in outputs if isinstance(u, str) and u.startswith("http")]
    if kind == "image":
        return jsonify({
            "kind": "image",
            "urls": media_urls,
            "reply": "Готово." if media_urls else "Модель завершилась без URL изображения.",
            **common,
        })

    if kind == "video":
        return jsonify({
            "kind": "video",
            "urls": media_urls,
            "reply": "Видео готово." if media_urls else "Модель завершилась без URL видео.",
            **common,
        })

    if kind == "audio":
        return jsonify({
            "kind": "audio",
            "urls": media_urls,
            "reply": "Аудио готово." if media_urls else "Модель завершилась без URL аудио.",
            **common,
        })

    return jsonify({"error": "unsupported_kind", "kind": kind}), 500


@app.route("/api/pricing", methods=["GET"])
def api_pricing():
    region = (request.args.get("region") or os.getenv("REGION") or "RU").upper()
    items = list_pricing_public(region=region)
    rate, stale = get_usd_rub_rate()
    return jsonify({"items": items, "usd_rub_rate": rate, "rate_stale_penalty": stale, "region": region})



@app.route("/api/assistant", methods=["POST"])
def api_assistant():
    """Step 3 entry: rules-first recommendations; LLM path stub when unclear."""
    data = request.get_json(silent=True) or {}
    messages = data.get("messages") if isinstance(data.get("messages"), list) else []
    # last 6 turns, total <= 2000 chars
    clipped = []
    total = 0
    for item in messages[-6:][::-1]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        room = 2000 - total
        if room <= 0:
            break
        content = content[:room]
        clipped.append({"role": role, "content": content})
        total += len(content)
    clipped.reverse()
    last_user = next((m["content"] for m in reversed(clipped) if m["role"] == "user"), "")
    has_image = bool(data.get("has_image"))
    free_left = int(data.get("free_left") or 1)
    region = (os.getenv("REGION") or "RU").upper()
    result = assistant_recommend(last_user, has_image=has_image, free_left=free_left, region=region)
    # prices already from pricing; ensure server-side
    app.logger.info(
        "assistant used_llm=%s tokens_in_est=%s",
        result.get("used_llm"),
        min(1500, total + 400),
    )
    return jsonify(result)


register_auth(app, db, User)
app.config["INTEGRATED_MODELS"] = INTEGRATED_MODELS
app.config["GENERATE_JOB_FIELDS"] = _generate_job_fields
register_product(app, db, User)
apply_rate_limits(app)

# ── Ассистент чата студии: POST /api/assistant/chat (не трогает /api/chat и /api/assistant) ──
from assistant.flask_adapter import build_from_env as _assist_build, metrics_hook as _assist_metrics, register_assistant


def _assist_redis():
    try:
        from queue_runtime import get_redis
        r = get_redis()
        r.ping()
        return r
    except Exception:
        return None  # без Redis — память в процессе (сессия ассистента не переживёт рестарт)


def _assist_channel_healthy(channel: str) -> bool:
    from queue_runtime.health import is_channel_healthy
    return is_channel_healthy(channel)


def _assist_on_event(ev: dict) -> None:
    app.logger.info(
        "assistant intent=%s llm=%s provider=%s tokens=%s degraded=%s ms=%s",
        ev["intent"], ev["llm_used"], ev["provider"], ev["tokens"], ev["degraded"], ev["ms"],
    )
    try:
        metric = (app.extensions.get("product_models") or {}).get("AssistantMetric")
        if metric is not None:
            _assist_metrics(db, metric)(ev)
    except Exception:
        app.logger.exception("assistant metrics failed")


load_env(BASE_DIR)
os.environ.setdefault("ASSIST_VITRINA_URL", "/explore")
ASSISTANT = _assist_build(
    models=INTEGRATED_MODELS,
    price_fn=lambda mid: _integration_prices().get(mid),
    channel_healthy=_assist_channel_healthy,
    redis_client=_assist_redis(),
    on_event=_assist_on_event,
    cost_fn=_generate_cost_kop,
    visible_fn=lambda mid: _is_studio_visible(INTEGRATED_MODELS.get(mid) or {}),   # этапы проекта: только модели студии
)
register_assistant(
    app, ASSISTANT,
    user_id_fn=lambda: session.get("user_id"),
    # перед «Сгенерировать» ассистент спрашивает: 1) войти, 2) пополнить — по данным сервера, не фронта
    account_fn=lambda _uid: _generate_account() if _generate_require_auth() else None,
)

# ── Скрепка: POST/GET/DELETE /api/uploads (файлы для генерации; записи — в Redis, иначе в памяти) ──
register_uploads(app, redis_fn=_assist_redis)

# ── История переписки студии: /api/chats (текст и имена файлов — в аккаунте; сами файлы живут 24 ч) ──
register_chat_history(app, db)

# ── Генерации → «Мои работы»; неопубликованные удаляются через 24 ч (flask purge-unpublished-works) ──
register_generation_works(app, db)


@app.after_request
def _no_cache_html(resp):
    ct = (resp.headers.get("Content-Type") or "").lower()
    if "text/html" in ct:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
    return resp

@app.route("/")
def index_page():
    ensure_csrf_token()
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/app")
def app_page():
    ensure_csrf_token()
    return send_from_directory(BASE_DIR, "app.html")


@app.route("/auth")
def auth_page():
    ensure_csrf_token()
    return send_from_directory(BASE_DIR, "auth.html")


@app.route("/media/<path:filename>")
def media_files(filename):
    return send_from_directory(os.path.join(BASE_DIR, "media"), filename)


@app.route("/explore")
def explore_page():
    ensure_csrf_token()
    return send_from_directory(BASE_DIR, "explore.html")


@app.route("/account")
def account_page():
    ensure_csrf_token()
    return send_from_directory(BASE_DIR, "account.html")


@app.route("/settings")
def settings_page():
    ensure_csrf_token()
    return redirect("/account#settings")


@app.route("/balance")
def balance_page():
    ensure_csrf_token()
    return redirect("/account#balance")


@app.route("/admin")
def admin_page():
    ensure_csrf_token()
    return send_from_directory(BASE_DIR, "admin.html")


@app.route("/w/<int:work_id>")
def work_page(work_id):
    ensure_csrf_token()
    return send_from_directory(BASE_DIR, "work.html")


@app.route("/@<handle>")
def creator_page(handle):
    ensure_csrf_token()
    return send_from_directory(BASE_DIR, "creator.html")


@app.route("/creator")
def creator_cabinet_page():
    ensure_csrf_token()
    return send_from_directory(BASE_DIR, "creator.html")

@app.route("/<path:filename>")
def public_files(filename):
    if filename.startswith("api/"):
        return jsonify({"error": "not found"}), 404
    ensure_csrf_token()
    return send_from_directory(BASE_DIR, filename)

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed()
    debug = (os.getenv("FLASK_DEBUG") or "").strip().lower() in {"1", "true", "yes"}
    # Production: gunicorn -c deploy/gunicorn.conf.py wsgi:app
    host = (os.getenv("HOST") or "0.0.0.0").strip() or "0.0.0.0"
    app.run(host=host, port=int(os.getenv("PORT") or 8000), debug=debug)
