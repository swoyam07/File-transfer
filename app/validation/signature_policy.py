from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.validation.extension_policy import ExtensionPolicy
from app.validation.media_inspector import MediaInspector

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SignatureResult:
    decision: str
    reason: str
    detected_extension: str | None = None
    mime_type: str | None = None
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def allow_unknown(cls) -> "SignatureResult":
        return cls(decision="allow", reason="signature_check_disabled")

    @classmethod
    def allow(cls, *, detected_extension: str | None, mime_type: str | None, warnings: list[str] | None = None) -> "SignatureResult":
        return cls(
            decision="allow",
            reason="allowed",
            detected_extension=detected_extension,
            mime_type=mime_type,
            warnings=warnings or [],
        )

    @classmethod
    def reject(cls, reason: str, *, detected_extension: str | None = None, mime_type: str | None = None) -> "SignatureResult":
        return cls(
            decision="reject",
            reason=reason,
            detected_extension=detected_extension,
            mime_type=mime_type,
        )


class SignaturePolicy:
    """
    Verifies that a file's content really is the media format its extension
    claims. Unknown or mismatched content is always rejected.
    """

    def __init__(self, extension_policy: ExtensionPolicy, *, enabled: bool = True, strict: bool = False) -> None:
        self._extension_policy = extension_policy
        self._enabled = enabled
        self._inspector = MediaInspector(strict=strict)

    def inspect_file(self, path: Path, *, claimed_extension: str) -> SignatureResult:
        if not self._enabled:
            return SignatureResult.allow_unknown()

        normalized_claim = self._extension_policy.normalize_extension(claimed_extension)
        if not self._extension_policy.is_allowed(normalized_claim):
            return SignatureResult.reject("unsupported_extension")

        result = self._inspector.inspect(path, claimed_extension=normalized_claim)
        if not result.ok:
            logger.warning("file_rejected", extra={"path": str(path), "reason": result.reason})
            return SignatureResult.reject(result.reason, detected_extension=result.format)

        if result.category != self._extension_policy.allowed_category_for_extension(normalized_claim):
            return SignatureResult.reject("signature_category_mismatch", detected_extension=result.format)

        return SignatureResult.allow(
            detected_extension=normalized_claim,
            mime_type=result.format,
            warnings=result.warnings,
        )
