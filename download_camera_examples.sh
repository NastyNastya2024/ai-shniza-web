#!/usr/bin/env bash
# Примеры движений камеры для этапа «Видео» помощника: 46 роликов с aicameramovements.com → assets/camera/
# Запуск из корня репозитория:  bash download_camera_examples.sh
set -euo pipefail
BASE="https://aicameramovements.com/previews/hq"
DEST="assets/camera"
mkdir -p "$DEST"
ok=0; fail=0
for f in 01-static-shot-hq.mp4 02-pan-right-hq.mp4 2b-pan-left-hq.mp4 03-whip-pan-right-hq.mp4 3b-whip-pan-left-hq.mp4 04-tilt-up-hq.mp4 4b-tilt-down-hq.mp4 05-slow-zoom-in-hq.mp4 5b-slow-zoom-out-hq.mp4 06-fast-zoom-in-v2-hq.mp4 06b-fast-zoom-out-v2-hq.mp4 07a-crash-zoom-in-v2-hq.mp4 07b-crash-zoom-out-v2-hq.mp4 08-dolly-in-hq.mp4 09-dolly-out-hq.mp4 16-tracking-shot-hq.mp4 17-follow-shot-over-the-shoulder-hq.mp4 18-reverse-tracking-walk-and-talk-hq.mp4 19-side-tracking-hq.mp4 20-low-tracking-v2-hq.mp4 21-vehicle-tracking-hq.mp4 22-chase-shot-hq.mp4 10-truck-right-hq.mp4 10b-truck-left-hq.mp4 11a-pedestal-up-hq.mp4 11b-pedestal-down-hq.mp4 12-slider-right-hq.mp4 12b-slider-left-hq.mp4 13-push-past-pass-by-shot-hq.mp4 14-arc-right-hq.mp4 14b-arc-left-hq.mp4 15-orbit-clockwise-hq.mp4 15b-orbit-counterclockwise-hq.mp4 23-handheld-shot-hq.mp4 24-snorricam-v2-hq.mp4 25-crane-up-hq.mp4 25b-crane-down-hq.mp4 26-drone-push-in-hq.mp4 26b-drone-pull-back-hq.mp4 27-helicopter-shot-hq.mp4 s1-first-person-view-hq.mp4 s2-tilt-shift-hq.mp4 s3-infinite-zoom-hq.mp4 s4-earth-zoom-out-hq.mp4 s5-time-lapse-hq.mp4 s6-pass-through-objects-hq.mp4; do
  if [ -s "$DEST/$f" ]; then ok=$((ok+1)); continue; fi
  if curl -fsSL --retry 3 --max-time 120 -o "$DEST/$f.part" "$BASE/$f"; then
    mv "$DEST/$f.part" "$DEST/$f"; ok=$((ok+1))
  else
    rm -f "$DEST/$f.part"; echo "не скачалось: $f" >&2; fail=$((fail+1))
  fi
done
echo "готово: $ok из 46, ошибок: $fail"
du -sh "$DEST"
