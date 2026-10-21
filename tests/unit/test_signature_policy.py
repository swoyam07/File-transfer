from __future__ import annotations

from pathlib import Path

from app.validation.extension_policy import ExtensionPolicy
from app.validation.signature_policy import SignaturePolicy
from tests.unit.media_samples import make_png


PNG_BYTES = make_png()


def test_signature_policy_allows_matching_png(tmp_path: Path) -> None:
    file_path = tmp_path / "image.png"
    file_path.write_bytes(PNG_BYTES)

    policy = SignaturePolicy(ExtensionPolicy(), enabled=True)
    result = policy.inspect_file(file_path, claimed_extension=".png")

    assert result.decision == "allow"
    assert result.detected_extension == ".png"
    assert result.mime_type == "png"


def test_signature_policy_rejects_blocked_detected_type(tmp_path: Path) -> None:
    file_path = tmp_path / "fake.jpg"
    file_path.write_bytes(b"MZ" + b"\x00" * 128)

    policy = SignaturePolicy(ExtensionPolicy(), enabled=True)
    result = policy.inspect_file(file_path, claimed_extension=".jpg")

    assert result.decision == "reject"