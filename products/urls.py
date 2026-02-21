from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CategoryViewSet, ProductViewSet, ProductVariantViewSet

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'', ProductViewSet, basename='product')

urlpatterns = [
    path('', include(router.urls)),
    path('<slug:product_slug>/variants/', ProductVariantViewSet.as_view({
        'get': 'list', 'post': 'create'
    }), name='product-variants'),
    path('<slug:product_slug>/variants/<uuid:id>/', ProductVariantViewSet.as_view({
        'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'
    }), name='product-variant-detail'),
]
