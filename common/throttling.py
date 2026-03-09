"""
Custom throttle classes for sensitive authentication endpoints.
"""
from rest_framework.throttling import ScopedRateThrottle


class LoginRateThrottle(ScopedRateThrottle):
    """
    Throttle for login endpoint - 5 requests per minute per IP.
    Prevents brute-force password attacks.
    """
    scope = 'login'


class RegisterRateThrottle(ScopedRateThrottle):
    """
    Throttle for registration endpoint - 10 requests per minute per IP.
    Prevents mass account creation.
    """
    scope = 'register'


class PasswordResetRateThrottle(ScopedRateThrottle):
    """
    Throttle for password reset endpoint - 3 requests per minute per IP.
    Prevents email spam abuse.
    """
    scope = 'password_reset'


class VerifyEmailRateThrottle(ScopedRateThrottle):
    """
    Throttle for email verification endpoint - 10 requests per minute per IP.
    Prevents brute-force token attacks.
    """
    scope = 'verify_email'
