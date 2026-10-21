# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Safe Media Transfer: offline, two-app (Sender / Receiver) PySide6 desktop tool that moves approved media files between two PCs over a direct TCP connection. No database, cloud, or server. Originally targeted at Windows (`.bat` scripts, README uses PowerShell) but the Python code is cross-platform and runs on Linux.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest pytest-timeout   # or: pip install -e .[dev]

pytest -q                                 # all tests (config in pytest.ini / pyproject)
pytest tests/unit/test_protocol_framing.py            # one file
pytest tests/unit/test_scanner.py::test_name          # one test

python receiver_main.py                   # start receiver first (e.g. listen on 127.0.0.1:5001)
python sender_main.py

pyinstaller sender.spec                   # builds into dist/
pyinstaller receiver.spec
```

Config is read from `config.toml`, falling back to `config.example.toml` (`app/utils/platform_paths.py`). Logs go to `logs/`.

## Architecture

Entry points `sender_main.py` / `receiver_main.py` launch Qt windows in `app/ui/{sender,receiver}/`. Long-running work runs off the GUI thread in `app/ui/workers/` (scan, send, receive workers), which call the service layer.

Data flow:
1. **Scanning** (`app/scanning/`): walk the source folder (symlinks refused), filter by `ExtensionPolicy` (built from config via `ExtensionPolicy.from_config`), then `SignaturePolicy` → `MediaInspector` validates real content.
2. **Validation** (`app/validation/`): `media_inspector.py` parses JPEG/PNG/HEIF/ISO-BMFF/Matroska/AVI structure, fails closed, and holds the extension→format map (`EXTENSION_FORMATS`); config may only allow extensions listed there. `strict=True` (receiver) rejects trailing data, `strict=False` (sender) warns because sanitizing removes it. `content_scanner.py` searches bytes for executable/script markers (images at inspect time, videos while streaming on the receiver). `sanitize_jpeg/png` strip metadata; `video_sanitizer.py` remuxes with ffmpeg (bitexact, so resume works).
3. **Handshake** (`app/security/auth.py`): HELLO/HELLO_ACK nonces → HMAC proofs from a PBKDF2 key of the pairing code (mutual) → session key that signs each file's SHA-256. `network_policy.py` restricts receiver peers and sender targets to LAN ranges. Version is `WIRE_PROTOCOL_VERSION` (separate from the unused binary `PROTOCOL_VERSION` framing in `app/protocol/`).
4. **Transfer** (`app/transfer/`): sender re-validates and sanitizes each file into a temp dir right before `FILE_START` (actual size goes in FILE_START, manifest sizes are estimates), sends `FILE_CANCEL` for files that fail. Receiver trusts nothing: re-checks path/extension/size/content, hashes while receiving, and only moves `.part` into place after everything passes; rejected parts are deleted. Per-file `FILE_RESULT` lets the batch continue past rejections. `SocketTransport.receive_json_message(max_bytes=...)` caps message size.
5. **Resume**: `.part` + `.part.json` sidecar (`app/state/resume_store.py`, atomic JSON); offset reused only if the state's expected size matches the new FILE_START size.
6. **Paths**: `app/security/path_validator.py` validates the raw string (no `..`, `:`, reserved Windows names, trailing dots/spaces) and keeps writes inside the destination.

Config parsing/validation lives in `app/config/` (loader + validator); custom exceptions in `app/exceptions.py`.

`tests/unit/media_samples.py` builds minimal valid media files for tests. `tests/unit/test_media_security.py` covers the attack cases end to end over localhost (including a tampered sender subclass that skips local checks, and a real-ffmpeg test that is skipped when ffmpeg is absent). Run the full suite after any protocol, validation or transfer change.
