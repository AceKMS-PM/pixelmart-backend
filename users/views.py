from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
import pyotp
import qrcode
import io
import base64

from .models import User
from .serializers import (
    UserSerializer, 
    UserRegistrationSerializer, 
    UserUpdateSerializer,
    ChangePasswordSerializer,
    TOTPSetupSerializer,
    TOTPVerifySerializer
)

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = UserRegistrationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'user': UserSerializer(user).data,
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'message': 'Registration successful. Please verify your email.'
        }, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        
        if not user.check_password(password):
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
        
        if user.is_banned:
            return Response({'error': 'Account suspended'}, status=status.HTTP_403_FORBIDDEN)
        
        if user.is_2fa_enabled:
            return Response({
                'requires_2fa': True,
                'user_id': user.id,
                'message': '2FA code required'
            })
        
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'user': UserSerializer(user).data,
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        })


class Login2FAView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        user_id = request.data.get('user_id')
        code = request.data.get('code')
        
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({'error': 'Invalid user'}, status=status.HTTP_400_BAD_REQUEST)
        
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(code, valid_window=1):
            return Response({'error': 'Invalid 2FA code'}, status=status.HTTP_400_BAD_REQUEST)
        
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'user': UserSerializer(user).data,
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        })


class ProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method == 'PUT' or self.request.method == 'PATCH':
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


class TOTPSetupView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        
        if user.is_2fa_enabled:
            return Response({'error': '2FA already enabled'}, status=status.HTTP_400_BAD_REQUEST)
        
        secret = pyotp.random_base32()
        user.totp_secret = secret
        user.save()
        
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name=user.email, issuer_name='Pixel-Mart')
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(uri)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color='black', back_color='white')
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        qr_code = base64.b64encode(buffer.getvalue()).decode()
        
        return Response({
            'secret': secret,
            'qr_code': f'data:image/png;base64,{qr_code}'
        })


class TOTPVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = TOTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        code = serializer.validated_data['code']
        
        if not user.totp_secret:
            return Response({'error': '2FA not set up'}, status=status.HTTP_400_BAD_REQUEST)
        
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(code, valid_window=1):
            return Response({'error': 'Invalid code'}, status=status.HTTP_400_BAD_REQUEST)
        
        user.is_2fa_enabled = True
        user.save()
        
        return Response({'message': '2FA enabled successfully'})


class TOTPDisableView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        
        code = request.data.get('code')
        if not code:
            return Response({'error': 'Code required'}, status=status.HTTP_400_BAD_REQUEST)
        
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(code, valid_window=1):
            return Response({'error': 'Invalid code'}, status=status.HTTP_400_BAD_REQUEST)
        
        user.is_2fa_enabled = False
        user.totp_secret = None
        user.save()
        
        return Response({'message': '2FA disabled successfully'})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
        except Exception:
            pass
        
        return Response({'message': 'Logged out successfully'})
