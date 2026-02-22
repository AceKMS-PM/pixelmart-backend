"""
Encryption utilities for sensitive data at rest.
Uses Fernet (AES-128-CBC + HMAC-SHA256) from the cryptography library.

Usage:
    from common.encryption import encrypt, decrypt

    encrypted = encrypt("my-secret")
    plaintext = decrypt(encrypted)

Key generation (run once, store in .env as ENCRYPTION_KEY):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Security rules:
    - ENCRYPTION_KEY must never be stored in the same place as the DB credentials.
      If both leak together, encryption provides no protection.
    - Never change ENCRYPTION_KEY without first re-encrypting all existing records.
      Changing the key makes all existing ciphertext permanently unreadable.
    - decrypt() raises ValueError on failure — callers must handle it explicitly.
      Silent fallback to '' would mask key-mismatch bugs as TOTP failures.
"""

import threading
from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken


# Thread-safe lazy singleton — one Fernet instance per process.
# Lock only taken on first call; subsequent calls are lock-free.
_fernet: Fernet | None = None
_lock = threading.Lock()


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        with _lock:
            if _fernet is None:               # double-checked locking
                key = getattr(settings, 'ENCRYPTION_KEY', None)
                if not key:
                    raise RuntimeError(
                        'ENCRYPTION_KEY is not configured. '
                        'Generate one with: '
                        'python -c "from cryptography.fernet import Fernet; '
                        'print(Fernet.generate_key().decode())" '
                        'and add it to your .env file.'
                    )
                _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(plaintext: str) -> str:
    """
    Encrypt a UTF-8 string. Returns a URL-safe base64 Fernet token (str).
    Raises RuntimeError if ENCRYPTION_KEY is not configured.
    """
    if not plaintext:
        return ''
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """
    Decrypt a Fernet token produced by encrypt().
    Returns the original plaintext string.

    Raises:
        ValueError  — if the token is invalid, expired, or was encrypted
                      with a different key. Callers must catch this and
                      return a 500 — do NOT silently return '' or the
                      caller will pass an empty string to pyotp and produce
                      misleading 'invalid code' errors instead of surfacing
                      the real configuration problem.
        RuntimeError — if ENCRYPTION_KEY is not configured.
    """
    if not ciphertext:
        return ''
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            'Decryption failed: the token is invalid or was encrypted with a '
            'different ENCRYPTION_KEY. If you rotated the key, re-encrypt all '
            'existing records before deploying.'
        ) from exc