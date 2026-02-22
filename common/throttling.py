"""
Custom throttle classes for sensitive authentication endpoints.

All auth endpoints are public (AllowAny), so we throttle by IP address only.
We use AnonRateThrottle as the base class — it always uses the IP as the cache
key, regardless of whether the request carries a valid JWT.

ScopedRateThrottle would switch to user-based keys for authenticated requests,
which is wrong for login/register: an attacker could bypass the IP limit by
attaching any valid token to their brute-force requests.

Rates are configured in settings.py under DEFAULT_THROTTLE_RATES:
    'login':          '5/min'
    'register':       '10/min'
    'password_reset': '3/min'
"""

from rest_framework.throttling import AnonRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    """
    5 requests / minute / IP on POST /auth/login/.
    Prevents brute-force password attacks.
    """
    scope = 'login'


class RegisterRateThrottle(AnonRateThrottle):
    """
    10 requests / minute / IP on POST /auth/register/.
    Prevents mass account creation / credential stuffing setup.
    """
    scope = 'register'


class PasswordResetRateThrottle(AnonRateThrottle):
    """
    3 requests / minute / IP on POST /auth/forgot-password/.
    Prevents email spam abuse.
    """
    scope = 'password_reset'