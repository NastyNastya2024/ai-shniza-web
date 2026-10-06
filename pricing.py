"""Pricing catalog and RUB price helpers (step 4 core; used by step 1 UI)."""
from __future__ import annotations

import math
import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Optional

import requests

# fallback USD/RUB if CBR unavailable
_FALLBACK_USD_RUB = 90.0
_cbr_cache: dict[str, Any] = {"rate": None, "fetched_at": 0.0, "stale_penalty": False}


@dataclass
class PricingRow:
    model_key: str
    channel: str
    upstream_id: str
    category: str  # video|image|music|voice|text|tool
    unit: str  # per_second|per_item|per_1k_chars|per_tokens|per_run_approx
    cost_usd: float = 0.0
    cost_in_per_1m: float = 0.0
    cost_out_per_1m: float = 0.0
    markup: float = 2.0
    region: str = "RU"  # RU|INTL
    max_duration_sec: Optional[int] = None
    fixed_resolution: Optional[str] = "720p"
    has_audio: bool = False
    is_free: bool = False
    enabled: bool = True
    needs_verify: bool = False
    description_ru: str = ""
    quality_score: int = 50  # for sort
    family: Optional[str] = None  # e.g. seedance
    version_label: Optional[str] = None


def _clamp_markup(unit: str, markup: float) -> float:
    default = 3.0 if unit == "per_run_approx" else 2.0
    m = markup if markup and markup > 0 else default
    if m < 1.5:
        raise ValueError("markup_min_1_5")
    return m


def get_usd_rub_rate(force: bool = False) -> tuple[float, bool]:
    """Return (rate, stale_penalty_applied). Cache ~24h; if >3 days old apply +10%."""
    now = time.time()
    cached = _cbr_cache.get("rate")
    fetched = float(_cbr_cache.get("fetched_at") or 0)
    if cached and not force and now - fetched < 86400:
        return float(cached), bool(_cbr_cache.get("stale_penalty"))

    rate = None
    try:
        resp = requests.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=8)
        resp.raise_for_status()
        rate = float(resp.json()["Valute"]["USD"]["Value"])
        _cbr_cache["fetched_at"] = now
        _cbr_cache["stale_penalty"] = False
        _cbr_cache["rate"] = rate
    except Exception:
        if cached:
            age = now - fetched
            penalty = age > 3 * 86400
            if penalty:
                return float(cached) * 1.10, True
            return float(cached), False
        rate = _FALLBACK_USD_RUB
        _cbr_cache["rate"] = rate
        _cbr_cache["fetched_at"] = now
        _cbr_cache["stale_penalty"] = True
    return float(rate), bool(_cbr_cache.get("stale_penalty"))


def price_rub_media(cost_usd: float, markup: float, unit: str = "per_second") -> int:
    m = _clamp_markup(unit, markup)
    rate, stale = get_usd_rub_rate()
    if stale:
        rate *= 1.0  # already applied in getter when using cache; keep explicit path clear
    raw = cost_usd * rate * 1.30 * m
    return max(1, int(math.ceil(raw - 1e-9)))


def price_rub_text_per_msg_approx(cost_in: float, cost_out: float, markup: float = 2.0, tokens_in: int = 800, tokens_out: int = 300) -> float:
    m = _clamp_markup("per_tokens", markup)
    rate, _ = get_usd_rub_rate()
    usd = (tokens_in / 1_000_000) * cost_in + (tokens_out / 1_000_000) * cost_out
    rub = usd * rate * 1.30 * m
    return max(0.10, round(math.ceil(rub * 100 - 1e-9) / 100, 2))


# Seed catalog (step 4). needs_verify → enabled False until owner confirms.
PRICING_SEED: list[PricingRow] = [
    PricingRow("veo-free/seedance", "omniroute", "veoaifree-web/seedance", "video", "per_item", 0, is_free=True, has_audio=False, description_ru="Бесплатное видео Seedance (очередь)", quality_score=40, family="free-video"),
    PricingRow("veo-free/veo", "omniroute", "veoaifree-web/veo", "video", "per_item", 0, is_free=True, description_ru="Бесплатное видео VEO 3.1 (очередь)", quality_score=45, family="free-video"),
    PricingRow("bytedance/seedance-1-pro-fast", "replicate", "bytedance/seedance-1-pro-fast", "video", "per_second", 0.025, needs_verify=True, enabled=False, description_ru="Seedance 1 Pro Fast", family="seedance", version_label="1 Pro Fast", quality_score=55),
    PricingRow("bytedance/seedance-1-lite", "replicate", "bytedance/seedance-1-lite", "video", "per_second", 0.036, needs_verify=True, enabled=False, description_ru="Seedance 1 Lite", family="seedance", version_label="1 Lite", quality_score=50),
    PricingRow("bytedance/seedance-2.0-mini", "replicate", "bytedance/seedance-2.0-mini", "video", "per_second", 0.05, needs_verify=True, enabled=False, has_audio=True, description_ru="Seedance 2.0 Mini со звуком", family="seedance", version_label="2.0 Mini", quality_score=70),
    PricingRow("bytedance/seedance-1.5-pro", "replicate", "bytedance/seedance-1.5-pro", "video", "per_second", 0.05, needs_verify=True, enabled=False, description_ru="Seedance 1.5 Pro", family="seedance", version_label="1.5 Pro", quality_score=65),
    PricingRow("bytedance/seedance-2.0-fast", "replicate", "bytedance/seedance-2.0-fast", "video", "per_second", 0.06, needs_verify=True, enabled=False, has_audio=True, description_ru="Seedance 2.0 Fast со звуком", family="seedance", version_label="2.0 Fast", quality_score=75),
    PricingRow("bytedance/seedance-1-pro", "replicate", "bytedance/seedance-1-pro", "video", "per_second", 0.06, needs_verify=True, enabled=False, description_ru="Seedance 1 Pro", family="seedance", version_label="1 Pro", quality_score=68),
    PricingRow("bytedance/seedance-2.0", "replicate", "bytedance/seedance-2.0", "video", "per_second", 0.10, has_audio=True, description_ru="Seedance 2.0 со звуком", family="seedance", version_label="2.0", quality_score=85, enabled=True),
    PricingRow("bytedance/seedance-2.5", "replicate", "bytedance/seedance-2.5", "video", "per_second", 0.1028, has_audio=True, max_duration_sec=30, description_ru="Seedance 2.5 — видео со звуком", family="seedance", version_label="2.5", quality_score=90, enabled=True),
    PricingRow("alibaba/wan-3", "replicate", "alibaba/wan-3", "video", "per_second", 0.10, description_ru="Wan 3.0 — видео 720p", quality_score=88, enabled=True),
    PricingRow("xai/grok-imagine-video-1.5", "replicate", "xai/grok-imagine-video-1.5", "video", "per_second", 0.08, has_audio=True, max_duration_sec=15, description_ru="Grok Imagine Video 1.5 — image→video со звуком", quality_score=86, enabled=True),
    PricingRow("google/veo-3.1", "replicate", "google/veo-3.1", "video", "per_second", 0.20, has_audio=True, max_duration_sec=8, description_ru="Veo 3.1 — видео со звуком", quality_score=95, enabled=True),
    PricingRow("google/veo-3.1-fast", "replicate", "google/veo-3.1-fast", "video", "per_second", 0.10, has_audio=True, max_duration_sec=8, description_ru="Veo 3.1 Fast — быстрое видео со звуком", quality_score=90, enabled=True),
    PricingRow("google/veo-3.1-lite", "fal", "fal-ai/veo3.1/lite", "video", "per_second", 0.05, region="INTL", description_ru="Veo 3.1 Lite", quality_score=80),
    PricingRow("openai/sora-2", "replicate", "openai/sora-2", "video", "per_second", 0.10, region="INTL", description_ru="Sora 2", quality_score=92),
    PricingRow("runwayml/gen4-turbo", "replicate", "runwayml/gen4-turbo", "video", "per_second", 0.05, max_duration_sec=10, description_ru="Gen-4 Turbo — быстрый i2v 720p", quality_score=86, enabled=True),
    PricingRow("kwaivgi/kling-v2.5-turbo-pro", "replicate", "kwaivgi/kling-v2.5-turbo-pro", "video", "per_second", 0.07, max_duration_sec=10, description_ru="Kling 2.5 Turbo Pro — cinematic t2v/i2v", quality_score=89, enabled=True),
    PricingRow("pixverse/pixverse-v6", "replicate", "pixverse/pixverse-v6", "video", "per_second", 0.05, has_audio=True, max_duration_sec=15, description_ru="PixVerse V6 — видео со звуком", quality_score=92, enabled=True),
    PricingRow("prunaai/p-video", "replicate", "prunaai/p-video", "video", "per_second", 0.005, has_audio=True, max_duration_sec=20, description_ru="P-Video — быстрое видео + draft", quality_score=84, enabled=True),
    PricingRow("fal-ai/kling-o3-i2v", "fal", "fal-ai/kling-video/o3/standard/image-to-video", "video", "per_second", 0.084, has_audio=False, description_ru="Kling O3 image-to-video", quality_score=82, enabled=True),
    PricingRow("minimax/hailuo-02", "replicate", "minimax/hailuo-02", "video", "per_item", 0.10, max_duration_sec=10, description_ru="Hailuo 02 — t2v/i2v 512p–1080p", quality_score=87, enabled=True),
    PricingRow("minimax/hailuo-2.3-fast", "replicate", "minimax/hailuo-2.3-fast", "video", "per_item", 0.19, description_ru="Hailuo 2.3 Fast", quality_score=78, enabled=True),
    PricingRow("bytedance/sdxl-lightning-4step", "replicate", "bytedance/sdxl-lightning-4step", "image", "per_run_approx", 0.0014, markup=3.0, description_ru="SDXL Lightning — быстро и дёшево", quality_score=55, enabled=True),
    PricingRow("prunaai/z-image-turbo", "replicate", "prunaai/z-image-turbo", "image", "per_item", 0.0025, description_ru="Z-Image Turbo", quality_score=60, enabled=True),
    PricingRow("black-forest-labs/flux-2-pro", "replicate", "black-forest-labs/flux-2-pro", "image", "per_item", 0.03, description_ru="Flux 2 Pro", quality_score=88, enabled=True),
    PricingRow("ideogram-ai/ideogram-v3-turbo", "replicate", "ideogram-ai/ideogram-v3-turbo", "image", "per_item", 0.03, description_ru="Ideogram v3 Turbo — быстрый t2i + текст", quality_score=85, enabled=True),
    PricingRow("openai/gpt-image-2", "replicate", "openai/gpt-image-2", "image", "per_item", 0.012, description_ru="GPT Image 2 — low/medium/high", quality_score=93, enabled=True),
    PricingRow("openai/gpt-image-2.5-flare", "replicate", "openai/gpt-image-2.5-flare", "image", "per_item", 0.012, description_ru="GPT Image 2.5 Flare — быстрый t2i/edit", quality_score=91, enabled=True),
    PricingRow("openai/gpt-image-2.5-sunburst", "replicate", "openai/gpt-image-2.5-sunburst", "image", "per_item", 0.012, description_ru="GPT Image 2.5 Sunburst — точный t2i/edit", quality_score=94, enabled=True),
    PricingRow("fal/seedream-5-lite", "fal", "fal-ai/bytedance/seedream/v5/lite/text-to-image", "image", "per_item", 0.035, description_ru="Seedream 5.0 Lite", quality_score=75, enabled=True),
    PricingRow("bytedance/seedream-5-pro", "replicate", "bytedance/seedream-5-pro", "image", "per_item", 0.045, description_ru="Seedream 5.0 Pro — 1K/2K", quality_score=90, enabled=True),
    PricingRow("fal/seedream-5-pro", "fal", "fal-ai/bytedance/seedream/v5/text-to-image", "image", "per_item", 0.0675, description_ru="Seedream 5.0 Pro", quality_score=86, enabled=True),
    PricingRow("google/nano-banana-2", "replicate", "google/nano-banana-2", "image", "per_item", 0.067, description_ru="Nano Banana 2 — t2i/edit 1K/2K/4K", quality_score=88, enabled=True),
    PricingRow("google/nano-banana-pro", "replicate", "google/nano-banana-pro", "image", "per_item", 0.15, region="INTL", description_ru="Nano Banana Pro", quality_score=84),
    PricingRow("851-labs/background-remover", "replicate", "851-labs/background-remover", "tool", "per_run_approx", 0.0004, markup=3.0, description_ru="Удаление фона", quality_score=50, enabled=True),
    PricingRow("tencentarc/gfpgan", "replicate", "tencentarc/gfpgan", "tool", "per_run_approx", 0.0046, markup=3.0, description_ru="Реставрация лиц GFPGAN", quality_score=55, enabled=True),
    PricingRow("philz1337x/clarity-upscaler", "replicate", "philz1337x/clarity-upscaler", "tool", "per_run_approx", 0.019, markup=3.0, description_ru="Апскейл Clarity", quality_score=60, enabled=True),
    PricingRow("lucataco/ace-step", "replicate", "lucataco/ace-step", "music", "per_run_approx", 0.022, markup=3.0, description_ru="ACE-Step — музыка из тегов", quality_score=78, enabled=True),
    PricingRow("minimax/music-2.5", "replicate", "minimax/music-2.5", "music", "per_item", 0.15, description_ru="MiniMax Music 2.5", quality_score=80, enabled=True),
    PricingRow("elevenlabs/music", "replicate", "elevenlabs/music", "music", "per_second", 0.0083, max_duration_sec=300, description_ru="ElevenLabs Music — text→music", quality_score=88, enabled=True),
    PricingRow("elevenlabs/v3", "replicate", "elevenlabs/v3", "voice", "per_1k_chars", 0.10, description_ru="ElevenLabs озвучка v3", quality_score=88, enabled=True),
    PricingRow("jaaari/kokoro-82m", "replicate", "jaaari/kokoro-82m", "voice", "per_run_approx", 0.00022, markup=3.0, description_ru="Kokoro TTS", quality_score=60, enabled=True),
    PricingRow("openai/whisper", "replicate", "openai/whisper", "voice", "per_run_approx", 0.0011, markup=3.0, description_ru="Whisper — речь в текст", quality_score=70, enabled=True),
    PricingRow("zsxkib/mmaudio", "replicate", "zsxkib/mmaudio", "music", "per_run_approx", 0.0054, markup=3.0, enabled=False, needs_verify=True, description_ru="MMAudio (лицензия — проверить)", quality_score=55),
    PricingRow("omniroute/chat-free", "omniroute", "auto/coding:free", "text", "per_tokens", is_free=True, description_ru="Бесплатный чат", quality_score=40, enabled=True),
    PricingRow("deepseek-ai/deepseek-v3.1", "replicate", "deepseek-ai/deepseek-v3.1", "text", "per_tokens", cost_in_per_1m=0.672, cost_out_per_1m=2.016, description_ru="DeepSeek V3.1", quality_score=75, enabled=True),
    PricingRow("google/gemini-3.5-flash", "replicate", "google/gemini-3.5-flash", "text", "per_tokens", cost_in_per_1m=1.5, cost_out_per_1m=9.0, region="INTL", description_ru="Gemini 3.5 Flash", quality_score=78),
    PricingRow("google/gemini-3.1-pro", "replicate", "google/gemini-3.1-pro", "text", "per_tokens", cost_in_per_1m=2.0, cost_out_per_1m=12.0, region="INTL", description_ru="Gemini 3.1 Pro", quality_score=92),
    PricingRow("openai/gpt-5.4", "replicate", "openai/gpt-5.4", "text", "per_tokens", cost_in_per_1m=2.5, cost_out_per_1m=15.0, region="INTL", description_ru="GPT-5.4", quality_score=90),
    PricingRow("anthropic/claude-4.5-haiku", "replicate", "anthropic/claude-4.5-haiku", "text", "per_tokens", cost_in_per_1m=1.0, cost_out_per_1m=5.0, region="INTL", description_ru="Claude 4.5 Haiku", quality_score=80),
    PricingRow("anthropic/claude-sonnet-5", "replicate", "anthropic/claude-sonnet-5", "text", "per_tokens", cost_in_per_1m=2.0, cost_out_per_1m=10.0, region="INTL", description_ru="Claude Sonnet 5", quality_score=88),
    PricingRow("anthropic/claude-opus-4.7", "replicate", "anthropic/claude-opus-4.7", "text", "per_tokens", cost_in_per_1m=5.0, cost_out_per_1m=25.0, region="INTL", description_ru="Claude Opus 4.7", quality_score=95),
]


def list_pricing_public(region: Optional[str] = None) -> list[dict]:
    region = (region or os.getenv("REGION") or "RU").upper()
    rate, stale = get_usd_rub_rate()
    out: list[dict] = []
    for row in PRICING_SEED:
        if not row.enabled:
            continue
        if region == "RU" and row.region == "INTL":
            continue
        item = asdict(row)
        item["usd_rub_rate"] = rate
        item["rate_stale_penalty"] = stale
        if row.is_free:
            item["price_rub"] = 0
            item["price_label"] = "Бесплатно"
            item["example_rub_5s"] = 0
        elif row.unit == "per_second":
            per_sec = price_rub_media(row.cost_usd, row.markup, row.unit)
            item["price_rub"] = per_sec
            item["example_rub_5s"] = per_sec * 5
            item["price_label"] = f"{per_sec} ₽/сек · ролик 5 с — {per_sec * 5} ₽"
        elif row.unit in {"per_item", "per_run_approx"}:
            p = price_rub_media(row.cost_usd, row.markup, row.unit)
            item["price_rub"] = p
            item["price_label"] = f"{p} ₽ за картинку" if row.category == "image" else f"{p} ₽ за запуск"
        elif row.unit == "per_1k_chars":
            p = price_rub_media(row.cost_usd, row.markup, "per_item")
            item["price_rub"] = p
            item["price_label"] = f"{p} ₽ / 1000 символов"
        elif row.unit == "per_tokens":
            approx = price_rub_text_per_msg_approx(row.cost_in_per_1m, row.cost_out_per_1m, row.markup)
            item["price_rub"] = approx
            item["price_label"] = f"~{approx} ₽ за сообщение"
        else:
            item["price_rub"] = 0
            item["price_label"] = "—"
        # hide channel from public UI payload? keep for server; UI must not show
        item.pop("channel", None)
        item.pop("upstream_id", None)
        out.append(item)
    return out
