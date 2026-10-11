#!/usr/bin/env bash
# Примеры движений камеры: 46 роликов + постеры с aicameramovements.com → assets/camera/
# Запуск из корня репозитория:  bash download_camera_examples.sh
set -euo pipefail
BASE="https://aicameramovements.com/previews/hq"
DEST="assets/camera"
mkdir -p "$DEST"
FILES=(
  01-static-shot-hq 02-pan-right-hq 2b-pan-left-hq 03-whip-pan-right-hq 3b-whip-pan-left-hq
  04-tilt-up-hq 4b-tilt-down-hq 05-slow-zoom-in-hq 5b-slow-zoom-out-hq
  06-fast-zoom-in-v2-hq 06b-fast-zoom-out-v2-hq 07a-crash-zoom-in-v2-hq 07b-crash-zoom-out-v2-hq
  08-dolly-in-hq 09-dolly-out-hq 16-tracking-shot-hq 17-follow-shot-over-the-shoulder-hq
  18-reverse-tracking-walk-and-talk-hq 19-side-tracking-hq 20-low-tracking-v2-hq
  21-vehicle-tracking-hq 22-chase-shot-hq 10-truck-right-hq 10b-truck-left-hq
  11a-pedestal-up-hq 11b-pedestal-down-hq 12-slider-right-hq 12b-slider-left-hq
  13-push-past-pass-by-shot-hq 14-arc-right-hq 14b-arc-left-hq 15-orbit-clockwise-hq
  15b-orbit-counterclockwise-hq 23-handheld-shot-hq 24-snorricam-v2-hq 25-crane-up-hq
  25b-crane-down-hq 26-drone-push-in-hq 26b-drone-pull-back-hq 27-helicopter-shot-hq
  s1-first-person-view-hq s2-tilt-shift-hq s3-infinite-zoom-hq s4-earth-zoom-out-hq
  s5-time-lapse-hq s6-pass-through-objects-hq
)
ok=0; fail=0
for stem in "${FILES[@]}"; do
  for ext in mp4 jpg; do
    f="${stem}.${ext}"
    if [ -s "$DEST/$f" ]; then ok=$((ok+1)); continue; fi
    if curl -fsSL --retry 3 --max-time 120 -o "$DEST/$f.part" "$BASE/$f"; then
      mv "$DEST/$f.part" "$DEST/$f"; ok=$((ok+1))
    else
      rm -f "$DEST/$f.part"; echo "не скачалось: $f" >&2; fail=$((fail+1))
    fi
  done
done
echo "готово: $ok файлов, ошибок: $fail (ожидается 92 = 46 mp4 + 46 jpg)"
du -sh "$DEST"
