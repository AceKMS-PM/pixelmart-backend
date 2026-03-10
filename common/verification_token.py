import secrets
from typing import Optional
from django.core.cache import cache

VERIFICATION_CACHE_PREFIX = 'email_verification:'
VERIFICATION_CACHE_TTL    = 86400  # 24 hours


def generate_verification_token(user_id: str) -> str:
    """Generate a secure random token and store user_id in cache (24h TTL)."""
    token = secrets.token_urlsafe(32)
    cache.set(f'{VERIFICATION_CACHE_PREFIX}{token}', user_id, timeout=VERIFICATION_CACHE_TTL)
    return token


def verify_token(token: str) -> Optional[str]:
    """
    Validate token and return user_id if valid.
    Single-use: deleted immediately after successful lookup.
    """
    key     = f'{VERIFICATION_CACHE_PREFIX}{token}'
    user_id = cache.get(key)
    if user_id:
        cache.delete(key)
    return user_id