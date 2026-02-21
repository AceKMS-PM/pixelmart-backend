from rest_framework import serializers
from django.utils.text import slugify

from products.models import Category, Product, ProductVariant


# ── Shared util ──────────────────────────────────────────────────────────────

def unique_slug(model_class, base_text, slug_field='slug', max_attempts=999):
    """
    Generate a unique slug, appending a counter on collision.
    Raises ValueError if a unique slug cannot be found within max_attempts.
    """
    slug = base = slugify(base_text)
    for counter in range(1, max_attempts + 1):
        if not model_class.objects.filter(**{slug_field: slug}).exists():
            return slug
        slug = f'{base}-{counter}'
    raise ValueError(f"Could not generate a unique slug for '{base_text}'")


# ── Category ─────────────────────────────────────────────────────────────────

class CategorySerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'parent', 'icon', 'sort_order', 'is_active', 'children', 'created_at']
        read_only_fields = ['id', 'slug', 'created_at']

    def get_children(self, obj):
        # Hard limit at depth 2 — prevents runaway recursion on bad data
        if self.context.get('depth', 0) >= 2:
            return []
        child_context = {**self.context, 'depth': self.context.get('depth', 0) + 1}
        return CategorySerializer(
            obj.children.filter(is_active=True),
            many=True,
            context=child_context,
        ).data


# ── Variant — public ──────────────────────────────────────────────────────────

class ProductVariantPublicSerializer(serializers.ModelSerializer):
    """
    Shown on public product pages.
    EXCLUDED: `sku` (internal inventory code), `weight` (fulfillment internal).
    """
    class Meta:
        model = ProductVariant
        fields = [
            'id', 'title', 'options',
            'price', 'compare_price',
            'quantity', 'image', 'is_available',
        ]


class ProductVariantSerializer(serializers.ModelSerializer):
    """Full variant for vendor / admin — includes sku, weight."""
    class Meta:
        model = ProductVariant
        fields = [
            'id', 'title', 'options', 'price', 'compare_price',
            'sku', 'quantity', 'image', 'weight', 'is_available', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


# ── Product — public list (lightest payload) ──────────────────────────────────

class ProductListSerializer(serializers.ModelSerializer):
    """
    Card view on the marketplace.
    EXCLUDED: description, cost_price, seo_* fields, digital_file, barcode, sku,
              weight, track_inventory.
    """
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_slug = serializers.CharField(source='store.slug', read_only=True)
    store_verified = serializers.BooleanField(source='store.is_verified', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'title', 'slug', 'short_description',
            'store_name', 'store_slug', 'store_verified',
            'category_name', 'images', 'price', 'compare_price',
            'status', 'quantity', 'is_digital', 'created_at',
        ]


# ── Product — public detail ───────────────────────────────────────────────────

class ProductPublicSerializer(serializers.ModelSerializer):
    """
    Full product page for anonymous/customer.
    EXCLUDED:
      - `cost_price` (vendor margin — must never be public)
      - `sku`, `barcode` (internal inventory)
      - `track_inventory`, `low_stock_threshold` (internal ops)
      - `seo_title`, `seo_description` (rendered server-side by Next.js)
      - `digital_file` (served via signed URL endpoint, not directly)
    """
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_slug = serializers.CharField(source='store.slug', read_only=True)
    store_verified = serializers.BooleanField(source='store.is_verified', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    variants = ProductVariantPublicSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'store', 'store_name', 'store_slug', 'store_verified',
            'title', 'slug', 'description', 'short_description',
            'category', 'category_name', 'tags', 'images',
            'price', 'compare_price',
            'quantity', 'weight',
            'status', 'is_digital',
            'published_at', 'variants',
            'created_at',
        ]


# ── Product — vendor / admin detail ──────────────────────────────────────────

class ProductSerializer(serializers.ModelSerializer):
    """
    Full detail for the store owner — includes cost_price, sku, inventory fields.
    """
    store_name = serializers.CharField(source='store.name', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'store', 'store_name', 'title', 'slug', 'description',
            'short_description', 'category', 'category_name', 'tags', 'images',
            'price', 'compare_price', 'cost_price',
            'sku', 'barcode', 'track_inventory', 'quantity', 'low_stock_threshold',
            'weight', 'status', 'is_digital', 'digital_file',
            'seo_title', 'seo_description', 'published_at',
            'variants', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'slug', 'store', 'created_at', 'updated_at']


# ── Product — create / update ─────────────────────────────────────────────────

class ProductCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = [
            'title', 'description', 'short_description', 'category', 'tags',
            'images', 'price', 'compare_price', 'cost_price',
            'sku', 'barcode', 'track_inventory', 'quantity', 'low_stock_threshold',
            'weight', 'status', 'is_digital', 'digital_file',
            'seo_title', 'seo_description',
        ]

    def create(self, validated_data):
        validated_data['store'] = self.context['request'].user.stores.get()
        validated_data['slug'] = unique_slug(Product, validated_data['title'])
        return super().create(validated_data)