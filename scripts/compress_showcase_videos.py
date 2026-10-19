#!/usr/bin/env python3
"""Compress static showcase videos in-place (~1/PUBLISH_VIDEO_SIZE_RATIO of size).

Safe to re-run: writes sibling ``*.aish-pub3`` markers.
Usage:
  .venv/bin/python scripts/compress_showcase_videos.py
  .venv/bin/python scripts/compress_showcase_videos.py --retarget
  .venv/bin/python scripts/compress_showcase_videos.py --dry-run
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from media_store import (  # noqa: E402
    PUBLISH_VIDEO_SIZE_RATIO,
    compress_video_file_inplace,
    retarget_showcase_video,
)


def _collect() -> list[Path]:
    files: list[Path] = []
    for pattern in ("works", "assets/camera", "assets/models/examples"):
        base = ROOT / pattern
        if not base.is_dir():
            continue
        for p in sorted(base.iterdir()):
            if p.suffix.lower() in {".mp4", ".webm", ".mov"} and p.is_file():
                files.append(p)
    return files


def _one(path: Path, dry: bool, retarget: bool) -> str:
    rel = path.relative_to(ROOT)
    if dry:
        return f"dry\t{rel}\t{path.stat().st_size}"
    if retarget:
        changed, original, before, after = retarget_showcase_video(
            str(path), size_ratio=PUBLISH_VIDEO_SIZE_RATIO
        )
        if changed:
            return (
                f"ok\t{rel}\t{before}->{after}\t"
                f"vs_orig={round(original / max(after, 1), 2)}x"
            )
        return f"skip\t{rel}\t{before}\tvs_orig={round(original / max(before, 1), 2)}x"
    changed, old, new = compress_video_file_inplace(str(path), size_ratio=PUBLISH_VIDEO_SIZE_RATIO)
    if changed:
        return f"ok\t{rel}\t{old}->{new}\t{round(old / max(new, 1), 2)}x"
    return f"skip\t{rel}\t{old}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--retarget",
        action="store_true",
        help="Nudge already-compressed files to original/PUBLISH_VIDEO_SIZE_RATIO",
    )
    ap.add_argument("--jobs", type=int, default=2)
    args = ap.parse_args()
    files = _collect()
    print(
        f"files={len(files)} ratio={PUBLISH_VIDEO_SIZE_RATIO} "
        f"jobs={args.jobs} retarget={args.retarget}",
        flush=True,
    )
    total_before = total_after = 0
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futs = [pool.submit(_one, p, args.dry_run, args.retarget) for p in files]
        for fut in as_completed(futs):
            line = fut.result()
            print(line, flush=True)
            parts = line.split("\t")
            if parts[0] == "ok" and "->" in parts[2]:
                a, b = parts[2].split("->")
                total_before += int(a)
                total_after += int(b)
            elif parts[0] == "skip":
                n = int(parts[2])
                total_before += n
                total_after += n
    if not args.dry_run and total_before:
        print(
            f"TOTAL {total_before} -> {total_after} "
            f"({round(total_before / max(total_after, 1), 2)}x this pass)",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
