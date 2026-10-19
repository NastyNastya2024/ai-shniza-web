"""Publish video compress: original stays full; public copy ~1/3 size."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

import pytest

import media_store


def _have_ffmpeg() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


@pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg required")
def test_compress_video_for_publish_shrinks_about_3x():
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "src.mp4")
        out = os.path.join(td, "out.mp4")
        # Noisy high-bitrate clip so there is headroom to compress ~3×.
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                "-t", "4", "-c:v", "libx264", "-preset", "ultrafast",
                "-x264-params", "qp=12", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", src,
            ],
            check=True, capture_output=True,
        )
        old = os.path.getsize(src)
        assert media_store.compress_video_for_publish(src, out, size_ratio=3.0)
        new = os.path.getsize(out)
        assert os.path.getsize(src) == old  # source untouched
        assert new < old * 0.55
        assert new > 1000


@pytest.mark.skipif(not _have_ffmpeg(), reason="ffmpeg required")
def test_compress_video_file_inplace_marks_and_is_idempotent():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "clip.mp4")
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=960x540:rate=24",
                "-t", "3", "-c:v", "libx264", "-preset", "ultrafast",
                "-x264-params", "qp=12", "-pix_fmt", "yuv420p", "-an", path,
            ],
            check=True, capture_output=True,
        )
        changed, old, new = media_store.compress_video_file_inplace(path, size_ratio=3.0)
        assert changed and new < old * 0.55
        assert os.path.isfile(path + ".aish-pub3")
        changed2, old2, new2 = media_store.compress_video_file_inplace(path, size_ratio=3.0)
        assert not changed2 and old2 == new2
