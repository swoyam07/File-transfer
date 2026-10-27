from __future__ import annotations

import csv
from pathlib import Path

from app.scanning.scanner import FileScanner
from app.transfer.rejected_files import REASONS_FILE, RejectedFiles, default_rejected_folder, is_file_problem
from app.validation.extension_policy import ExtensionPolicy
from app.validation.signature_policy import SignaturePolicy
from tests.unit.media_samples import make_jpeg, make_png


def test_bad_files_from_several_folders_end_up_in_one_folder(tmp_path: Path) -> None:
    source = tmp_path / "Media"
    for folder in ("trip", "family", "work"):
        (source / folder).mkdir(parents=True)
        (source / folder / "good.jpg").write_bytes(make_jpeg())
    (source / "trip" / "broken.jpg").write_bytes(b"not really a photo")
    (source / "trip" / "renamed.jpg").write_bytes(make_png())
    (source / "family" / "broken.jpg").write_bytes(b"\xff\xd8\xff garbage")
    (source / "work" / "notes.txt").write_text("not a media file")

    policy = ExtensionPolicy()
    result = FileScanner(policy, SignaturePolicy(policy)).scan(source)
    rejected = RejectedFiles(source)
    for issue in result.skipped:
        if is_file_problem(issue.reason):
            rejected.move(Path(issue.path).relative_to(result.source_root).as_posix(), issue.reason)

    folder = default_rejected_folder(source)
    assert folder == tmp_path / "Media_rejected"
    moved = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.name != REASONS_FILE and p.is_file())
    assert moved == ["family/broken.jpg", "trip/broken.jpg", "trip/renamed.jpg"]
    # Moved, not copied; good files and unrelated files stay where they were.
    assert not (source / "trip" / "broken.jpg").exists()
    assert all((source / folder_name / "good.jpg").exists() for folder_name in ("trip", "family", "work"))
    assert (source / "work" / "notes.txt").exists()

    with (folder / REASONS_FILE).open(encoding="utf-8") as handle:
        rows = {row["original_path"]: row["reason"] for row in csv.DictReader(handle)}
    assert rows["trip/renamed.jpg"] == "extension_mismatch:content_is_png"
    assert rows["trip/broken.jpg"] == "unrecognized_content"


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


def test_only_problems_with_the_file_itself_count() -> None:
    assert is_file_problem("unrecognized_content")
    assert is_file_problem("sender: ffmpeg_failed: invalid data")
    assert is_file_problem("receiver: suspicious_content:windows_executable")
    assert is_file_problem("receiver: pdf_active_content:JavaScript")
    # Not the file's fault: the cable, the receiver, disk space, or simply a type this app does not send.
    assert not is_file_problem("receiver: hash_mismatch")
    assert not is_file_problem("sender: not_enough_temp_space: needs 1 bytes free in /var/tmp")
    assert not is_file_problem("unsupported_extension")
    assert not is_file_problem("blocked_extension")


def test_scan_skips_a_rejected_folder_inside_the_source(tmp_path: Path) -> None:
    source = tmp_path / "Media"
    (source / "_rejected").mkdir(parents=True)
    (source / "_rejected" / "broken.jpg").write_bytes(b"junk")
    (source / "good.jpg").write_bytes(make_jpeg())

    policy = ExtensionPolicy()
    result = FileScanner(policy, SignaturePolicy(policy)).scan(source, exclude=source / "_rejected")
    assert [entry.relative_path for entry in result.images] == ["good.jpg"]
    assert result.skipped == []
