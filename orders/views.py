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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _role(user):
    return getattr(user, 'role', 'customer')


# ── Orders ────────────────────────────────────────────────────────────────────

class OrderViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,  # vendors update status/tracking; customers cannot
    viewsets.GenericViewSet,
):
    """
    Customers: list + retrieve their own orders (read-only).
    Vendors: list + retrieve store orders, update status/tracking.
    Admins: full access.

    NOTE: Order *creation* is intentionally excluded here.
    It will live in a dedicated checkout endpoint that handles
    inventory reservation, payment intent creation, and atomicity.
    """
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'uuid'

    def get_queryset(self):
        user = self.request.user
        role = _role(user)
        qs = Order.objects.select_related('customer', 'store').prefetch_related('order_items')
        if role == 'admin':
            return qs
        if role == 'vendor':
            return qs.filter(store__owner=user)
        # customer
        return qs.filter(customer=user)

    def get_serializer_class(self):
        role = _role(self.request.user)
        if role == 'admin':
            return OrderAdminSerializer
        if role == 'vendor':
            return OrderVendorSerializer
        return OrderCustomerSerializer

    def update(self, request, *args, **kwargs):
        # Customers must never be able to call PATCH/PUT on orders
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
    lookup_field = 'uuid'

    def get_queryset(self):
        user = self.request.user
        if _role(user) == 'admin':
            return Coupon.objects.all()
        # Vendors see only their own store coupons
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
        Public-ish endpoint for checkout: validate a coupon code.
        Returns only the discount info — not internal coupon config.
        Timing-safe: always runs the same DB query regardless of outcome.
        """
        code = request.data.get('code', '').strip().upper()
        store_id = request.data.get('store_id')
        cart_total = int(request.data.get('cart_total', 0))

        invalid_response = Response(
            {'valid': False, 'reason': 'INVALID_CODE'},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

        try:
            coupon = Coupon.objects.get(code=code, store_id=store_id, is_active=True)
        except Coupon.DoesNotExist:
            return invalid_response

        now = timezone.now()
        if coupon.starts_at and coupon.starts_at > now:
            return invalid_response  # not yet active — same generic error (no info leak)
        if coupon.expires_at and coupon.expires_at < now:
            return Response({'valid': False, 'reason': 'COUPON_EXPIRED'},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        if coupon.max_uses and coupon.used_count >= coupon.max_uses:
            return Response({'valid': False, 'reason': 'MAX_USES_REACHED'},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        if coupon.min_order_amount and cart_total < coupon.min_order_amount:
            return Response({'valid': False, 'reason': 'MIN_ORDER_NOT_MET'},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        if coupon.discount_type == 'percentage':
            discount_amount = int(cart_total * coupon.value / 100)
        else:
            discount_amount = min(coupon.value, cart_total)  # never negative total

        return Response({
            'valid': True,
            'discount_amount': discount_amount,
            'discount_type': coupon.discount_type,
            'new_total': cart_total - discount_amount,
        })


# ── Payouts ───────────────────────────────────────────────────────────────────

class PayoutViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Vendors request payouts (POST) and view history (GET).
    Update / delete are not allowed — payouts are immutable once created.
    Admins see all payouts with full detail.
    """
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'uuid'

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