"""
Searches file bytes for markers of executables and scripts.

Media files are compressed binary data, so long readable markers such as a
Windows executable stub or "<script" essentially never occur by chance. Finding
one means something was embedded in the file and it is rejected.

The scanner is incremental so it can be fed chunks while a file streams over
the network, with an overlap so a marker split across chunks is still found.
"""

from __future__ import annotations

import re
from pathlib import Path

# (name, literal anchor in lower case, precise pattern confirmed around a hit)
_PATTERNS: list[tuple[str, bytes, bytes]] = [
    ("windows_executable", b"this program cannot be run in dos mode", rb"this program cannot be run in dos mode"),
    ("windows_executable", b"this program must be run under win32", rb"this program must be run under win32"),
    ("html_script", b"<script", rb"<script[\s>/]"),
    ("html_document", b"<!doctype html", rb"<!doctype html"),
    ("html_document", b"<html", rb"<html[\s>]"),
    ("html_iframe", b"<iframe", rb"<iframe[\s>]"),
    ("php_code", b"<?php", rb"<\?php"),
    ("powershell", b"powershell", rb"powershell(?:\.exe)?\s+-"),
    ("windows_script_host", b"wscript.shell", rb"wscript\.shell"),
    ("windows_script_host", b"activexobject(", rb"activexobject\("),
    ("shell_script", b"#!/", rb"#!/(?:usr/)?bin/(?:env\s+)?(?:ba|z|k)?sh\b"),
    ("javascript_uri", b"javascript:", rb"javascript:[a-z]"),
]
_COMPILED = [(name, anchor, re.compile(pattern)) for name, anchor, pattern in _PATTERNS]
_LOWER = bytes.maketrans(bytes(range(65, 91)), bytes(range(97, 123)))
_OVERLAP = 64
_FILE_READ_SIZE = 8 * 1024 * 1024


class ContentScanner:
    def __init__(self) -> None:
        self._tail = b""
        self.finding: str | None = None

    def feed(self, chunk: bytes) -> str | None:
        if self.finding is not None:
            return self.finding
        # Lower-casing with translate() and searching literals with find()
        # both run in C, fast enough to scan multi-GB videos while they stream.
        window = (self._tail + chunk).translate(_LOWER)
        for name, anchor, pattern in _COMPILED:
            start = window.find(anchor)
            while start >= 0:
                if pattern.match(window, start, start + _OVERLAP):
                    self.finding = name
                    return name
                start = window.find(anchor, start + 1)
        self._tail = chunk[-_OVERLAP:] if len(chunk) >= _OVERLAP else (self._tail + chunk)[-_OVERLAP:]
        return None

    @classmethod
    def scan_file(cls, path: Path) -> str | None:
        scanner = cls()
        with path.open("rb") as handle:
            while chunk := handle.read(_FILE_READ_SIZE):
                if scanner.feed(chunk):
                    break
        return scanner.finding
