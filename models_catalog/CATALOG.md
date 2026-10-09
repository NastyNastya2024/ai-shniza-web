# Live models catalog (with prices)

Source of truth: `INTEGRATED_MODELS` in `server.py`. Prices fetched **2026-09-09 16:53 UTC**.

Units differ by model (per image / per second / per token / per megapixel). Compare only within the same unit and similar resolution.

## Replicate vs fal — overlapping families

| Family | Replicate | fal | Note |
|---|---|---|---|
| **Wan 3.0** | `$0.025/s` output video (`alibaba/wan-3`) | `480p $0.05/s` · `720p $0.10/s` · `1080p $0.20/s` | Replicate cheaper on published per-second; fal tiers by resolution + native audio options |
| **Seedance 2.0** | `$0.10/s` (`bytedance/seedance-2.0`) | `720p $0.3034/s` · `1080p $0.682/s` | Replicate much cheaper on listed rate; fal page also mentions token formula |
| **Seedance 2.5** | `$0.1028/s` (Replicate only) | — | No fal twin in runtime yet |
| **Seedream 5** | — | Lite `$0.035/image` · Pro `$0.0675–0.135/image` | fal-only in our stack |

## Full table

| Name | Channel | Upstream | Category | In | Out | Price |
|---|---|---|---|---|---|---|
| Ассистент · OmniRoute | omniroute |  | llm | text | text | free-tier / pool (OmniRoute) |
| Ассистент · DeepSeek V3.1 | replicate | deepseek-ai/deepseek-v3.1 | llm | text | text | $0.672 per million input tokens (or around 1,488,095 tokens for $1) · $2.016 per million output tokens (or around 496,031 tokens for $1) |
| Ассистент · DeepSeek V3 | replicate | deepseek-ai/deepseek-v3 | llm | text | text | $1.45 per million output tokens (or around 689,655 tokens for $1) · $1.45 per million input tokens (or around 689,655 tokens for $1) |
| Ассистент · Claude Sonnet 5 | replicate | anthropic/claude-sonnet-5 | llm | text | text | $2 per million input tokens (or 500,000 tokens for $1) · $0.01 per thousand output tokens (or 100,000 tokens for $1) |
| Ассистент · Claude Haiku 4.5 | replicate | anthropic/claude-4.5-haiku | llm | text | text | $5 per million output tokens (or 200,000 tokens for $1) · $1 per million input tokens (or 1,000,000 tokens for $1) |
| Ассистент · Claude Opus 4.7 | replicate | anthropic/claude-opus-4.7 | llm | text, image | text | $5 per million input tokens (or 200,000 tokens for $1) · $0.025 per thousand output tokens (or 40,000 tokens for $1) |
| Ассистент · Gemini 3.5 Flash | replicate | google/gemini-3.5-flash | llm | text | text | $1.50 per million input tokens (or around 666,666 tokens for $1) · $9 per million output tokens (or around 111,111 tokens for $1) |
| Ассистент · Gemini 3.1 Pro | replicate | google/gemini-3.1-pro | llm | text, image | text | $2 per million input tokens (or 500,000 tokens for $1) · $0.012 per thousand output tokens (or around 83,333 tokens for $1) |
| Ассистент · GPT-5.4 | replicate | openai/gpt-5.4 | llm | text, image | text | $2.50 per million input tokens (or 400,000 tokens for $1) · $0.015 per thousand output tokens (or around 66,666 tokens for $1) |
| GPT-5.6 Sol | replicate | openai/gpt-5.6-sol | llm | text, image | text | $2 per million input tokens (or 500,000 tokens for $1) · $0.01 per thousand output tokens (or 100,000 tokens for $1) |
| Runway Gen-4.5 | replicate | runwayml/gen-4.5 | video | text, image | video | $0.12 per second of output video (or around 83 seconds for $10) |
| Gen-4 Turbo | replicate | runwayml/gen4-turbo | video | image, text | video | $0.05/s |
| Veo 3.1 | replicate | google/veo-3.1 | video | text, image | video | $0.20/s without audio · $0.40/s with audio |
| Veo 3.1 Fast | replicate | google/veo-3.1-fast | video | text, image | video | $0.10/s without audio · $0.15/s with audio |
| Veo 3.1 Lite | replicate | google/veo-3.1-lite | video | text, image | video | $0.05 per second of output video (or 20 seconds for $1) |
| Sora 2 | replicate | openai/sora-2 | video | text, image | video | $0.10 per second of output video (or 10 seconds for $1) |
| Hailuo 2.3 Fast | replicate | minimax/hailuo-2.3-fast | video | image, text | video | $0.19 per output video (or around 52 videos for $10) |
| Hailuo 02 | replicate | minimax/hailuo-02 | video | text, image | video | $0.10/vid 512p6s · $0.15 512p10s · $0.27 768p6s · $0.45 768p10s · $0.48 1080p6s |
| DreamActor M2.0 | replicate | bytedance/dreamactor-m2.0 | video | image, video | video | $0.05 per second of output video (or 20 seconds for $1) |
| Nano Banana Pro | replicate | google/nano-banana-pro | image | text, image | image | $0.15/img · fal backup fal-ai/nano-banana-pro(/edit) |
| Nano Banana 2 | replicate | google/nano-banana-2 | image | text, image | image | $0.067/img 1K · $0.101 2K · $0.151 4K |
| Nano Banana 2 Lite | replicate | google/nano-banana-2-lite | image | text, image | image | $0.034 per output image (or around 29 images for $1) |
| Gemini 3.1 Flash TTS | replicate | google/gemini-3.1-flash-tts | audio | text | audio | $2 per million input tokens (or 500,000 tokens for $1) · $0.04 per thousand output tokens (or 25,000 tokens for $1) |
| ElevenLabs v3 | replicate | elevenlabs/v3 | audio | text | audio | $0.10 per thousand input characters (or 10,000 characters for $1) |
| ElevenLabs Music | replicate | elevenlabs/music | audio | text | audio | $0.0083/s |
| Stable Audio 2.5 | replicate | stability-ai/stable-audio-2.5 | audio | text | audio | $0.20 / file |
| Lyria 2 | replicate | google/lyria-2 | audio | text | audio | $2 per thousand seconds of output audio (or 500 seconds for $1) |
| MiniMax Music-01 | replicate | minimax/music-01 | audio | text, audio | audio | $0.035 per output audio file (or around 28 files for $1) |
| ACE-Step | replicate | lucataco/ace-step | audio | text | audio | ~$0.022 / run |
| Flux Music | replicate | zsxkib/flux-music | audio | text | audio | $0.000975 per second; typical ~$0.0022 |
| MiniMax Music 2.5 | replicate | minimax/music-2.5 | audio | text | audio | $0.15 per output audio file (or around 66 files for $10) |
| ElevenLabs Scribe v2 | replicate | elevenlabs/scribe-v2 | text | audio | text | $3.667 per thousand outputs (or around 272 outputs for $1) |
| Flux 2 Pro | replicate | black-forest-labs/flux-2-pro | image | text, image | image | $0.015 per run (or around 66 runs for $1) · $0.015 per input image megapixel (or around 66 megapixels for $1) · $0.015 per output image megapixel (or around 66 megapixels for $1) |
| Flux 1.1 Pro | replicate | black-forest-labs/flux-1.1-pro | image | text, image | image | $0.04 per output image (or 25 images for $1) |
| Flux Kontext Pro | replicate | black-forest-labs/flux-kontext-pro | image | text, image | image | $0.04 per output image (or 25 images for $1) |
| Grok Imagine Image 2 | replicate | xai/grok-imagine-image-2 | image | text, image | image | $0.04 per output image (or 25 images for $1) |
| PASD Magnify | replicate | lucataco/pasd-magnify | image | image, text | image | $0.000975 per second; typical ~$0.0081 |
| Ideogram v3 Turbo | replicate | ideogram-ai/ideogram-v3-turbo | image | text, image | image | $0.03 per output image (or around 33 images for $1) |
| Gen-4 Image | replicate | runwayml/gen4-image | image | text, image | image | $0.05 per output image (or 20 images for $1) |
| Z-Image Turbo | replicate | prunaai/z-image-turbo | image | text | image | $2.50 per thousand output image megapixels (or 400 megapixels for $1) |
| HiDream L1 Fast | replicate | prunaai/hidream-l1-fast | image | text | image | $5 per thousand output images (or 200 images for $1) |
| GPT Image 2 | replicate | openai/gpt-image-2 | image | text, image | image | $0.012/image low · $0.047 medium · $0.128 high |
| GPT Image 2.5 Flare | replicate | openai/gpt-image-2.5-flare | image | text, image | image | $0.012/image low · $0.047 medium · $0.128 high · $0.25 xhigh · $0.50 max |
| GPT Image 2.5 Sunburst | replicate | openai/gpt-image-2.5-sunburst | image | text, image | image | $0.012/image low · $0.047 medium · $0.128 high · $0.25 xhigh · $0.50 max |
| Wan 3.0 | replicate | alibaba/wan-3 | video | text, image | video | $0.05/s 480p · $0.10/s 720p · $0.20/s 1080p |
| Grok Imagine Video 1.5 | replicate | xai/grok-imagine-video-1.5 | video | image, text | video | $0.08/s output video (synced audio · 480p/720p · 1–15s) |
| Seedance 2.5 | replicate | bytedance/seedance-2.5 | video | text, image | video | $0.1028/s output video (synced audio · 480p/720p · up to 30s) |
| Seedance 2.0 | replicate | bytedance/seedance-2.0 | video | text | video | $0.10 per second of output video (or 10 seconds for $1) |
| Happy Horse 1.1 T2V | fal | alibaba/happy-horse/v1.1/text-to-video | video | text | video | 720p $0.14/s · 1080p $0.18/s |
| Gemini Omni Flash | fal | google/gemini-omni-flash | video | text | video | $21.875 / 1M tokens · ~$0.125/s at 720p |
| Soul Cinema | higgsfield | higgsfield-ai/soul/cinema | image | text, image | image | Higgsfield credits · cinematic t2i/i2i |
| Grok Imagine Video 1.5 I2V | fal | xai/grok-imagine-video/v1.5/image-to-video | video | image, text | video | 480p $0.08/s · 720p $0.14/s · 1080p $0.25/s · +$0.01/ref image |
| Seedance 2.0 T2V | fal | bytedance/seedance-2.0/text-to-video | video | text | video | 720p $0.3034/s · 1080p $0.682/s (also token formula on page) |
| Kling 2.5 Turbo Pro | replicate | kwaivgi/kling-v2.5-turbo-pro | video | text, image | video | $0.07/s |
| Kling O3 Standard I2V | fal | fal-ai/kling-video/o3/standard/image-to-video | video | image, text | video | $0.084/s audio off · $0.112/s audio on |
| MiniMax H3 Ref→Video | fal | minimax/h3/reference-to-video | video | text, image | video | 480p $0.05/s · 768p $0.06/s · 2K $0.13/s · 4K $0.16/s · +$0.08 after 5 ref images |
| Wan 3.0 T2V | fal | alibaba/wan-3.0/text-to-video | video | text | video | 480p $0.05/s · 720p $0.10/s · 1080p $0.20/s |
| Wan 3.0 I2V | fal | alibaba/wan-3.0/image-to-video | video | image, text | video | 480p $0.05/s · 720p $0.10/s · 1080p $0.20/s |
| LTX 2.3 T2V | fal | fal-ai/ltx-2.3/text-to-video | video | text | video | 1080p $0.08/s · 1440p $0.16/s · 2160p $0.32/s |
| LTX 2.3 T2V Fast | fal | fal-ai/ltx-2.3/text-to-video/fast | video | text | video | 1080p $0.06/s · 1440p $0.12/s · 2160p $0.24/s |
| LTX 2.3 I2V | fal | fal-ai/ltx-2.3/image-to-video | video | image, text | video | 1080p $0.08/s · 1440p $0.16/s · 2160p $0.32/s |
| LTX 2.3 I2V Fast | fal | fal-ai/ltx-2.3/image-to-video/fast | video | image, text | video | 1080p $0.06/s · 1440p $0.12/s · 2160p $0.24/s |
| LTX 2.3 A2V | fal | fal-ai/ltx-2.3/audio-to-video | video | audio, text, image | video | $0.10/s |
| PixVerse V6 | replicate | pixverse/pixverse-v6 | video | text, image | video | $0.05/s 360p · $0.07 540p · $0.09 720p · $0.18 1080p |
| P-Video | replicate | prunaai/p-video | video | text, image, audio | video | $0.005/s 720p draft · $0.02 720p · $0.01 1080p draft · $0.04 1080p |
| PixVerse V6 T2V | fal | fal-ai/pixverse/v6/text-to-video | video | text | video | 360p $0.025–0.035/s · 540p $0.035–0.045/s · 720p $0.045–0.060/s · 1080p $0.090–0.115/s (no/with audio) |
| PixVerse V6 I2V | fal | fal-ai/pixverse/v6/image-to-video | video | image, text | video | 360p $0.025–0.035/s · 540p $0.035–0.045/s · 720p $0.045–0.060/s · 1080p $0.090–0.115/s (no/with audio) |
| Seedream 5.0 Pro | replicate | bytedance/seedream-5-pro | image | text, image | image | $0.045/image 1K · $0.09/image 2K |
| Seedream 5.0 Lite Edit | fal | fal-ai/bytedance/seedream/v5/lite/edit | image | image, text | image | $0.035 / image |
| Seedream 5.0 Lite T2I | fal | fal-ai/bytedance/seedream/v5/lite/text-to-image | image | text | image | $0.035 / image |
| Seedream 5.0 Pro T2I | fal | bytedance/seedream/v5/pro/text-to-image | image | text | image | ≤1536² $0.0675/image · ≤2048² $0.135/image (tentative) |
| Seedream 5.0 Pro Edit | fal | bytedance/seedream/v5/pro/edit | image | image, text | image | ≤1536² $0.0675 + $0.0045×extra inputs · ≤2048² $0.135 + $0.0045×extra (tentative) |
| OmniRoute · auto/chat | omniroute | auto/chat | llm | text | text | free-tier / pool (OmniRoute) |
| OmniRoute · auto/coding:free | omniroute | auto/coding:free | llm | text | text | free-tier / pool (OmniRoute) |

Refresh: `python3 models_catalog/build_priced_catalog.py` (uses `fal_prices.json` for fal; scrapes replicate.com for Replicate).

Architecture / assistant persona: [`docs/architecture/assistant-prompt.md`](../docs/architecture/assistant-prompt.md), [`docs/architecture/ARCHITECTURE.md`](../docs/architecture/ARCHITECTURE.md) §9.
