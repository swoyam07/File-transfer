from __future__ import annotations

from dataclasses import dataclass, field

from app.constants import (
    DEFAULT_ALLOWED_IMAGE_EXTENSIONS,
    DEFAULT_ALLOWED_VIDEO_EXTENSIONS,
    DEFAULT_BLOCKED_EXTENSIONS,
)
from app.validation.media_inspector import category_for_extension


@dataclass(slots=True)
class ExtensionPolicy:
    allowed_images: set[str] = field(default_factory=lambda: set(DEFAULT_ALLOWED_IMAGE_EXTENSIONS))
    allowed_videos: set[str] = field(default_factory=lambda: set(DEFAULT_ALLOWED_VIDEO_EXTENSIONS))
    blocked_extensions: set[str] = field(default_factory=lambda: set(DEFAULT_BLOCKED_EXTENSIONS))

    @classmethod
    def from_config(cls, allowed: dict[str, set[str]], blocked: set[str]) -> "ExtensionPolicy":
        return cls(
            allowed_images=set(allowed.get("images", set())),
            allowed_videos=set(allowed.get("videos", set())),
            blocked_extensions=set(blocked) | set(DEFAULT_BLOCKED_EXTENSIONS),
        )

    def normalize_extension(self, extension: str) -> str:
        ext = extension.strip().lower()
        if not ext.startswith(".") and ext:
            ext = f".{ext}"
        return ext

    def is_blocked(self, extension: str) -> bool:
        return self.normalize_extension(extension) in self.blocked_extensions

    def allowed_category_for_extension(self, extension: str) -> str | None:
        normalized = self.normalize_extension(extension)
        if normalized in self.blocked_extensions:
            return None
        # An extension is only usable when the media inspector can validate
        # that format and it sits in the matching category.
        if normalized in self.allowed_images and category_for_extension(normalized) == "images":
            return "images"
        if normalized in self.allowed_videos and category_for_extension(normalized) == "videos":
            return "videos"
        return None

    def is_allowed(self, extension: str) -> bool:
        return self.allowed_category_for_extension(extension) is not None
