from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Sum, Count, Avg

from .models import Store
from .serializers import StoreSerializer, StoreCreateSerializer, StoreUpdateSerializer
from orders.models import Order
from products.models import Product


class IsStoreOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user


class StoreViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        if self.action == 'list':
            if self.request.user.role == 'admin':
                return Store.objects.all()
            return Store.objects.filter(status='active')
        return Store.objects.filter(owner=self.request.user)
    
    def get_serializer_class(self):
        if self.action == 'create':
            return StoreCreateSerializer
        if self.action in ['update', 'partial_update']:
            return StoreUpdateSerializer
        return StoreSerializer
    
    def perform_create(self, serializer):
        serializer.save()
    
    @action(detail=True, methods=['get'])
    def dashboard(self, request, pk=None):
        store = self.get_object()
        
        period = request.query_params.get('period', 'today')
        
        today = timezone.now()
        if period == 'today':
            start_date = today.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'week':
            start_date = today - timezone.timedelta(days=7)
        elif period == 'month':
            start_date = today - timezone.timedelta(days=30)
        else:
            start_date = today - timezone.timedelta(days=7)
        
        orders = Order.objects.filter(store=store, created_at__gte=start_date)
        
        revenue = orders.aggregate(total=Sum('total_amount'))['total'] or 0
        order_count = orders.count()
        avg_order = revenue / order_count if order_count > 0 else 0
        
        top_products = (
            Order.objects.filter(store=store)
            .values('items__product_id')
            .annotate(total_sold=Sum('items__quantity'))
            .order_by('-total_sold')[:5]
        )
        
        pending_orders = Order.objects.filter(store=store, status='pending').count()
        low_stock_products = Product.objects.filter(
            store=store, 
            track_inventory=True,
            quantity__lte=models.F('low_stock_threshold')
        ).count()
        
        return Response({
            'period': period,
            'revenue': {'value': revenue, 'change_pct': 0},
            'orders': {'value': order_count, 'change_pct': 0},
            'avg_order': {'value': avg_order, 'change_pct': 0},
            'conversion': {'value': 0, 'change_pct': 0},
            'top_products': list(top_products),
            'pending_orders': pending_orders,
            'low_stock_alerts': low_stock_products,
            'balance': {
                'available': store.balance,
                'pending': store.pending_balance
            }
        })
    
    @action(detail=True, methods=['get'])
    def balance(self, request, pk=None):
        store = self.get_object()
        return Response({
            'available': store.balance,
            'pending': store.pending_balance,
            'currency': store.currency
        })


class PublicStoreViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Store.objects.filter(status='active')
    serializer_class = StoreSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'
    
    def get_queryset(self):
        queryset = Store.objects.filter(status='active')
        
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(name__icontains=search)
        
        country = self.request.query_params.get('country')
        if country:
            queryset = queryset.filter(country=country)
        
        is_verified = self.request.query_params.get('is_verified')
        if is_verified:
            queryset = queryset.filter(is_verified=True)
        
        return queryset
