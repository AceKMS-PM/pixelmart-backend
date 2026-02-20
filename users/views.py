from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.core.cache import cache
import pyotp
import qrcode
import io
import base64

from .serializers import (
    UserSerializer,
    UserRegistrationSerializer,
    UserUpdateSerializer,
    ChangePasswordSerializer,
    TOTPVerifySerializer,
)

User = get_user_model()

# ── helpers ──────────────────────────────────────────────────────────────────

def _issue_tokens(user):
    refresh = RefreshToken.for_user(user)
    return {'refresh': str(refresh), 'access': str(refresh.access_token)}


def _2fa_attempt_key(user_id):
    return f'2fa_attempts:{user_id}'


# ── Auth views ────────────────────────────────────────────────────────────────

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = UserRegistrationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        tokens = _issue_tokens(user)
        return Response(
            {'user': UserSerializer(user).data, **tokens,
             'message': 'Registration successful. Please verify your email.'},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '')

        # Single generic error to avoid user-enumeration
        invalid = Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return invalid

        if not user.check_password(password):
            return invalid

        if user.is_banned:
            return Response({'error': 'Account suspended'}, status=status.HTTP_403_FORBIDDEN)

        if user.is_2fa_enabled:
            # Store a signed, short-lived token in cache instead of exposing user_id
            import secrets
            pending_key = secrets.token_urlsafe(32)
            cache.set(f'2fa_pending:{pending_key}', user.pk, timeout=300)  # 5 min TTL
            return Response({
                'requires_2fa': True,
                'pending_token': pending_key,
                'message': '2FA code required',
            })

        tokens = _issue_tokens(user)
        return Response({'user': UserSerializer(user).data, **tokens})


class Login2FAView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        pending_token = request.data.get('pending_token', '')
        code = request.data.get('code', '')

        if not pending_token or not code:
            return Response({'error': 'pending_token and code are required'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Resolve the pending token
        cache_key = f'2fa_pending:{pending_token}'
        user_id = cache.get(cache_key)
        if not user_id:
            return Response({'error': 'Invalid or expired token'},
                            status=status.HTTP_400_BAD_REQUEST)

        # Rate-limit: max 5 attempts per pending session
        attempts_key = _2fa_attempt_key(pending_token)
        attempts = cache.get(attempts_key, 0)
        if attempts >= 5:
            cache.delete(cache_key)
            return Response({'error': 'Too many attempts. Please log in again.'},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)

        if not user.totp_secret:
            return Response({'error': 'Invalid token'}, status=status.HTTP_400_BAD_REQUEST)

        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(code, valid_window=1):
            cache.set(attempts_key, attempts + 1, timeout=300)
            return Response({'error': 'Invalid 2FA code'}, status=status.HTTP_400_BAD_REQUEST)

        # Success — consume the pending token
        cache.delete(cache_key)
        cache.delete(attempts_key)

        tokens = _issue_tokens(user)
        return Response({'user': UserSerializer(user).data, **tokens})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except Exception:
                pass
        return Response({'message': 'Logged out successfully'})


# ── Profile ───────────────────────────────────────────────────────────────────

class ProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return UserUpdateSerializer
        return UserSerializer


class ChangePasswordView(generics.UpdateAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'message': 'Password changed successfully'})


# ── 2FA management ───────────────────────────────────────────────────────────

class TOTPSetupView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user.is_2fa_enabled:
            return Response({'error': '2FA already enabled'}, status=status.HTTP_400_BAD_REQUEST)

        secret = pyotp.random_base32()
        # Store temporarily; only persisted after verification
        user.totp_secret = secret
        user.save(update_fields=['totp_secret'])

        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name=user.email, issuer_name='Pixel-Mart')

        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        qr_b64 = base64.b64encode(buffer.getvalue()).decode()

        return Response({'secret': secret, 'qr_code': f'data:image/png;base64,{qr_b64}'})


class TOTPVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TOTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        if not user.totp_secret:
            return Response({'error': '2FA not set up'}, status=status.HTTP_400_BAD_REQUEST)

        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(serializer.validated_data['code'], valid_window=1):
            return Response({'error': 'Invalid code'}, status=status.HTTP_400_BAD_REQUEST)

        user.is_2fa_enabled = True
        user.save(update_fields=['is_2fa_enabled'])
        return Response({'message': '2FA enabled successfully'})


class TOTPDisableView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        code = request.data.get('code', '')
        if not code:
            return Response({'error': 'Code required'}, status=status.HTTP_400_BAD_REQUEST)

        if not user.totp_secret:
            return Response({'error': '2FA not active'}, status=status.HTTP_400_BAD_REQUEST)

        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(code, valid_window=1):
            return Response({'error': 'Invalid code'}, status=status.HTTP_400_BAD_REQUEST)

        user.is_2fa_enabled = False
        user.totp_secret = None
        user.save(update_fields=['is_2fa_enabled', 'totp_secret'])
        return Response({'message': '2FA disabled successfully'})