from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    RegisterView, LoginView, Login2FAView, ProfileView,
    ChangePasswordView, TOTPSetupView, TOTPVerifyView,
    TOTPDisableView, LogoutView,
)

urlpatterns = [
    # ── Auth ──────────────────────────────────────────────────
    path('register/',    RegisterView.as_view(),   name='register'),
    path('login/',       LoginView.as_view(),       name='login'),
    path('login/2fa/',   Login2FAView.as_view(),    name='login-2fa'),
    path('logout/',      LogoutView.as_view(),      name='logout'),
    path('refresh/',     TokenRefreshView.as_view(), name='token_refresh'),

    # ── Profile ────────────────────────────────────────────────
    path('me/',          ProfileView.as_view(),     name='profile'),
    path('me/password/', ChangePasswordView.as_view(), name='change-password'),

    # ── 2FA ───────────────────────────────────────────────────
    # All three are POST — setup mutates state (generates + stores secret),
    # so it must not be GET (proxy caching / browser prefetch risk).
    path('2fa/setup/',   TOTPSetupView.as_view(),  name='2fa-setup'),
    path('2fa/verify/',  TOTPVerifyView.as_view(),  name='2fa-verify'),
    path('2fa/disable/', TOTPDisableView.as_view(), name='2fa-disable'),
]