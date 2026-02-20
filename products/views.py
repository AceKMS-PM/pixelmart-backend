from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q

from .models import Category, Product, ProductVariant
from .serializers import (
    CategorySerializer,
    ProductSerializer,
    ProductCreateSerializer,
    ProductListSerializer,
    ProductVariantSerializer,
)


class IsProductOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_authenticated and obj.store.owner == request.user


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'slug'

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAdminUser()]
        return super().get_permissions()


class ProductViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsProductOwner]
    lookup_field = 'slug'

    def get_queryset(self):
        queryset = Product.objects.select_related('store', 'category').prefetch_related('variants')
        user = self.request.user

        if self.action == 'list':
            # Public listing: only active products
            queryset = queryset.filter(status='active')

            # Apply optional filters
            params = self.request.query_params
            if category := params.get('category'):
                queryset = queryset.filter(category__slug=category)
            if store := params.get('store'):
                queryset = queryset.filter(store__slug=store)
            if search := params.get('search'):
                queryset = queryset.filter(
                    Q(title__icontains=search) | Q(short_description__icontains=search)
                )

            # Ordering
            ordering = params.get('ordering', 'recent')
            order_map = {
                'recent': '-created_at',
                'price_asc': 'price',
                'price_desc': '-price',
                'bestseller': '-store__total_orders',
                'rating': '-store__avg_rating',
            }
            queryset = queryset.order_by(order_map.get(ordering, '-created_at'))

        else:
            # Write / detail actions: FIXED — safe guard for AnonymousUser
            if not user.is_authenticated:
                return Product.objects.none()
            if getattr(user, 'role', None) == 'admin':
                pass  # admin sees all
            else:
                queryset = queryset.filter(store__owner=user)

        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        if self.action in ['create', 'update', 'partial_update']:
            return ProductCreateSerializer
        return ProductSerializer

    def perform_create(self, serializer):
        from stores.models import Store
        store_slug = self.request.data.get('store_slug')
        try:
            store = Store.objects.get(slug=store_slug, owner=self.request.user)
        except Store.DoesNotExist:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'store_slug': 'Store not found or you do not own it.'})
        serializer.save(store=store)

    def perform_update(self, serializer):
        serializer.save()

    @action(detail=True, methods=['post'])
    def duplicate(self, request, slug=None):
        product = self.get_object()

        new_product = Product.objects.get(pk=product.pk)
        new_product.pk = None
        new_product.slug = f'{product.slug}-copy'
        new_product.status = 'draft'
        new_product.save()

        for variant in product.variants.all():
            new_variant = ProductVariant.objects.get(pk=variant.pk)
            new_variant.pk = None
            new_variant.product = new_product
            new_variant.save()

        return Response(ProductSerializer(new_product).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch'])
    def inventory(self, request, slug=None):
        product = self.get_object()
        quantity = request.data.get('quantity')
        if quantity is not None:
            product.quantity = quantity
            product.save(update_fields=['quantity'])
        return Response(ProductSerializer(product).data)


class ProductVariantViewSet(viewsets.ModelViewSet):
    serializer_class = ProductVariantSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ProductVariant.objects.filter(
            store__owner=self.request.user,
            product__slug=self.kwargs['product_slug'],
        )

    def perform_create(self, serializer):
        from stores.models import Store
        product = Product.objects.get(slug=self.kwargs['product_slug'])
        store = Store.objects.get(owner=self.request.user, id=product.store_id)
        serializer.save(product=product, store=store)