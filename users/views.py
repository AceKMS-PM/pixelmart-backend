import io
import base64
import secrets

import pyotp
import qrcode

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from django.conf import settings

from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from common.throttling import LoginRateThrottle, RegisterRateThrottle
from common.verification_token import generate_verification_token, verify_token
from common.emails import send_verification_email, send_welcome_email
from .serializers import (
    UserSerializer,
    UserRegistrationSerializer,
    UserUpdateSerializer,
    ChangePasswordSerializer,
    TOTPVerifySerializer,
)

User = get_user_model()


# ─────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────

def _issue_tokens(user):
    """Create a fresh JWT pair and stamp last_login_at."""
    refresh = RefreshToken.for_user(user)
    user.last_login_at = timezone.now()
    user.save(update_fields=['last_login_at'])
    return {
        'refresh': str(refresh),
        'access':  str(refresh.access_token),
    }


def _pending_cache_key(token):
    return f'2fa_pending:{token}'


def _attempt_cache_key(token):
    return f'2fa_attempts:{token}'


def _blacklist_all_tokens_for(user):
    """
    Blacklist every outstanding refresh token for this user.
    Called after password change and account deletion so stolen sessions
    cannot be reused.
    Requires rest_framework_simplejwt.token_blacklist in INSTALLED_APPS.
    """
    from rest_framework_simplejwt.token_blacklist.models import (
        OutstandingToken, BlacklistedToken,
    )
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


def _get_totp_or_500(user):
    """
    Safely decrypt the user's TOTP secret and return a pyotp.TOTP instance.

    Returns:
      pyotp.TOTP  — on success
      None        — if no secret is set (caller treats this as invalid state)
      Response    — HTTP 500 if decryption fails (key mismatch / corruption)

    Usage in views:
        totp = _get_totp_or_500(user)
        if isinstance(totp, Response):
            return totp
        if totp is None:
            return Response({'error': '...'}, status=400)
    """
    try:
        plain = user.totp_secret
    except ValueError:
        return Response(
            {'error': 'Authentication service error. Please contact support.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    if not plain:
        return None
    return pyotp.TOTP(plain)


# ─────────────────────────────────────────────────────────────
#  Registration
# ─────────────────────────────────────────────────────────────

class RegisterView(generics.CreateAPIView):
    """
    POST /auth/register/

    Creates the account and sends a verification email.
    NO tokens issued — the user must verify their email first, then
    log in via POST /auth/login/.

    Issuing tokens here would make the is_verified gate in LoginView
    meaningless: the user could skip login entirely and use the tokens
    from registration to access protected endpoints while unverified.

    Throttled: 10 req/min/IP (RegisterRateThrottle).
    """
    queryset           = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class   = UserRegistrationSerializer
    throttle_classes   = [RegisterRateThrottle]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        # Generate verification token and send email
        token = generate_verification_token(str(user.pk))
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
        verification_url = f'{frontend_url}/verify-email?token={token}'

        send_verification_email(user.email, verification_url, user.name)

        return Response(
            {
                'user':    UserSerializer(user).data,
                'message': (
                    'Registration successful. '
                    'Please check your email and click the verification link '
                    'before logging in.'
                ),
            },
            status=status.HTTP_201_CREATED,
        )


# ─────────────────────────────────────────────────────────────
#  Login — step 1
# ─────────────────────────────────────────────────────────────

class LoginView(APIView):
    """
    POST /auth/login/

    Security decisions:
    1. Identical error for wrong email AND wrong password — no user enumeration.
    2. is_banned + is_active checked before any other branch.
    3. is_verified gate: checked AFTER password validation (so an attacker
       with a wrong password cannot confirm that the email exists and is
       unverified). Returns a distinct error code so the frontend can
       offer a "Resend verification email" button.
    4. 2FA challenge returns an opaque pending_token (Redis, 5-min TTL).
       The real user PK is never sent to the client.
    5. Throttled: 5 req/min/IP (LoginRateThrottle).
    """
    permission_classes = [AllowAny]
    throttle_classes   = [LoginRateThrottle]

    def post(self, request):
        email    = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')

        if not email or not password:
            return Response(
                {'error': 'Email and password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        _invalid = Response(
            {'error': 'Invalid credentials.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return _invalid

        if not user.check_password(password):
            return _invalid

        if user.is_banned:
            return Response(
                {'error': 'Account suspended. Please contact support.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not user.is_active:
            return Response(
                {'error': 'Account is inactive.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Email verification gate ────────────────────────────
        # Checked after password so a wrong-password request cannot be used
        # to probe whether a given email is registered and unverified.
        if not user.is_verified:
            return Response(
                {
                    'error': 'Email not verified. Please check your inbox.',
                    'code':  'EMAIL_NOT_VERIFIED',  # frontend uses this for "Resend" button
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if user.is_2fa_enabled:
            pending_token = secrets.token_urlsafe(32)
            cache.set(_pending_cache_key(pending_token), user.pk, timeout=300)
            return Response({
                'requires_2fa':  True,
                'pending_token': pending_token,
            })

        tokens = _issue_tokens(user)
        return Response({'user': UserSerializer(user).data, **tokens})


# ─────────────────────────────────────────────────────────────
#  Login — step 2 (2FA code)
# ─────────────────────────────────────────────────────────────

class Login2FAView(APIView):
    """
    POST /auth/login/2fa/

    Security decisions:
    1. pending_token resolves to user PK via Redis — no DB ID on the wire.
    2. Attempt counter uses cache.add() + cache.incr() — atomic, race-safe.
    3. Max 5 attempts — lockout destroys both keys, forces restart from login.
    4. On success both keys deleted immediately (one-time-use token).
    5. Decryption errors return 500 — server config problem, not user error.
    """
    permission_classes = [AllowAny]

    _MAX_ATTEMPTS = 5
    _TTL          = 300  # must match LoginView TTL

    def post(self, request):
        pending_token = request.data.get('pending_token', '').strip()
        code          = request.data.get('code', '').strip()

        if not pending_token or not code:
            return Response(
                {'error': 'pending_token and code are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        p_key   = _pending_cache_key(pending_token)
        user_pk = cache.get(p_key)

        if user_pk is None:
            return Response(
                {'error': 'Invalid or expired token. Please log in again.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        a_key = _attempt_cache_key(pending_token)
        cache.add(a_key, 0, timeout=self._TTL)
        attempts = cache.incr(a_key)

        if attempts > self._MAX_ATTEMPTS:
            cache.delete(p_key)
            cache.delete(a_key)
            return Response(
                {'error': 'Too many attempts. Please log in again.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            user = User.objects.get(pk=user_pk)
        except User.DoesNotExist:
            cache.delete(p_key)
            return Response(
                {'error': 'Invalid or expired token.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        totp = _get_totp_or_500(user)
        if isinstance(totp, Response):
            cache.delete(p_key)
            return totp
        if totp is None:
            cache.delete(p_key)
            return Response(
                {'error': 'Invalid or expired token.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not totp.verify(code, valid_window=1):
            return Response(
                {'error': 'Invalid 2FA code.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        cache.delete(p_key)
        cache.delete(a_key)

        tokens = _issue_tokens(user)
        return Response({'user': UserSerializer(user).data, **tokens})


# ─────────────────────────────────────────────────────────────
#  Logout
# ─────────────────────────────────────────────────────────────

class LogoutView(APIView):
    """
    POST /auth/logout/
    Always 200 — prevents probing token validity. TokenError swallowed.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh', '')
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except TokenError:
                pass
        return Response({'message': 'Logged out successfully.'})


# ─────────────────────────────────────────────────────────────
#  Profile
# ─────────────────────────────────────────────────────────────

class ProfileView(generics.RetrieveUpdateAPIView):
    """
    GET   /auth/me/  → UserSerializer
    PATCH /auth/me/  → UserUpdateSerializer (name, avatar, phone, locale)

    Email changes blocked here — require re-verification via a future
    dedicated endpoint.
    """
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return UserUpdateSerializer
        return UserSerializer


# ─────────────────────────────────────────────────────────────
#  Change password
# ─────────────────────────────────────────────────────────────

class ChangePasswordView(generics.UpdateAPIView):
    """
    PUT /auth/me/password/

    After save, ALL outstanding refresh tokens are blacklisted —
    stolen tokens from a breach cannot be reused after a password reset.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = ChangePasswordSerializer

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        _blacklist_all_tokens_for(request.user)
        return Response({'message': 'Password changed successfully. Please log in again.'})


# ─────────────────────────────────────────────────────────────
#  2FA — Setup
# ─────────────────────────────────────────────────────────────

class TOTPSetupView(APIView):
    """
    POST /auth/2fa/setup/

    Generates + encrypts a new TOTP secret, returns plaintext secret + QR code.
    2FA activated only after POST /auth/2fa/verify/.

    POST not GET — this endpoint writes to DB. A GET would risk browser
    prefetch overwriting the secret while the user is scanning the QR code.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if user.is_2fa_enabled:
            return Response(
                {'error': '2FA is already enabled. Disable it first to re-setup.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plain_secret     = pyotp.random_base32()
        user.totp_secret = plain_secret               # setter encrypts automatically
        user.save(update_fields=['_totp_secret_encrypted'])

        totp = pyotp.TOTP(plain_secret)
        uri  = totp.provisioning_uri(name=user.email, issuer_name='Pixel-Mart')

        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(uri)
        qr.make(fit=True)
        img    = qr.make_image(fill_color='black', back_color='white')
        buf    = io.BytesIO()
        img.save(buf, format='PNG')
        qr_b64 = base64.b64encode(buf.getvalue()).decode()

        return Response({
            'secret':    plain_secret,
            'qr_code':   f'data:image/png;base64,{qr_b64}',
            'next_step': 'POST /auth/2fa/verify/ with a valid 6-digit code to activate.',
        })


# ─────────────────────────────────────────────────────────────
#  2FA — Verify and activate
# ─────────────────────────────────────────────────────────────

class TOTPVerifyView(APIView):
    """POST /auth/2fa/verify/ — validates code, activates 2FA."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TOTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user

        if user.is_2fa_enabled:
            return Response(
                {'error': '2FA is already enabled.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        totp = _get_totp_or_500(user)
        if isinstance(totp, Response):
            return totp
        if totp is None:
            return Response(
                {'error': '2FA setup not initiated. Call POST /auth/2fa/setup/ first.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not totp.verify(serializer.validated_data['code'], valid_window=1):
            return Response(
                {'error': 'Invalid code. Please try again.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.is_2fa_enabled = True
        user.save(update_fields=['is_2fa_enabled'])
        return Response({'message': '2FA enabled successfully.'})


# ─────────────────────────────────────────────────────────────
#  2FA — Disable
# ─────────────────────────────────────────────────────────────

class TOTPDisableView(APIView):
    """
    POST /auth/2fa/disable/

    Requires valid TOTP code. Serializer runs FIRST to avoid leaking
    account state through different error paths.
    Vendors blocked if a payout is pending.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if not user.is_2fa_enabled:
            return Response(
                {'error': '2FA is not enabled on this account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = TOTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if user.is_vendor:
            from orders.models import Payout
            if Payout.objects.filter(store__owner=user, status='pending').exists():
                return Response(
                    {'error': 'Cannot disable 2FA while a payout is pending.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        totp = _get_totp_or_500(user)
        if isinstance(totp, Response):
            return totp
        if totp is None:
            return Response(
                {'error': 'Inconsistent 2FA state. Please contact support.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not totp.verify(serializer.validated_data['code'], valid_window=1):
            return Response(
                {'error': 'Invalid code.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.is_2fa_enabled = False
        user.totp_secret    = None
        user.save(update_fields=['is_2fa_enabled', '_totp_secret_encrypted'])

        return Response({'message': '2FA disabled successfully.'})


# ─────────────────────────────────────────────────────────────
#  Account Deletion
# ─────────────────────────────────────────────────────────────

class DeleteAccountView(APIView):
    """
    DELETE /auth/me/delete/

    Soft delete — data retained 30 days then purged by scheduled task.
    Password confirmation required. Vendors blocked with pending payouts.
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        password = request.data.get('password', '')

        if not password:
            return Response(
                {'error': 'Password confirmation is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = request.user

        if not user.check_password(password):
            return Response(
                {'error': 'Invalid password.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if user.is_vendor:
            from orders.models import Payout
            if Payout.objects.filter(
                store__owner=user,
                status__in=['pending', 'processing'],
            ).exists():
                return Response(
                    {'error': 'Cannot delete account while a payout is pending or processing.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        user.deleted_at = timezone.now()
        user.is_active  = False
        user.email      = f'deleted_{user.pk}@deleted.pixelmart.local'
        user.save(update_fields=['deleted_at', 'is_active', 'email'])

        _blacklist_all_tokens_for(user)

        return Response(
            {'message': 'Account scheduled for deletion. You have 30 days to contact support to recover it.'},
            status=status.HTTP_200_OK,
        )


# ─────────────────────────────────────────────────────────────
#  Email Verification
# ─────────────────────────────────────────────────────────────

from common.throttling import VerifyEmailRateThrottle

class VerifyEmailView(APIView):
    """
    POST /auth/verify-email/
    
    Verifies user's email address using the token sent to their inbox.
    Token is single-use and expires after 24 hours.
    Rate limited: 10 requests per minute per IP.
    """
    permission_classes = [AllowAny]
    throttle_classes = [VerifyEmailRateThrottle]

    def post(self, request):
        token = request.data.get('token', '').strip()

        if not token:
            return Response(
                {'error': 'Token is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_id = verify_token(token)
        
        if not user_id:
            return Response(
                {'error': 'Invalid or expired verification token.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if user.is_verified:
            return Response(
                {'message': 'Email already verified. You can log in.'},
                status=status.HTTP_200_OK,
            )

        user.is_verified = True
        user.save(update_fields=['is_verified'])

        # Send welcome email
        send_welcome_email(user.email, user.name)

        return Response(
            {'message': 'Email verified successfully. You can now log in.'},
            status=status.HTTP_200_OK,
        )


class ResendVerificationView(APIView):
    """
    POST /auth/resend-verification/
    
    Resends the verification email to unverified users.
    Rate limited: 1 email per hour per email address.
    """
    permission_classes = [AllowAny]

    RESEND_THROTTLE = 3600  # 1 hour

    def post(self, request):
        email = request.data.get('email', '').strip().lower()

        if not email:
            return Response(
                {'error': 'Email is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Rate limiting check
        throttle_key = f'verification_resend:{email}'
        if cache.get(throttle_key):
            return Response(
                {
                    'error': 'Too many requests. Please try again later.',
                    'retry_after': self.RESEND_THROTTLE,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Don't reveal whether email exists
            return Response(
                {'message': 'If an account exists with this email, a verification link has been sent.'},
                status=status.HTTP_200_OK,
            )

        if user.is_verified:
            return Response(
                {'message': 'Email is already verified. You can log in.'},
                status=status.HTTP_200_OK,
            )

        # Generate new token and send email
        token = generate_verification_token(str(user.pk))
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
        verification_url = f'{frontend_url}/verify-email?token={token}'

        success = send_verification_email(user.email, verification_url, user.name)
        
        if not success:
            return Response(
                {'error': 'Failed to send verification email. Please try again later.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Set throttle
        cache.set(throttle_key, True, timeout=self.RESEND_THROTTLE)

        return Response(
            {'message': 'Verification email sent. Please check your inbox.'},
            status=status.HTTP_200_OK,
        )