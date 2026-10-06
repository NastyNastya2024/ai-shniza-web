from __future__ import annotations

import os
import re
import json
import time
from dataclasses import dataclass
from typing import List, Tuple

import requests
from flask import Flask, jsonify, redirect, request, send_from_directory
from flask_sqlalchemy import SQLAlchemy

from auth import load_env, register_auth
from security import configure_security, apply_rate_limits, ensure_csrf_token
from pricing import list_pricing_public, price_rub_media, get_usd_rub_rate
from assistant_rules import recommend as assistant_recommend
from product_routes import register_product

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
Ты — «Заботливый Навигатор + Экономический Адвокат» маркетплейса генеративных моделей «{AI}-шница».
Ты лучший друг и наставник: помогаешь не переплачивать и получать вау-результат даже на бюджетных моделях.
Отвечай на языке пользователя. Будь добр, эмоционален (уместны эмодзи вроде 🫶), искренне радуйся успехам.

Жёсткое правило каталога:
- Рекомендуй ТОЛЬКО модели из блока «КАТАЛОГ LIVE-МОДЕЛЕЙ» в конце системного сообщения.
- Не называй Midjourney, ChatGPT/Sora «снаружи», Ideogram вне списка и любые другие сети, которых нет в каталоге.
- Если подходящей модели нет — честно скажи об этом и предложи ближайшие из каталога.

Формат ответа (обязательно, нарушать нельзя):
- Каждый смысловой блок с НОВОЙ СТРОКИ. Запрещено писать весь ответ одной строкой/абзацем.
- Используй Markdown с пустыми строками между блоками.
- Шаблон для рекомендаций моделей (копируй структуру 1 в 1):

Кратко, о чём речь (1–2 предложения).

### 1. Название модели · канал
- **Исходники:** …
- **Цена:** …
- **Качество:** …

### 2. Название модели · канал
- **Исходники:** …
- **Цена:** …
- **Качество:** …

## Вердикт
Что выбрать и почему.

## Готовый промпт
текст промпта

## Параметры запуска
- …

## Следующий шаг
какую модель нажать в боковом меню Generate

Суперсилы:
1) Защита бюджета — баланс цена/качество; подчёркивай экономию через доработку промпта.
2) Промпт-доработка — готовый промпт именно под выбранную модель из каталога.
3) Параметры под задачу — всегда помогай с настройками запуска.

Алгоритм:
1) Уточни (если не сказано): задача, формат, бюджет на генерат, тон.
2) Предложи 2–3 модели ТОЛЬКО из каталога с абзацами «исходники / цена / качество».
3) Дай улучшенный промпт и параметры.
4) В конце — какой пункт выбрать в UI.

Оркестрация с UI (ассистент → модель → ассистент):
- Ты всегда первый: советы, выбор модели, доработка промпта.
- Если в контексте указана выбранная медиа-модель и пользователь ЯВНО просит сгенерировать
  (не «помоги выбрать / посоветуй / сравни»), добавь В КОНЦЕ ответа отдельной строкой ровно:
  GENERATE_NOW: <финальный промпт для этой модели>
- Для советов, уточнений и выбора модели строку GENERATE_NOW НЕ добавляй.
- Не объясняй этот маркер пользователю — UI его спрячет и запустит модель.

Этика (мягко, но чётко):
Запрещено: суицид, насилие над людьми/животными, жестокость, буллинг, экстремизм, унижение.
Опасный запрос → отказ как друг и перевод на созидательную задачу.
Подавленность → 8-800-2000-122 и https://www.iasp.info/suicidalthoughts/ , затем созидание.
Не выдумывай вредоносные инструкции. Не обещай невозможное.
""".strip()


def _catalog_for_prompt(max_chars: int = 9000) -> str:
    """Compact live catalog for the navigator system prompt."""
    prices = _integration_prices()
    lines = [
        "КАТАЛОГ LIVE-МОДЕЛЕЙ (рекомендуй только отсюда; поля: id | name | channel | in | out | price):"
    ]
    for spec in INTEGRATED_MODELS.values():
        # Не предлагаем «выбрать ассистента» — чат всегда Omni→резерв
        if spec.get("group") == "assistants" or spec.get("kind") in {"chat", "llm"}:
            continue
        mid = spec["id"]
        price = prices.get(mid) or "н/д"
        inputs = ",".join(spec.get("inputs") or [])
        outputs = ",".join(spec.get("outputs") or [])
        lines.append(
            f"- {mid} | {spec.get('name') or mid} | {spec.get('provider')} | "
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
    session = _chat_session()
    last_detail = ""
    last_status = 502

    def _chat_ok(reply: str, used_model: str, channel: str):
        visible, generate_prompt = _split_generate_now(reply)
        payload = {"reply": visible or reply, "model": used_model, "channel": channel}
        if generate_prompt:
            payload["generate_prompt"] = generate_prompt
            mid = (data.get("selected_model_id") or "").strip()
            if mid:
                payload["generate_model"] = mid
        return jsonify(payload)

    # Primary: OmniRoute free-capable routes
    omni_key = _omniroute_key()
    if omni_key:
        preferred = (os.getenv("OMNIROUTE_CHAT_MODEL") or "auto/coding:free").strip()
        omni_models = []
        for candidate in (preferred, "auto/coding:free", "auto/best-free", "auto/chat"):
            if candidate and candidate not in omni_models:
                omni_models.append(candidate)
        for model in omni_models:
            payload = {
                "model": model,
                "messages": chat_messages,
                "temperature": 0.35,
                "max_tokens": 1600,
                "stream": False,
            }
            try:
                resp = session.post(
                    f"{_omniroute_base()}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {omni_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=90,
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

    # Fallback: DeepSeek on Replicate if OmniRoute unavailable / rate-limited
    if _replicate_token():
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
            wait_seconds=120,
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

    if not omni_key and not _replicate_token():
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
        "name": "Ассистент · OmniRoute",
        "provider": "omniroute",
        "kind": "chat",
        "group": "assistants",
        "replicate_model": None,
        "inputs": ["text"],
        "outputs": ["text"],
    },
    "deepseek-v3-1": {
        "id": "deepseek-v3-1",
        "name": "Ассистент · DeepSeek V3.1",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "deepseek-ai/deepseek-v3.1",
        "inputs": ["text"],
        "outputs": ["text"],
    },
    "deepseek-v3": {
        "id": "deepseek-v3",
        "name": "Ассистент · DeepSeek V3",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "deepseek-ai/deepseek-v3",
        "inputs": ["text"],
        "outputs": ["text"],
    },
    "claude-sonnet-5": {
        "id": "claude-sonnet-5",
        "name": "Ассистент · Claude Sonnet 5",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "anthropic/claude-sonnet-5",
        "inputs": ["text"],
        "outputs": ["text"],
    },
    "claude-4-5-haiku": {
        "id": "claude-4-5-haiku",
        "name": "Ассистент · Claude Haiku 4.5",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "anthropic/claude-4.5-haiku",
        "inputs": ["text"],
        "outputs": ["text"],
    },
    "claude-opus-4-7": {
        "id": "claude-opus-4-7",
        "name": "Ассистент · Claude Opus 4.7",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "anthropic/claude-opus-4.7",
        "inputs": ["text", "image"],
        "outputs": ["text"],
    },
    "gemini-3-5-flash": {
        "id": "gemini-3-5-flash",
        "name": "Ассистент · Gemini 3.5 Flash",
        "provider": "replicate",
        "kind": "llm",
        "group": "assistants",
        "replicate_model": "google/gemini-3.5-flash",
        "inputs": ["text"],
        "outputs": ["text"],
    },
    "gpt-5-4": {
        "id": "gpt-5-4",
        "name": "Ассистент · GPT-5.4",
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
    "veo-3-1-lite": {
        "id": "veo-3-1-lite",
        "name": "Veo 3.1 Lite",
        "provider": "replicate",
        "kind": "video",
        "group": "generative",
        "replicate_model": "google/veo-3.1-lite",
        "inputs": ["text", "image"],
        "outputs": ["video"],
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
        "notes": "tags→music; instrumental default",
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
    "gpt-image-2-5-flare": {
        "id": "gpt-image-2-5-flare",
        "name": "GPT Image 2.5 Flare",
        "provider": "replicate",
        "kind": "image",
        "group": "image",
        "replicate_model": "openai/gpt-image-2.5-flare",
        "inputs": ["text", "image"],
        "outputs": ["image"],
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
        "notes": "30% off this week",
    },
    "seedance-2-5": {
        "id": "seedance-2-5",
        "name": "Seedance 2.5",
        "provider": "replicate",
        "kind": "video",
        "group": "video",
        "replicate_model": "bytedance/seedance-2.5",
        "inputs": ["text"],
        "outputs": ["video"],
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
        "notes": "image required",
    },
    # --- OmniRoute channel (OpenAI-compatible /v1) ---
    "omni-auto": {
        "id": "omni-auto",
        "name": "OmniRoute · auto/chat",
        "provider": "omniroute",
        "kind": "llm",
        "group": "assistants",
        "omniroute_model": "auto/chat",
        "inputs": ["text"],
        "outputs": ["text"],
        "notes": "via OmniRoute gateway",
    },
    "omni-auto-free": {
        "id": "omni-auto-free",
        "name": "OmniRoute · auto/coding:free",
        "provider": "omniroute",
        "kind": "llm",
        "group": "assistants",
        "omniroute_model": "auto/coding:free",
        "inputs": ["text"],
        "outputs": ["text"],
        "notes": "free-tier routing via OmniRoute",
    },
}


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


def _provider_model_ref(spec: dict) -> str | None:
    if spec.get("provider") == "fal":
        return spec.get("fal_model")
    if spec.get("provider") == "omniroute":
        return spec.get("omniroute_model")
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

    if model_id in {"gpt-image-2-5-flare", "gpt-image-2-5-sunburst"}:
        payload = {
            "prompt": prompt,
            "quality": "auto",
            "output_format": "webp",
            "number_of_images": 1,
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
            "duration": 5,
            "enable_prompt_expansion": True,
        }
        if image:
            payload["image"] = image
        return payload

    if model_id == "seedance-2-5":
        return {"prompt": prompt}

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
    if spec.get("group") == "assistants" and spec.get("kind") in {"llm", "chat"}:
        prompt = _with_assistant_persona(prompt)
    if spec.get("provider") == "omniroute":
        return {"prompt": prompt}
    return _build_replicate_input(spec, prompt, image_data_url, audio_data_url, video_data_url)


def _run_replicate_prediction(replicate_model: str, input_payload: dict, wait_seconds: int = 120) -> dict:
    token = _replicate_token()
    if not token:
        return {"error": "not_configured", "status": 503}

    # Replicate Prefer: wait must be 1..60; longer jobs continue via polling below.
    prefer_wait = max(1, min(int(wait_seconds or 60), 60))
    owner, name = replicate_model.split("/", 1)
    url = f"https://api.replicate.com/v1/models/{owner}/{name}/predictions"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": f"wait={prefer_wait}",
    }
    try:
        resp = requests.post(url, headers=headers, json={"input": input_payload}, timeout=prefer_wait + 30)
    except requests.RequestException as exc:
        return {"error": "upstream", "detail": str(exc.__class__.__name__), "status": 502}

    try:
        body = resp.json()
    except ValueError:
        return {"error": "bad_response", "detail": resp.text[:300], "status": 502}

    if resp.status_code >= 400:
        detail = body.get("detail") or body.get("error") or resp.text[:300]
        return {"error": "upstream", "detail": detail, "status": resp.status_code, "body": body}

    status = body.get("status")
    if status == "succeeded":
        return {"ok": True, "prediction": body}
    if status in {"failed", "canceled"}:
        return {
            "error": "failed",
            "detail": body.get("error") or status,
            "status": 502,
            "prediction": body,
        }

    # Prefer:wait may return early — poll a few times
    get_url = body.get("urls", {}).get("get") or f"https://api.replicate.com/v1/predictions/{body.get('id')}"
    for _ in range(40):
        time.sleep(2)
        try:
            poll = requests.get(get_url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
            pdata = poll.json()
        except (requests.RequestException, ValueError):
            continue
        st = pdata.get("status")
        if st == "succeeded":
            return {"ok": True, "prediction": pdata}
        if st in {"failed", "canceled"}:
            return {
                "error": "failed",
                "detail": pdata.get("error") or st,
                "status": 502,
                "prediction": pdata,
            }
    return {"error": "timeout", "detail": "prediction still running", "status": 504, "prediction": body}


def _run_fal_prediction(fal_model: str, input_payload: dict, wait_seconds: int = 120) -> dict:
    """Submit to fal.ai queue and poll until COMPLETED (or timeout)."""
    key = _fal_key()
    if not key:
        return {"error": "not_configured", "status": 503}

    headers = {
        "Authorization": f"Key {key}",
        "Content-Type": "application/json",
    }
    submit_url = f"https://queue.fal.run/{fal_model.lstrip('/')}"
    try:
        resp = requests.post(submit_url, headers=headers, json=input_payload, timeout=60)
    except requests.RequestException as exc:
        return {"error": "upstream", "detail": str(exc.__class__.__name__), "status": 502}

    try:
        body = resp.json()
    except ValueError:
        return {"error": "bad_response", "detail": resp.text[:300], "status": 502}

    if resp.status_code >= 400:
        detail = body.get("detail") or body.get("error") or resp.text[:300]
        return {"error": "upstream", "detail": detail, "status": resp.status_code, "body": body}

    status_url = body.get("status_url")
    response_url = body.get("response_url")
    request_id = body.get("request_id")
    if not status_url or not response_url:
        # Some endpoints may return the result immediately
        if any(k in body for k in ("images", "image", "video", "audio", "output", "text")):
            return {"ok": True, "prediction": body}
        return {"error": "bad_response", "detail": "missing fal queue urls", "status": 502, "body": body}

    deadline = time.time() + max(wait_seconds, 30)
    while time.time() < deadline:
        try:
            poll = requests.get(f"{status_url}?logs=0", headers=headers, timeout=30)
            pdata = poll.json()
        except (requests.RequestException, ValueError):
            time.sleep(2)
            continue

        status = pdata.get("status")
        if status == "COMPLETED":
            try:
                result = requests.get(response_url, headers=headers, timeout=60)
                rbody = result.json()
            except (requests.RequestException, ValueError) as exc:
                return {"error": "upstream", "detail": str(exc.__class__.__name__), "status": 502}
            if result.status_code >= 400:
                return {
                    "error": "upstream",
                    "detail": rbody.get("detail") or rbody.get("error") or result.text[:300],
                    "status": result.status_code,
                    "body": rbody,
                }
            if isinstance(rbody, dict):
                rbody.setdefault("request_id", request_id)
            return {"ok": True, "prediction": rbody}
        if status in {"FAILED", "CANCELLED", "CANCELED"}:
            return {
                "error": "failed",
                "detail": pdata.get("error") or status,
                "status": 502,
                "prediction": pdata,
            }
        time.sleep(2)

    return {"error": "timeout", "detail": "fal request still running", "status": 504, "prediction": body}


def _run_omniroute_prediction(omni_model: str, input_payload: dict, wait_seconds: int = 120) -> dict:
    """Call OmniRoute OpenAI-compatible /v1/chat/completions."""
    key = _omniroute_key()
    if not key:
        return {"error": "not_configured", "detail": "OMNIROUTE_API_KEY missing", "status": 503}
    base = _omniroute_base()
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
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=wait_seconds + 30)
    except requests.RequestException as exc:
        return {"error": "upstream", "detail": str(exc.__class__.__name__), "status": 502}

    try:
        data = resp.json()
    except ValueError:
        return {"error": "bad_response", "detail": resp.text[:300], "status": 502}

    if resp.status_code >= 400:
        detail = data.get("error") or data.get("detail") or resp.text[:300]
        if isinstance(detail, dict):
            detail = detail.get("message") or detail
        return {"error": "upstream", "detail": detail, "status": resp.status_code, "body": data}

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


@app.route("/api/channels/health", methods=["GET"])
def api_channels_health():
    try:
        from queue_runtime.health import read_all_health
        return jsonify({"channels": read_all_health()})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "health_unavailable", "detail": str(exc)}), 503


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
        return cover if isinstance(cover, str) and cover.startswith("http") else None
    except Exception:
        return None


def _integration_image(spec: dict, *, fetch_missing: bool = False) -> str:
    """Preview image: cached Replicate cover, else kind-based real stock photo."""
    covers = _load_covers()
    mid = spec["id"]
    if isinstance(covers.get(mid), str) and covers[mid].startswith("http"):
        return covers[mid]
    rep = (spec.get("replicate_model") or "").strip()
    if rep and isinstance(covers.get(rep), str) and covers[rep].startswith("http"):
        return covers[rep]

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
    """Fill models_catalog/covers.json from Replicate (admin/ops)."""
    load_env(BASE_DIR)
    if not _replicate_token():
        return jsonify({"error": "not_configured"}), 503
    updated = 0
    covers = _load_covers()
    for spec in INTEGRATED_MODELS.values():
        if spec.get("group") == "assistants":
            continue
        rep = (spec.get("replicate_model") or "").strip()
        if not rep:
            continue
        mid = spec["id"]
        if covers.get(mid):
            continue
        cover = _fetch_replicate_cover(rep)
        if cover:
            covers[mid] = cover
            covers[rep] = cover
            updated += 1
    _save_covers(covers)
    return jsonify({"updated": updated, "total_cached": len(covers)})


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
        provider = spec["provider"]
        # Ассистенты не в UI: чат всегда Omni → DeepSeek fallback в /api/chat
        if spec.get("group") == "assistants" or spec.get("kind") in {"chat", "llm"}:
            continue
        if provider != "groq" and not healthy_fn(provider):
            continue
        mid = spec["id"]
        items.append({
            "id": mid,
            "name": spec["name"],
            "provider": provider,
            "kind": spec["kind"],
            "group": spec.get("group") or spec["kind"],
            "replicate_model": spec.get("replicate_model"),
            "fal_model": spec.get("fal_model"),
            "inputs": spec["inputs"],
            "outputs": spec["outputs"],
            "notes": spec.get("notes"),
            "price": prices.get(mid) or "",
            "price_full": prices.get(f"{mid}__full") or prices.get(mid) or "",
            "image_url": _integration_image(spec, fetch_missing=False),
        })
    return jsonify({
        "items": items,
        "channels": health,
        "usd_rub_rate": prices.get("__usd_rub_rate") or f"{_usd_rub_rate():.4f}".rstrip("0").rstrip("."),
    })


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(silent=True) or {}
    model_id = (data.get("model") or "assistant").strip()
    prompt = data.get("prompt") if isinstance(data.get("prompt"), str) else ""
    image_data_url = data.get("image") if isinstance(data.get("image"), str) else None
    audio_data_url = data.get("audio") if isinstance(data.get("audio"), str) else None
    video_data_url = data.get("video") if isinstance(data.get("video"), str) else None

    spec = INTEGRATED_MODELS.get(model_id)
    if not spec:
        return jsonify({"error": "unknown_model", "detail": model_id}), 400

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

    try:
        input_payload = _build_provider_input(
            spec, prompt, image_data_url, audio_data_url, video_data_url
        )
    except ValueError as exc:
        return jsonify({"error": "bad_model", "detail": str(exc)}), 400

    upstream_model = _provider_model_ref(spec)
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
                "input_payload": input_payload,
            })
            result = wait_for_result(job_id)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": "queue_unavailable", "detail": str(exc)}), 503

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
        "grok-imagine-video-1-5-i2v-fal",
        "seedance-2-0-t2v-fal",
        "kling-o3-standard-i2v-fal",
        "minimax-h3-ref-to-video-fal",
        "wan-3-0-t2v-fal",
        "wan-3-0-i2v-fal",
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
        }), code

    prediction = result["prediction"]
    kind = spec["kind"]
    if provider == "fal":
        outputs = _fal_extract_outputs(prediction, kind)
    else:
        outputs = _flatten_output(prediction.get("output"))

    common = {
        "model": model_id,
        "provider": provider,
        "upstream_model": upstream_model,
        "replicate_model": spec.get("replicate_model"),
        "fal_model": spec.get("fal_model"),
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
register_product(app, db, User)
apply_rate_limits(app)

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
