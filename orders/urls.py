from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrderViewSet, CouponViewSet, PayoutViewSet

router = DefaultRouter()
router.register(r'', OrderViewSet, basename='order')
router.register(r'coupons', CouponViewSet, basename='coupon')
router.register(r'payouts', PayoutViewSet, basename='payout')

urlpatterns = [
    path('', include(router.urls)),
]
