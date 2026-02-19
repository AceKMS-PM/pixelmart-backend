from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone

from .models import Order, Coupon, Payout
from stores.models import Store


class OrderViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return Order.objects.all()
        if user.role == 'vendor':
            return Order.objects.filter(store__owner=user)
        return Order.objects.filter(customer=user)


class CouponViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Coupon.objects.filter(store__owner=self.request.user)
    
    def perform_create(self, serializer):
        store_slug = self.request.data.get('store_slug')
        store = Store.objects.get(slug=store_slug, owner=self.request.user)
        serializer.save(store=store)
    
    @action(detail=False, methods=['post'])
    def validate(self, request):
        code = request.data.get('code')
        store_id = request.data.get('store_id')
        cart_total = request.data.get('cart_total', 0)
        
        try:
            coupon = Coupon.objects.get(code=code, store_id=store_id, is_active=True)
        except Coupon.DoesNotExist:
            return Response({'valid': False, 'reason': 'INVALID_CODE'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        
        if coupon.expires_at and coupon.expires_at < timezone.now():
            return Response({'valid': False, 'reason': 'COUPON_EXPIRED'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        
        if coupon.max_uses and coupon.used_count >= coupon.max_uses:
            return Response({'valid': False, 'reason': 'MAX_USES_REACHED'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        
        if coupon.min_order_amount and cart_total < coupon.min_order_amount:
            return Response({'valid': False, 'reason': 'MIN_ORDER_NOT_MET'}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        
        if coupon.discount_type == 'percentage':
            discount_amount = int(cart_total * coupon.value / 100)
        else:
            discount_amount = coupon.value
        
        return Response({
            'valid': True,
            'discount_amount': discount_amount,
            'discount_type': coupon.discount_type,
            'new_total': cart_total - discount_amount
        })


class PayoutViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Payout.objects.filter(store__owner=self.request.user)
