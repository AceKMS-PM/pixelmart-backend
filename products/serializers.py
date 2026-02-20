from rest_framework import serializers
from django.utils.text import slugify

from products.models import Category, Product, ProductVariant


# ── Shared util ──────────────────────────────────────────────────────────────

def unique_slug(model_class, base_text, slug_field='slug'):
    """Generate a unique slug, appending a counter on collision."""
    slug = slugify(base_text)
    base = slug
    counter = 1
    while model_class.objects.filter(**{slug_field: slug}).exists():
        slug = f'{base}-{counter}'
        counter += 1
    return slug


# ── Category ─────────────────────────────────────────────────────────────────

class CategorySerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'parent', 'icon', 'sort_order', 'is_active', 'children', 'created_at']
        read_only_fields = ['id', 'slug', 'created_at']

    def get_children(self, obj):
        return CategorySerializer(obj.children.filter(is_active=True), many=True).data


# ── Product Variant ───────────────────────────────────────────────────────────

class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = [
            'id', 'title', 'options', 'price', 'compare_price',
            'sku', 'quantity', 'image', 'weight', 'is_available', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


# ── Product (full detail) ─────────────────────────────────────────────────────

class ProductSerializer(serializers.ModelSerializer):
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_slug = serializers.CharField(source='store.slug', read_only=True)
    store_verified = serializers.BooleanField(source='store.is_verified', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'store', 'store_name', 'store_slug', 'store_verified',
            'title', 'slug', 'description', 'short_description',
            'category', 'category_name', 'tags', 'images',
            'price', 'compare_price', 'cost_price',
            'sku', 'barcode', 'track_inventory', 'quantity', 'low_stock_threshold',
            'weight', 'status', 'is_digital', 'digital_file',
            'seo_title', 'seo_description', 'published_at',
            'variants', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'slug', 'created_at', 'updated_at']


# ── Product (list — lighter payload) ─────────────────────────────────────────

class ProductListSerializer(serializers.ModelSerializer):
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


# ── Product Create / Update ───────────────────────────────────────────────────

class ProductCreateSerializer(serializers.ModelSerializer):
    variants = ProductVariantSerializer(many=True, required=False)

    class Meta:
        model = Product
        fields = [
            'title', 'description', 'short_description',
            'category', 'tags', 'images',
            'price', 'compare_price', 'cost_price',
            'sku', 'barcode', 'track_inventory', 'quantity', 'low_stock_threshold',
            'weight', 'status', 'is_digital', 'digital_file',
            'seo_title', 'seo_description', 'variants',
        ]

    def create(self, validated_data):
        variants_data = validated_data.pop('variants', [])
        # 'store' is injected by perform_create, not from client input
        store = validated_data['store']
        validated_data['slug'] = unique_slug(Product, validated_data['title'])

        product = Product.objects.create(**validated_data)

        for variant_data in variants_data:
            ProductVariant.objects.create(product=product, store=store, **variant_data)

        return product

    def update(self, instance, validated_data):
        variants_data = validated_data.pop('variants', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if variants_data is not None:
            instance.variants.all().delete()
            for variant_data in variants_data:
                ProductVariant.objects.create(
                    product=instance, store=instance.store, **variant_data
                )

        return instance