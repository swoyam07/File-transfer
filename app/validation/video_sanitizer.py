"""
Removes metadata from videos by remuxing them with ffmpeg.

Streams are copied without re-encoding (no quality loss). Only video and audio
streams are kept: data streams (GPS / telemetry tracks), attachments, chapters
and container metadata (title, location, device, creation tool) are dropped.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_FFMPEG_TIMEOUT_SECONDS = 6 * 60 * 60


def find_ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def strip_video_metadata(source: Path, destination: Path, *, ffmpeg: str) -> None:
    command = [
        ffmpeg,
        "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(source),
        "-map", "0:v", "-map", "0:a?",
        "-c", "copy",
        "-map_metadata", "-1",
        "-map_chapters", "-1",
        # bitexact keeps the output identical between runs, which a resumed
        # transfer relies on.
        "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
        "-y", str(destination),
    ]
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=_FFMPEG_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0 or not destination.exists():
        message = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(f"ffmpeg_failed: {message[-1] if message else result.returncode}")
