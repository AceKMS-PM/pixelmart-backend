from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound
from django.db.models import Q

from .models import Category, Product, ProductVariant
from .serializers import (
    CategorySerializer,
    ProductSerializer,
    ProductPublicSerializer,
    ProductCreateSerializer,
    ProductListSerializer,
    ProductVariantSerializer,
    ProductVariantPublicSerializer,
)


def _is_owner(user, product):
    return user.is_authenticated and product.store.owner == user


def _role(user):
    return getattr(user, 'role', None) if user.is_authenticated else None


# ── Category ──────────────────────────────────────────────────────────────────

class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'slug'

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAdminUser()]
        return super().get_permissions()


# ── Products ──────────────────────────────────────────────────────────────────

class IsProductOwner(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.user.is_authenticated and obj.store.owner == request.user


class ProductViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsProductOwner]
    lookup_field = 'slug'

    def get_queryset(self):
        queryset = Product.objects.select_related('store', 'category').prefetch_related('variants')
        user = self.request.user

        if self.action == 'list':
            queryset = queryset.filter(status='active')

            params = self.request.query_params
            if category := params.get('category'):
                queryset = queryset.filter(category__slug=category)
            if store := params.get('store'):
                queryset = queryset.filter(store__slug=store)
            if search := params.get('search'):
                queryset = queryset.filter(
                    Q(title__icontains=search) | Q(short_description__icontains=search)
                )

            order_map = {
                'recent': '-created_at',
                'price_asc': 'price',
                'price_desc': '-price',
                'bestseller': '-store__total_orders',
                'rating': '-store__avg_rating',
            }
            ordering = params.get('ordering', 'recent')
            queryset = queryset.order_by(order_map.get(ordering, '-created_at'))

        else:
            # Non-list actions: guard anonymous
            if not user.is_authenticated:
                return Product.objects.none()
            if _role(user) != 'admin':
                queryset = queryset.filter(store__owner=user)

        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer

        if self.action in ['create', 'update', 'partial_update']:
            return ProductCreateSerializer

        # Detail view: show cost_price etc. only to the owner or admin
        user = self.request.user
        if user.is_authenticated and _role(user) in ('admin', 'vendor'):
            return ProductSerializer

        return ProductPublicSerializer  # anonymous / customers never see cost_price

    def perform_create(self, serializer):
        from stores.models import Store
        store_slug = self.request.data.get('store_slug')
        try:
            store = Store.objects.get(slug=store_slug, owner=self.request.user)
        except Store.DoesNotExist:
            raise ValidationError({'store_slug': 'Store not found or you do not own it.'})
        serializer.save(store=store)

    @action(detail=True, methods=['post'])
    def duplicate(self, request, slug=None):
        product = self.get_object()  # IsProductOwner enforces ownership

        import copy
        new_product = copy.copy(product)
        new_product.pk = None
        new_product.slug = f'{product.slug}-copy'
        new_product.status = 'draft'
        new_product.save()

        for variant in product.variants.all():
            new_variant = copy.copy(variant)
            new_variant.pk = None
            new_variant.product = new_product
            new_variant.save()

        return Response(ProductSerializer(new_product).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['patch'])
    def inventory(self, request, slug=None):
        product = self.get_object()  # IsProductOwner enforces ownership
        quantity = request.data.get('quantity')
        if quantity is None:
            raise ValidationError({'quantity': 'This field is required.'})
        if not isinstance(quantity, int) or quantity < 0:
            raise ValidationError({'quantity': 'Must be a non-negative integer.'})
        product.quantity = quantity
        product.save(update_fields=['quantity'])
        return Response(ProductSerializer(product).data)


# ── Product Variants ──────────────────────────────────────────────────────────

class ProductVariantViewSet(viewsets.ModelViewSet):
    """
    Nested under /products/{product_slug}/variants/.
    Read: public sees price/availability only.
    Write: owner only.
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def _get_product(self):
        try:
            return Product.objects.get(slug=self.kwargs['product_slug'])
        except Product.DoesNotExist:
            raise NotFound('Product not found.')

    def get_queryset(self):
        product = self._get_product()
        return ProductVariant.objects.filter(product=product)

    def get_serializer_class(self):
        user = self.request.user
        if user.is_authenticated and _role(user) in ('admin', 'vendor'):
            return ProductVariantSerializer
        return ProductVariantPublicSerializer

    def perform_create(self, serializer):
        from stores.models import Store
        product = self._get_product()
        if product.store.owner != self.request.user:
            raise PermissionDenied('You can only add variants to your own products.')
        serializer.save(product=product, store=product.store)

    def get_object(self):
        obj = super().get_object()
        # For write actions, enforce ownership
        if self.request.method not in permissions.SAFE_METHODS:
            if not self.request.user.is_authenticated or obj.product.store.owner != self.request.user:
                raise PermissionDenied('You can only modify variants of your own products.')
        return obj