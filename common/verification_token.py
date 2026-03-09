import uuid
import secrets
from django.core.cache import cache


VERIFICATION_CACHE_PREFIX = 'email_verification:'
VERIFICATION_CACHE_TTL = 86400  # 24 hours


def generate_verification_token(user_id: str) -> str:
    """
    Generate a secure, random verification token and store it in cache.
    
    Returns:
        str: A URL-safe random token
    """
    token = secrets.token_urlsafe(32)
    cache.set(f'{VERIFICATION_CACHE_PREFIX}{token}', user_id, timeout=VERIFICATION_CACHE_TTL)
    return token


def verify_token(token: str) -> str | None:
    """
    Verify a verification token and return the user ID if valid.
    Token is single-use - it's deleted after verification.
    
    Returns:
        str: User ID if valid, None if invalid/expired
    """
    key = f'{VERIFICATION_CACHE_PREFIX}{token}'
    user_id = cache.get(key)
    if user_id:
        cache.delete(key)  # Single-use token
    return user_id


def get_token_ttl(token: str) -> int:
    """Get remaining TTL for a token in seconds."""
    key = f'{VERIFICATION_CACHE_PREFIX}{token}'
    return cache.ttl(key)


def delete_token(token: str) -> None:
    """Delete a token (for rate limiting purposes)."""
    cache.delete(f'{VERIFICATION_CACHE_PREFIX}{token}')
