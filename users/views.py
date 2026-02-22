import io
import base64
import secrets

import pyotp
import qrcode

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken, OutstandingToken
from rest_framework_simplejwt.exceptions import TokenError

from common.throttling import LoginRateThrottle, RegisterRateThrottle
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
    Called after password change so stolen sessions can't be reused.
    Requires rest_framework_simplejwt.token_blacklist in INSTALLED_APPS.
    """
    from rest_framework_simplejwt.token_blacklist.models import (
        OutstandingToken, BlacklistedToken
    )
    tokens = OutstandingToken.objects.filter(user=user)
    for token in tokens:
        BlacklistedToken.objects.get_or_create(token=token)


# ─────────────────────────────────────────────────────────────
#  Registration
# ─────────────────────────────────────────────────────────────

class RegisterView(generics.CreateAPIView):
    """
    POST /auth/register/
    Public. role='admin' blocked in UserRegistrationSerializer.validate_role().
    Throttled to 10 requests per minute per IP.
    """
    queryset           = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class   = UserRegistrationSerializer
    throttle_classes   = [RegisterRateThrottle]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user   = serializer.save()
        tokens = _issue_tokens(user)
        return Response(
            {
                'user':    UserSerializer(user).data,
                **tokens,
                'message': 'Registration successful. Please verify your email.',
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
    2. is_banned + is_active checked BEFORE the 2FA branch — blocked users
       never reach the 2FA endpoint.
    3. 2FA challenge returns an opaque pending_token (Redis, 5-min TTL).
       The real user PK is never sent to the client.
    4. Throttled to 5 requests per minute per IP — prevents brute-force.
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

        if user.is_2fa_enabled:
            pending_token = secrets.token_urlsafe(32)
            cache.set(_pending_cache_key(pending_token), user.pk, timeout=300)
            return Response({
                'requires_2fa':  True,
                'pending_token': pending_token,
                # user_id intentionally omitted — never expose DB PKs here
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
    2. Attempt counter uses cache.add() + cache.incr() for atomic increments,
       preventing the race condition where parallel requests both read 0 and
       both get counted as attempt 1.
    3. Max 5 attempts — on lockout both cache keys are destroyed, forcing
       the user to restart from POST /auth/login/.
    4. On success both keys are deleted immediately (one-time-use token).
    5. Missing totp_secret returns the same generic error as an expired token —
       no information about account state leaked.
    6. HTTP 401 (not 400) for bad codes — consistent with RFC 9110.
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

        # ── Atomic attempt counting (fix for race condition) ───
        # cache.add() only sets the key if it doesn't already exist.
        # cache.incr() atomically increments and returns the new value.
        # Together they guarantee we never hand out more than MAX_ATTEMPTS
        # even under concurrent requests.
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

        if not user.totp_secret:
            cache.delete(p_key)
            return Response(
                {'error': 'Invalid or expired token.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(code, valid_window=1):
            # Attempt was already counted above — just return the error
            return Response(
                {'error': 'Invalid 2FA code.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # ── Success — consume both keys immediately ─────────────
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

    Security decisions:
    - Always returns 200, even if no token was provided or already expired.
      Prevents probing whether a token is still valid.
    - TokenError swallowed intentionally.
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
    GET   /auth/me/  → UserSerializer (safe fields only)
    PATCH /auth/me/  → UserUpdateSerializer (name, avatar, phone, locale)

    Security decisions:
    - Email updates are intentionally blocked here — they require re-verification.
      Add a dedicated /auth/me/email/ endpoint with a confirmation flow later.
    - role, is_verified, is_2fa_enabled are read-only in both serializers.
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

    Security decisions:
    - old_password validated in ChangePasswordSerializer.
    - new_password must differ from old (serializer enforces).
    - After a successful change, ALL outstanding refresh tokens for this
      user are blacklisted. This ensures that a stolen refresh token
      (from a breach or a leaked log) cannot be reused after a password reset.
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = ChangePasswordSerializer

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Invalidate all existing sessions — stolen refresh tokens are now dead
        _blacklist_all_tokens_for(request.user)
        return Response({'message': 'Password changed successfully. Please log in again.'})


# ─────────────────────────────────────────────────────────────
#  2FA — Setup
# ─────────────────────────────────────────────────────────────

class TOTPSetupView(APIView):
    """
    POST /auth/2fa/setup/   ← POST, not GET (this endpoint mutates state)

    Generates a new TOTP secret, saves it unactivated, returns the secret
    + a QR code PNG for the authenticator app to scan.

    2FA is activated only after a successful POST to TOTPVerifyView.

    Security decisions:
    - Must be POST, not GET. GET must be idempotent per HTTP spec; this
      endpoint writes totp_secret to the DB on every call. A GET would be
      vulnerable to browser prefetches, proxy caching, and accidental double
      requests overwriting a secret the user is in the middle of scanning.
    - Blocked if 2FA is already fully enabled (must disable first).
    - Repeated POSTs before verify overwrite the previous secret — intentional
      idempotency for the setup flow.
    - secret is returned in plaintext (user needs it for manual app entry).
      TODO: encrypt totp_secret at rest (AES-256, as per spec).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):                     # ← was GET, now POST
        user = request.user

        if user.is_2fa_enabled:
            return Response(
                {'error': '2FA is already enabled. Disable it first to re-setup.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        secret = pyotp.random_base32()
        user.totp_secret = secret
        user.save(update_fields=['totp_secret'])

        totp = pyotp.TOTP(secret)
        uri  = totp.provisioning_uri(name=user.email, issuer_name='Pixel-Mart')

        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(uri)
        qr.make(fit=True)
        img    = qr.make_image(fill_color='black', back_color='white')
        buf    = io.BytesIO()
        img.save(buf, format='PNG')
        qr_b64 = base64.b64encode(buf.getvalue()).decode()

        return Response({
            'secret':    secret,
            'qr_code':   f'data:image/png;base64,{qr_b64}',
            'next_step': 'POST /auth/2fa/verify/ with a valid 6-digit code to activate.',
        })


# ─────────────────────────────────────────────────────────────
#  2FA — Verify and activate
# ─────────────────────────────────────────────────────────────

class TOTPVerifyView(APIView):
    """
    POST /auth/2fa/verify/

    Validates the TOTP code against the pending secret, then activates 2FA.

    Security decisions:
    - Blocked if 2FA is already enabled.
    - Blocked if totp_secret is absent (setup never called).
    - No extra rate-limit: user is fully authenticated (valid JWT), so the
      attack surface is already narrow — they'd have to own the session.
    """
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

        if not user.totp_secret:
            return Response(
                {'error': '2FA setup not initiated. Call POST /auth/2fa/setup/ first.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        totp = pyotp.TOTP(user.totp_secret)
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

    Requires a valid TOTP code to confirm intent — protects against hijacked sessions.

    Security decisions:
    - Input validation (serializer) runs FIRST, before any business logic
      that would reveal account state (payout check, totp_secret check).
      This prevents an attacker from inferring account state from which
      error they receive.
    - Vendors blocked if a payout is pending (spec rule).
    - totp_secret is nulled on success — future setup generates a fresh secret.
    - Inconsistent state (is_2fa_enabled=True, totp_secret=None) returns 500
      rather than silently succeeding — it signals a data integrity issue.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        if not user.is_2fa_enabled:
            return Response(
                {'error': '2FA is not enabled on this account.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Validate input FIRST (before revealing any account state) ──
        serializer = TOTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # ── Business rule: vendor + pending payout ──────────────
        if user.is_vendor:
            from orders.models import Payout
            if Payout.objects.filter(store__owner=user, status='pending').exists():
                return Response(
                    {'error': 'Cannot disable 2FA while a payout is pending.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        # ── Guard: should never happen if is_2fa_enabled is True ─
        if not user.totp_secret:
            return Response(
                {'error': 'Inconsistent 2FA state. Please contact support.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # ── Verify the code ─────────────────────────────────────
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(serializer.validated_data['code'], valid_window=1):
            return Response(
                {'error': 'Invalid code.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.is_2fa_enabled = False
        user.totp_secret     = None
        user.save(update_fields=['is_2fa_enabled', 'totp_secret'])

        return Response({'message': '2FA disabled successfully.'})


# ─────────────────────────────────────────────────────────────
#  Account Deletion
# ─────────────────────────────────────────────────────────────

class DeleteAccountView(APIView):
    """
    DELETE /auth/me/delete/

    Soft delete: sets deleted_at timestamp. Account data is retained for 30 days
    before a cleanup job permanently removes it.

    Security decisions:
    - Requires password confirmation to prevent accidental/malicious deletion
    - Blacklists all outstanding tokens immediately
    - Anonymizes email to prevent re-registration with same email
    - Vendors: rejects if store has pending payouts
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        password = request.data.get('password', '')

        if not password:
            return Response(
                {'error': 'Password confirmation is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not request.user.check_password(password):
            return Response(
                {'error': 'Invalid password.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user = request.user

        if user.role == 'vendor':
            from orders.models import Payout
            if Payout.objects.filter(store__owner=user, status__in=['pending', 'processing']).exists():
                return Response(
                    {'error': 'Cannot delete account while payouts are pending or processing.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        user.deleted_at = timezone.now()
        user.email = f'deleted_{user.id}@deleted.pixelmart.local'
        user.is_active = False
        user.save(update_fields=['deleted_at', 'email', 'is_active'])

        _blacklist_all_tokens_for(user)

        return Response({
            'message': 'Account scheduled for deletion. You have 30 days to contact support to recover your account.',
        })