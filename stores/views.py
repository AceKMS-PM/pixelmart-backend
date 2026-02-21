from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import models  # FIXED: was missing, caused NameError on models.F(...)
from django.db.models import Sum
from django.utils import timezone

from .models import Store
from .serializers import StoreSerializer, StoreCreateSerializer, StoreUpdateSerializer
from orders.models import Order
from products.models import Product


class IsStoreOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user


class StoreViewSet(viewsets.ModelViewSet):
    """Vendor-facing viewset — all operations require ownership."""
    permission_classes = [permissions.IsAuthenticated, IsStoreOwner]
    lookup_field = 'uuid'

    def get_queryset(self):
        # Vendors see only their own stores; admins see all
        user = self.request.user
        if user.role == 'admin':
            return Store.objects.all()
        return Store.objects.filter(owner=user)

    def get_serializer_class(self):
        if self.action == 'create':
            return StoreCreateSerializer
        if self.action in ['update', 'partial_update']:
            return StoreUpdateSerializer
        return StoreSerializer

    def perform_create(self, serializer):
        # Prevent a vendor from owning more than one store
        if Store.objects.filter(owner=self.request.user).exists():
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied('You already own a store.')
        serializer.save()

    # ── Dashboard ─────────────────────────────────────────────────────────────

    @action(detail=True, methods=['get'])
    def dashboard(self, request, pk=None):
        store = self.get_object()  # enforces IsStoreOwner

        period = request.query_params.get('period', 'week')
        today = timezone.now()

        period_map = {
            'today': today.replace(hour=0, minute=0, second=0, microsecond=0),
            'week': today - timezone.timedelta(days=7),
            'month': today - timezone.timedelta(days=30),
        }
        start_date = period_map.get(period, period_map['week'])

        orders = Order.objects.filter(store=store, created_at__gte=start_date)
        revenue = orders.aggregate(total=Sum('total_amount'))['total'] or 0
        order_count = orders.count()
        avg_order = revenue / order_count if order_count else 0

        top_products = list(
            Order.objects.filter(store=store)
            .values('items__product_id')
            .annotate(total_sold=Sum('items__quantity'))
            .order_by('-total_sold')[:5]
        )

        pending_orders = Order.objects.filter(store=store, status='pending').count()

        # FIXED: models.F now resolves correctly (django.db.models imported above)
        low_stock_count = Product.objects.filter(
            store=store,
            track_inventory=True,
            quantity__lte=models.F('low_stock_threshold'),
        ).count()

        return Response({
            'period': period,
            'revenue': {'value': revenue, 'change_pct': 0},
            'orders': {'value': order_count, 'change_pct': 0},
            'avg_order': {'value': round(avg_order, 2), 'change_pct': 0},
            'conversion': {'value': 0, 'change_pct': 0},
            'top_products': top_products,
            'pending_orders': pending_orders,
            'low_stock_alerts': low_stock_count,
            'balance': {
                'available': store.balance,
                'pending': store.pending_balance,
                'currency': store.currency,
            },
        })

    @action(detail=True, methods=['get'])
    def balance(self, request, pk=None):
        store = self.get_object()  # enforces IsStoreOwner
        return Response({
            'available': store.balance,
            'pending': store.pending_balance,
            'currency': store.currency,
        })


class PublicStoreViewSet(viewsets.ReadOnlyModelViewSet):
    """Public read-only store discovery — no financial data exposed."""
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'

    def get_queryset(self):
        return Store.objects.filter(status='active').only(
            'uuid', 'name', 'slug', 'description', 'logo', 'banner',
            'theme_id', 'primary_color', 'subscription_tier',
            'level', 'total_orders', 'avg_rating', 'is_verified',
            'country', 'currency', 'created_at',
        )

    def get_serializer_class(self):
        from .serializers import PublicStoreSerializer
        return PublicStoreSerializer