"""
Encryption utilities for sensitive data at rest.
Uses Fernet (AES-128-CBC) from cryptography library.
"""

from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken


_fernet: Fernet | None = None


def get_fernet() -> Fernet:
    """
    Lazy-load Fernet instance. Raises RuntimeError if ENCRYPTION_KEY not configured.
    """
    global _fernet
    if _fernet is None:
        key = settings.ENCRYPTION_KEY
        if not key:
            raise RuntimeError(
                "ENCRYPTION_KEY is not set. Generate one with:\n"
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        _fernet = Fernet(key.encode())
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return the encrypted value as a string."""
    if not plaintext:
        return ''
    f = get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a string. Returns empty string if decryption fails."""
    if not ciphertext:
        return ''
    f = get_fernet()
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return ''
