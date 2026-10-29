"""
Moves files whose extension is not in allowed_extensions out of the source
folder into one "rejected" folder on the sender, so they can be looked at later.

Files are only moved: never repaired, changed or sent. Their subfolders are
kept, so files from different folders cannot collide, and reasons.csv lists
why each one was moved.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from app.utils.time_utils import utc_now_iso

REASONS_FILE = "reasons.csv"

# Only files whose extension is not in allowed_extensions are moved. Files with
# an allowed extension that fail the content checks stay where they are.
_UNLISTED_EXTENSION = ("unsupported_extension", "blocked_extension")


def default_rejected_folder(source_root: Path) -> Path:
    # Next to the source folder, not inside it, so the next scan does not find it.
    return source_root.parent / f"{source_root.name}_rejected"


def is_unlisted_extension(reason: str) -> bool:
    return reason in _UNLISTED_EXTENSION


class RejectedFiles:
    def __init__(self, source_root: Path, folder: Path | None = None) -> None:
        self.source_root = source_root.resolve()
        self.folder = (folder or default_rejected_folder(self.source_root)).resolve()

    def move(self, relative_path: str, reason: str) -> Path | None:
        """Move one file and record why. Returns the new path, or None when
        there is no regular file to move."""
        source = self.source_root / relative_path
        if source.is_symlink() or not source.is_file():
            return None
        target = self.folder / relative_path
        candidate = target
        counter = 1
        while candidate.exists():
            candidate = target.with_name(f"{target.stem} ({counter}){target.suffix}")
            counter += 1
        candidate.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source, candidate)
        self._record(relative_path, reason, candidate)
        return candidate

    def _record(self, relative_path: str, reason: str, moved_to: Path) -> None:
        reasons = self.folder / REASONS_FILE
        new = not reasons.exists()
        with reasons.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if new:
                writer.writerow(["time", "original_path", "reason", "moved_to"])
            writer.writerow([utc_now_iso(), relative_path, reason, moved_to.relative_to(self.folder).as_posix()])
