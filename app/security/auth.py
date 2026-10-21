"""
Mutual authentication with a shared pairing code.

Both computers are configured with the same pairing code. During the handshake
each side proves it knows the code without sending it:

    sender   -> HELLO        {client_nonce}
    receiver -> HELLO_ACK    {server_nonce}
    sender   -> AUTH_REQUEST {proof = HMAC(key, "client" | nonces)}
    receiver -> AUTH_RESULT  {ok, proof = HMAC(key, "server" | nonces)}

A session key derived from both nonces then signs every file's SHA-256, so a
device on the network cannot inject or alter file data without detection.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

MIN_PAIRING_CODE_LENGTH = 8
NONCE_BYTES = 32
_KDF_SALT = b"safe-media-transfer/pairing/v2"
_KDF_ITERATIONS = 200_000


class AuthError(Exception):
    pass


def validate_pairing_code(code: str) -> str:
    code = code.strip()
    if len(code) < MIN_PAIRING_CODE_LENGTH:
        raise AuthError(f"Pairing code must be at least {MIN_PAIRING_CODE_LENGTH} characters")
    return code


def derive_key(pairing_code: str) -> bytes:
    code = validate_pairing_code(pairing_code)
    return hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), _KDF_SALT, _KDF_ITERATIONS)


def new_nonce() -> str:
    return secrets.token_hex(NONCE_BYTES)


def _mac(key: bytes, label: str, *parts: str) -> str:
    message = "|".join((label, *parts)).encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def client_proof(key: bytes, client_nonce: str, server_nonce: str) -> str:
    return _mac(key, "client", client_nonce, server_nonce)


def server_proof(key: bytes, client_nonce: str, server_nonce: str) -> str:
    return _mac(key, "server", client_nonce, server_nonce)


def session_key(key: bytes, client_nonce: str, server_nonce: str) -> bytes:
    return bytes.fromhex(_mac(key, "session", client_nonce, server_nonce))


def file_tag(session: bytes, relative_path: str, size: int, sha256: str) -> str:
    return _mac(session, "file", relative_path, str(size), sha256.lower())


def verify(expected: str, received: object) -> bool:
    return isinstance(received, str) and hmac.compare_digest(expected, received)


def check_nonce(value: object) -> str:
    if not isinstance(value, str) or len(value) != NONCE_BYTES * 2:
        raise AuthError("invalid_nonce")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise AuthError("invalid_nonce") from exc
    return value
