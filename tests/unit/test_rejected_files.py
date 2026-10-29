from __future__ import annotations

import csv
from pathlib import Path

from app.scanning.scanner import FileScanner
from app.transfer.rejected_files import REASONS_FILE, RejectedFiles, default_rejected_folder, is_unlisted_extension
from app.validation.extension_policy import ExtensionPolicy
from app.validation.signature_policy import SignaturePolicy
from tests.unit.media_samples import make_jpeg, make_png


def test_unlisted_extensions_from_several_folders_end_up_in_one_folder(tmp_path: Path) -> None:
    source = tmp_path / "Media"
    for folder in ("trip", "family", "work"):
        (source / folder).mkdir(parents=True)
        (source / folder / "good.jpg").write_bytes(make_jpeg())
    (source / "trip" / "broken.jpg").write_bytes(b"not really a photo")
    (source / "trip" / "renamed.jpg").write_bytes(make_png())
    (source / "family" / "broken.jpg").write_bytes(b"\xff\xd8\xff garbage")
    (source / "work" / "notes.txt").write_text("not a media file")
    (source / "family" / "setup.exe").write_bytes(b"MZ")

    policy = ExtensionPolicy()
    result = FileScanner(policy, SignaturePolicy(policy)).scan(source)
    rejected = RejectedFiles(source)
    for issue in result.skipped:
        if is_unlisted_extension(issue.reason):
            rejected.move(Path(issue.path).relative_to(result.source_root).as_posix(), issue.reason)

    folder = default_rejected_folder(source)
    assert folder == tmp_path / "Media_rejected"
    moved = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.name != REASONS_FILE and p.is_file())
    assert moved == ["family/setup.exe", "work/notes.txt"]
    # Moved, not copied; files with an allowed extension stay, even broken ones.
    assert not (source / "work" / "notes.txt").exists()
    assert all((source / folder_name / "good.jpg").exists() for folder_name in ("trip", "family", "work"))
    assert (source / "trip" / "broken.jpg").exists()
    assert (source / "trip" / "renamed.jpg").exists()

    with (folder / REASONS_FILE).open(encoding="utf-8") as handle:
        rows = {row["original_path"]: row["reason"] for row in csv.DictReader(handle)}
    assert rows["work/notes.txt"] == "unsupported_extension"
    assert rows["family/setup.exe"] == "blocked_extension"


def test_moving_keeps_both_files_when_names_collide(tmp_path: Path) -> None:
    source = tmp_path / "Media"
    source.mkdir()
    rejected = RejectedFiles(source)
    (source / "a.jpg").write_bytes(b"first")
    rejected.move("a.jpg", "unrecognized_content")
    (source / "a.jpg").write_bytes(b"second")
    second = rejected.move("a.jpg", "unrecognized_content")

    assert second == rejected.folder / "a (1).jpg"
    assert (rejected.folder / "a.jpg").read_bytes() == b"first"
    assert second.read_bytes() == b"second"


def test_only_unlisted_extensions_are_moved() -> None:
    assert is_unlisted_extension("unsupported_extension")
    assert is_unlisted_extension("blocked_extension")
    # Allowed extension but bad content: skipped, left in place.
    assert not is_unlisted_extension("unrecognized_content")
    assert not is_unlisted_extension("extension_mismatch:content_is_png")
    assert not is_unlisted_extension("symlink_not_allowed")
