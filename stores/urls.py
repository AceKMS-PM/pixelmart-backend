from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import StoreViewSet, PublicStoreViewSet

router = DefaultRouter()
router.register(r'my', StoreViewSet, basename='my-store')
router.register(r'', PublicStoreViewSet, basename='store')

urlpatterns = [
    path('', include(router.urls)),
]
