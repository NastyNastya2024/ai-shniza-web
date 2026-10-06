# Fal backup models report (2026-10-06)

Sources: `https://fal.ai/models/<fal_model>/llms.txt` (fetched 2026-10-06).

## Confirmed and added

| Replicate id | Fal backup id(s) | fal_model |
|---|---|---|
| wan-3-0 | wan-3-0-t2v-fal / wan-3-0-i2v-fal | alibaba/wan-3.0/… |
| grok-imagine-video-1-5 | grok-imagine-video-1-5-i2v-fal (i only) | xai/grok-imagine-video/v1.5/image-to-video |
| seedance-2-5 | seedance-2-5-t2v-fal / seedance-2-5-ref2v-fal | bytedance/seedance-2.5/… |
| veo-3-1 | veo-3-1-t2v-fal / veo-3-1-i2v-fal | fal-ai/veo3.1/… |
| veo-3-1-fast | veo-3-1-fast-t2v-fal / veo-3-1-fast-i2v-fal | fal-ai/veo3.1/fast/… |
| kling-v2-5-turbo-pro | kling-v2-5-turbo-pro-t2v-fal / kling-v2-5-i2v-fal | fal-ai/kling-video/v2.5-turbo/pro/… |
| pixverse-v6 | pixverse-v6-t2v-fal / pixverse-v6-i2v-fal | fal-ai/pixverse/v6/… |
| hailuo-02 | hailuo-02-t2v-fal / hailuo-02-i2v-fal | fal-ai/minimax/hailuo-02/standard/… (768p) |
| seedream-5-pro | seedream-5-pro-t2i-fal / seedream-5-pro-edit-fal | bytedance/seedream/v5/pro/… |
| gpt-image-2 | gpt-image-2-fal / gpt-image-2-edit-fal | openai/gpt-image-2(/edit) |
| gpt-image-2-5-flare | gpt-image-2-5-flare-fal | openai/gpt-image-2.5/flare/text-to-image |
| gpt-image-2-5-sunburst | gpt-image-2-5-sunburst-fal | openai/gpt-image-2.5/sunburst/text-to-image |
| nano-banana-2 | nano-banana-2-fal / nano-banana-2-edit-fal | fal-ai/nano-banana-2(/edit) |
| ideogram-v3-turbo | ideogram-v3-turbo-fal | fal-ai/ideogram/v3 (TURBO via rendering_speed) |
| ace-step | ace-step-fal | fal-ai/ace-step |
| elevenlabs-music | elevenlabs-music-fal | fal-ai/elevenlabs/music |
| stable-audio-2-5 | stable-audio-2-5-fal | fal-ai/stable-audio-25/text-to-audio |

## No fal backup (by design)

| Replicate id | Reason |
|---|---|
| p-video | no matching fal endpoint in catalog |
| gen4-turbo | no matching fal endpoint in catalog |

## Routing

`FAILOVER_MAP` + `_failover_target()` in `server.py`. Automatic switch on channel failure is **B2** (not in this commit).

## Smoke

`python scripts/fal_backup_smoke.py` (plan) · `python scripts/fal_backup_smoke.py --yes` (paid).
