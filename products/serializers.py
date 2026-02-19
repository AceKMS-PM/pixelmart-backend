from rest_framework import serializers
from products.models import Category, Product, ProductVariant
from stores.models import Store


class CategorySerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()
    
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'parent', 'icon', 'sort_order', 'is_active', 'children', 'created_at']
        read_only_fields = ['id', 'slug', 'created_at']
    
    def get_children(self, obj):
        children = obj.children.filter(is_active=True)
        return CategorySerializer(children, many=True).data


class ProductVariantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductVariant
        fields = [
            'id', 'title', 'options', 'price', 'compare_price',
            'sku', 'quantity', 'image', 'weight', 'is_available', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


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
            'variants', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'slug', 'created_at', 'updated_at']


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
            'seo_title', 'seo_description', 'variants'
        ]
    
    def create(self, validated_data):
        from django.utils.text import slugify
        
        variants_data = validated_data.pop('variants', [])
        
        title = validated_data['title']
        slug = slugify(title)
        base_slug = slug
        counter = 1
        
        while Product.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        
        validated_data['slug'] = slug
        
        product = Product.objects.create(**validated_data)
        
        for variant_data in variants_data:
            ProductVariant.objects.create(
                product=product,
                store=validated_data['store'],
                **variant_data
            )
        
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
                    product=instance,
                    store=instance.store,
                    **variant_data
                )
        
        return instance


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
            'status', 'quantity', 'is_digital', 'created_at'
        ]
