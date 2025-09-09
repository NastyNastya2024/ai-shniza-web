from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Tuple

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "app.db")

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
CORS(app)

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
    if os.path.exists(DB_PATH) and Model.query.count() > 0:
        return
    db.drop_all()
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
        ("ideogram", "ideogram", ["image-generation"], "Ideogram — image generation model", IMAGE_GEN_IMAGE),
        ("google", "imagen-4", ["image-generation"], "Imagen-4 — image generation model", IMAGE_GEN_IMAGE),
        ("black-forest-labs", "flux-kontext", ["image-generation"], "FluxKontext — image generation model", IMAGE_GEN_IMAGE),
        ("kling", "kling-v2.1", ["video-generation", "text-to-video"], "Kling v2.1 — video generation", VIDEO_GEN_IMAGE),
        ("minimax", "minimax-video", ["video-generation"], "Minimax Video — video generation", VIDEO_GEN_IMAGE),
        ("bytedance", "seedance", ["video-generation", "text-to-video"], "Seedance — video generation", VIDEO_GEN_IMAGE),
        ("google", "veo3-8s", ["video-generation"], "Veo3 (8 секунд) — video generation", VIDEO_GEN_IMAGE),
        ("minimax", "minimax-music", ["music-generation", "audio"], "Minimax Music — music generation", MUSIC_GEN_IMAGE),
        ("meta", "musicgen", ["music-generation", "audio"], "MusicGen — music generation", MUSIC_GEN_IMAGE),
        ("chatterbox", "chatterbox", ["music-generation", "audio"], "Chatterbox — music generation", MUSIC_GEN_IMAGE),
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
        "title": f"{m.vendor}/{m.name}",
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

@app.route("/")
def ok():
    return jsonify({"ok": True})

if __name__ == "__main__":
    with app.app_context():
        seed()
    app.run(host="0.0.0.0", port=5000, debug=True)
