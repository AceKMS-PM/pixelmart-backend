from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from django.db.models import Q

from .models import Category, Product, ProductVariant
from .serializers import (
    CategorySerializer, 
    ProductSerializer, 
    ProductCreateSerializer,
    ProductListSerializer,
    ProductVariantSerializer
)


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'slug'
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAdminUser()]
        return super().get_permissions()


class IsProductOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return obj.store.owner == request.user


class ProductViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'slug'
    
    def get_queryset(self):
        queryset = Product.objects.select_related('store', 'category').prefetch_related('variants')
        
        if self.action == 'list':
            queryset = queryset.filter(status='active')
        elif self.request.user.role != 'admin':
            queryset = queryset.filter(store__owner=self.request.user)
        
        search = self.request.query_params.get('q')
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | 
                Q(description__icontains=search) |
                Q(tags__contains=[search])
            )
        
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category__slug=category)
        
        store_slug = self.request.query_params.get('store')
        if store_slug:
            queryset = queryset.filter(store__slug=store_slug)
        
        min_price = self.request.query_params.get('min_price')
        if min_price:
            queryset = queryset.filter(price__gte=int(min_price))
        
        max_price = self.request.query_params.get('max_price')
        if max_price:
            queryset = queryset.filter(price__lte=int(max_price))
        
        in_stock = self.request.query_params.get('in_stock')
        if in_stock == 'true':
            queryset = queryset.filter(
                Q(track_inventory=False) | Q(quantity__gt=0)
            )
        
        ordering = self.request.query_params.get('sort', '-created_at')
        if ordering == 'price_asc':
            queryset = queryset.order_by('price')
        elif ordering == 'price_desc':
            queryset = queryset.order_by('-price')
        elif ordering == 'newest':
            queryset = queryset.order_by('-created_at')
        elif ordering == 'bestseller':
            queryset = queryset.order_by('-store__total_orders')
        elif ordering == 'rating':
            queryset = queryset.order_by('-store__avg_rating')
        else:
            queryset = queryset.order_by('-created_at')
        
        return queryset
    
    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        if self.action in ['create', 'update', 'partial_update']:
            return ProductCreateSerializer
        return ProductSerializer
    
    def perform_create(self, serializer):
        store_slug = self.request.data.get('store_slug')
        from stores.models import Store
        store = Store.objects.get(slug=store_slug, owner=self.request.user)
        serializer.save(store=store)
    
    def perform_update(self, serializer):
        serializer.save()
    
    @action(detail=True, methods=['post'])
    def duplicate(self, request, slug=None):
        product = self.get_object()
        
        if product.store.owner != request.user:
            return Response(
                {'error': 'You can only duplicate your own products'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        new_product = Product.objects.get(pk=product.pk)
        new_product.pk = None
        new_product.slug = f"{product.slug}-copy"
        new_product.status = 'draft'
        new_product.save()
        
        for variant in product.variants.all():
            new_variant = ProductVariant.objects.get(pk=variant.pk)
            new_variant.pk = None
            new_variant.product = new_product
            new_variant.save()
        
        return Response(
            ProductSerializer(new_product).data,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=True, methods=['patch'])
    def inventory(self, request, slug=None):
        product = self.get_object()
        
        if product.store.owner != request.user:
            return Response(
                {'error': 'You can only update your own products'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        quantity = request.data.get('quantity')
        if quantity is not None:
            product.quantity = quantity
            product.save()
        
        return Response(ProductSerializer(product).data)


class ProductVariantViewSet(viewsets.ModelViewSet):
    serializer_class = ProductVariantSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return ProductVariant.objects.filter(
            store__owner=self.request.user,
            product__slug=self.kwargs['product_slug']
        )
    
    def perform_create(self, serializer):
        from stores.models import Store
        product = Product.objects.get(slug=self.kwargs['product_slug'])
        store = Store.objects.get(owner=self.request.user, id=product.store.id)
        serializer.save(product=product, store=store)
