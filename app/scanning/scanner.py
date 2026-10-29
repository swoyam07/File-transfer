from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.models.manifest import FileManifestEntry, ScanIssue, ScanResult
from app.validation.extension_policy import ExtensionPolicy
from app.validation.signature_policy import SignaturePolicy, SignatureResult


class FileScanner:
    def __init__(
        self,
        extension_policy: ExtensionPolicy,
        signature_policy: SignaturePolicy | None = None,
    ) -> None:
        self._extension_policy = extension_policy
        self._signature_policy = signature_policy

    def scan(
        self,
        source_root: Path,
        *,
        exclude: Path | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> ScanResult:
        """on_progress(done, total) is called as paths are checked."""
        source_root = source_root.resolve()
        result = ScanResult(source_root=source_root)
        exclude = exclude.resolve() if exclude else None
        report = on_progress or (lambda done, total: None)

        paths = sorted(source_root.rglob("*"))
        for done, path in enumerate(paths):
            report(done, len(paths))
            if exclude is not None and path.is_relative_to(exclude):
                continue  # the rejected-files folder, if it was put inside the source
            if path.is_symlink():
                result.skipped.append(ScanIssue(path=path, reason="symlink_not_allowed"))
                continue
            if not path.is_file():
                continue

            extension = path.suffix.lower()
            if self._extension_policy.is_blocked(extension):
                result.skipped.append(ScanIssue(path=path, reason="blocked_extension"))
                continue

            category = self._extension_policy.allowed_category_for_extension(extension)
            if category is None:
                result.skipped.append(ScanIssue(path=path, reason="unsupported_extension"))
                continue

            signature_result = self._check_signature(path, extension)
            if signature_result.decision == "reject":
                result.skipped.append(ScanIssue(path=path, reason=signature_result.reason))
                continue

            relative_path = path.relative_to(source_root).as_posix()
            stat = path.stat()

            entry = FileManifestEntry(
                relative_path=relative_path,
                category=category,
                extension=extension,
                size_bytes=stat.st_size,
                modified_time_ns=stat.st_mtime_ns,
                signature_extension=signature_result.detected_extension,
                mime_type=signature_result.mime_type,
                warnings=list(signature_result.warnings),
            )

            if signature_result.warnings:
                result.warnings.append(ScanIssue(path=path, reason=";".join(signature_result.warnings)))

            result.category_entries(category).append(entry)

        report(len(paths), len(paths))
        return result

    def _check_signature(self, path: Path, extension: str) -> SignatureResult:
        if self._signature_policy is None:
            return SignatureResult.allow_unknown()

        return self._signature_policy.inspect_file(path, claimed_extension=extension)