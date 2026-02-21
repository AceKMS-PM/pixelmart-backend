from rest_framework import viewsets, mixins, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from .models import Order, Coupon, Payout
from .serializers import (
    OrderCustomerSerializer,
    OrderVendorSerializer,
    OrderAdminSerializer,
    CouponSerializer,
    CouponPublicSerializer,
    PayoutSerializer,
    PayoutAdminSerializer,
)
from stores.models import Store


def _role(user):
    return getattr(user, 'role', 'customer')


# ── Orders ────────────────────────────────────────────────────────────────────

class OrderViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Customers: list + retrieve their own orders (read-only).
    Vendors: list + retrieve store orders, update status/tracking.
    Admins: full access.

    Order creation lives in a separate atomic checkout endpoint
    (payment intent + inventory reserve + order create).
    """
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        role = _role(user)
        qs = Order.objects.select_related('customer', 'store').prefetch_related('order_items')
        if role == 'admin':
            return qs
        if role == 'vendor':
            return qs.filter(store__owner=user)
        return qs.filter(customer=user)

    def get_serializer_class(self):
        role = _role(self.request.user)
        if role == 'admin':
            return OrderAdminSerializer
        if role == 'vendor':
            return OrderVendorSerializer
        return OrderCustomerSerializer

    def update(self, request, *args, **kwargs):
        if _role(request.user) == 'customer':
            raise PermissionDenied('Customers cannot modify orders.')
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if _role(request.user) == 'customer':
            raise PermissionDenied('Customers cannot modify orders.')
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)


# ── Coupons ───────────────────────────────────────────────────────────────────

class CouponViewSet(viewsets.ModelViewSet):
    """Vendor-only — manages coupons for their store."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CouponSerializer
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        if _role(user) == 'admin':
            return Coupon.objects.all()
        return Coupon.objects.filter(store__owner=user)

    def perform_create(self, serializer):
        store_slug = self.request.data.get('store_slug')
        try:
            store = Store.objects.get(slug=store_slug, owner=self.request.user)
        except Store.DoesNotExist:
            raise ValidationError({'store_slug': 'Store not found or you do not own it.'})
        serializer.save(store=store)

    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def validate(self, request):
        """
        Checkout: validate a coupon code and return discount info only.
        Does not expose internal coupon config (used_count, max_uses, etc.).
        """
        code = request.data.get('code', '').strip().upper()
        cart_total = request.data.get('cart_total', 0)
        now = timezone.now()

        try:
            coupon = Coupon.objects.get(code=code, is_active=True)
        except Coupon.DoesNotExist:
            return Response({'error': 'Invalid or inactive coupon.'}, status=status.HTTP_404_NOT_FOUND)

        if coupon.starts_at and coupon.starts_at > now:
            return Response({'error': 'This coupon is not yet active.'}, status=status.HTTP_400_BAD_REQUEST)

        if coupon.expires_at and coupon.expires_at < now:
            return Response({'error': 'This coupon has expired.'}, status=status.HTTP_400_BAD_REQUEST)

        if coupon.max_uses and coupon.used_count >= coupon.max_uses:
            return Response({'error': 'This coupon has reached its usage limit.'}, status=status.HTTP_400_BAD_REQUEST)

        if coupon.min_order_amount and cart_total < coupon.min_order_amount:
            return Response(
                {'error': f'Minimum order amount is {coupon.min_order_amount} cents.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if coupon.discount_type == 'percentage':
            discount_amount = int(cart_total * coupon.value / 100)
        elif coupon.discount_type == 'fixed_amount':
            discount_amount = coupon.value
        else:
            discount_amount = 0

        # Cap discount — never go negative
        discount_amount = min(discount_amount, cart_total)
        new_total = cart_total - discount_amount

        return Response({
            'coupon': CouponPublicSerializer(coupon).data,
            'discount_amount': discount_amount,
            'new_total': new_total,
        })


# ── Payouts ───────────────────────────────────────────────────────────────────

class PayoutViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Vendors create payout requests. Update/delete not allowed — payouts are immutable.
    Admins see all payouts with full detail.
    """
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        if _role(user) == 'admin':
            return Payout.objects.select_related('store', 'initiated_by').all()
        return Payout.objects.filter(store__owner=user)

    def get_serializer_class(self):
        if _role(self.request.user) == 'admin':
            return PayoutAdminSerializer
        return PayoutSerializer

    def perform_create(self, serializer):
        user = self.request.user
        if _role(user) != 'vendor':
            raise PermissionDenied('Only vendors can request payouts.')
        if not user.is_2fa_enabled:
            raise PermissionDenied('2FA must be enabled before requesting a payout.')

        store_slug = self.request.data.get('store_slug')
        try:
            store = Store.objects.get(slug=store_slug, owner=user)
        except Store.DoesNotExist:
            raise ValidationError({'store_slug': 'Store not found or you do not own it.'})

        from django.conf import settings
        min_amount = getattr(settings, 'MIN_PAYOUT_AMOUNT', 100)
        amount = serializer.validated_data.get('amount', 0)
        if amount < min_amount:
            raise ValidationError({'amount': f'Minimum payout is {min_amount} cents.'})
        if store.balance < amount:
            raise ValidationError({'amount': 'Insufficient balance.'})

        serializer.save(store=store, initiated_by=user)