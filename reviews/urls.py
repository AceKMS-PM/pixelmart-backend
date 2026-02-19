from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ReviewViewSet, MessageViewSet, NotificationViewSet

router = DefaultRouter()
router.register(r'', ReviewViewSet, basename='review')
router.register(r'messages', MessageViewSet, basename='message')
router.register(r'notifications', NotificationViewSet, basename='notification')

urlpatterns = [
    path('', include(router.urls)),
]
