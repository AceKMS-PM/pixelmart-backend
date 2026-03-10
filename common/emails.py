import logging
from typing import Optional
from django.core.mail import send_mail
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.conf import settings
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

_RESET_SALT         = 'pixelmart-password-reset'
RESET_TOKEN_MAX_AGE = 60 * 60  # 1 hour


# ── Reset token helpers ───────────────────────────────────────────────────────

def make_reset_token(user) -> str:
    return TimestampSigner(salt=_RESET_SALT).sign(str(user.pk))


def unsign_reset_token(token: str) -> Optional[str]:
    """Returns user PK (str) or None if invalid/expired."""
    try:
        return TimestampSigner(salt=_RESET_SALT).unsign(token, max_age=RESET_TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


# ── Email senders ─────────────────────────────────────────────────────────────

def send_verification_email(user_email: str, verification_url: str, user_name: Optional[str] = None) -> bool:
    if user_name is None:
        user_name = user_email.split('@')[0]

    html_message = render_to_string('emails/verification.html', {
        'user_name':        user_name,
        'verification_url': verification_url,
    })

    try:
        send_mail(
            subject='Vérifiez votre adresse email — PixelMart',
            message=(
                f'Bonjour {user_name},\n\n'
                f'Bienvenue sur PixelMart ! Veuillez vérifier votre adresse email '
                f'en cliquant sur le lien ci-dessous :\n\n'
                f'{verification_url}\n\n'
                f'Ce lien expirera dans 24 heures.\n\n'
                f"Si vous n'avez pas créé de compte, ignorez cet email.\n\n"
                f"Cordialement,\nL'équipe PixelMart"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user_email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception('Failed to send verification email to %s', user_email)
        if settings.DEBUG:
            logger.debug('[EMAIL MOCK] Verification URL: %s', verification_url)
            return True
        return False


def send_welcome_email(user_email: str, user_name: Optional[str] = None) -> bool:
    if user_name is None:
        user_name = user_email.split('@')[0]

    frontend_url = getattr(settings, 'FRONTEND_URL', 'https://pixelmart.com').rstrip('/')

    try:
        send_mail(
            subject='Bienvenue sur PixelMart !',
            message=(
                f'Bonjour {user_name},\n\n'
                f'Votre adresse email a été vérifiée avec succès !\n\n'
                f'Vous pouvez maintenant vous connecter : {frontend_url}\n\n'
                f"Cordialement,\nL'équipe PixelMart"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user_email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception('Failed to send welcome email to %s', user_email)
        if settings.DEBUG:
            logger.debug('[EMAIL MOCK] Welcome email to: %s', user_email)
            return True
        return False


def send_password_reset_email(user) -> None:
    """
    Envoie le lien de réinitialisation du mot de passe.
    Token signé via TimestampSigner (1h TTL) — pas de Redis nécessaire.
    Échec silencieux en production (loggé).
    """
    token        = make_reset_token(user)
    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000').rstrip('/')
    link         = f'{frontend_url}/auth/reset-password?token={token}'

    try:
        send_mail(
            subject='Réinitialisation de votre mot de passe — PixelMart',
            message=(
                f'Bonjour {user.name},\n\n'
                f'Vous avez demandé la réinitialisation de votre mot de passe.\n'
                f'Cliquez sur le lien ci-dessous (valable 1 heure) :\n\n'
                f'{link}\n\n'
                f"Si vous n'êtes pas à l'origine de cette demande, ignorez cet email — "
                f'votre mot de passe ne sera pas modifié.\n\n'
                f"Cordialement,\nL'équipe PixelMart"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:
        logger.exception('Failed to send password reset email to %s', user.email)
        if settings.DEBUG:
            logger.debug('[EMAIL MOCK] Password reset URL: %s', link)