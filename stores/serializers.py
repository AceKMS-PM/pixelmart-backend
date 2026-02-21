from rest_framework import serializers
from django.utils.text import slugify
from stores.models import Store


class PublicStoreSerializer(serializers.ModelSerializer):
    """Safe read-only serializer — no financial or internal data."""
    owner_name = serializers.CharField(source='owner.name', read_only=True)

    class Meta:
        model = Store
        fields = [
            'uuid', 'owner_name', 'name', 'slug', 'description',
            'logo', 'banner', 'theme_id', 'primary_color',
            'subscription_tier', 'level', 'total_orders', 'avg_rating',
            'is_verified', 'country', 'currency', 'created_at',
        ]


class StoreSerializer(serializers.ModelSerializer):
    """Full serializer for the store owner — includes financial fields."""
    owner_name = serializers.CharField(source='owner.name', read_only=True)

    class Meta:
        model = Store
        fields = [
            'uuid', 'owner', 'owner_name', 'name', 'slug', 'description',
            'logo', 'banner', 'theme_id', 'primary_color', 'status',
            'subscription_tier', 'subscription_ends_at', 'balance',
            'pending_balance', 'level', 'total_orders', 'avg_rating',
            'is_verified', 'country', 'currency', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'uuid', 'owner', 'slug', 'balance', 'pending_balance',
            'level', 'total_orders', 'avg_rating', 'is_verified',
            'created_at', 'updated_at',
        ]


class StoreCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ['name', 'description', 'logo', 'banner', 'country', 'currency']

    def create(self, validated_data):
        name = validated_data['name']
        base_slug = slugify(name)
        slug = base_slug
        counter = 1
        while Store.objects.filter(slug=slug).exists():
            slug = f'{base_slug}-{counter}'
            counter += 1

        validated_data['slug'] = slug
        validated_data['owner'] = self.context['request'].user
        return super().create(validated_data)


class StoreUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = [
            'name', 'description', 'logo', 'banner',
            'theme_id', 'primary_color', 'country', 'currency',
        ]


class StoreDashboardSerializer(serializers.Serializer):
    period = serializers.CharField()
    revenue = serializers.DictField()
    orders = serializers.DictField()
    avg_order = serializers.DictField()
    conversion = serializers.DictField()
    top_products = serializers.ListField()
    pending_orders = serializers.IntegerField()
    low_stock_alerts = serializers.IntegerField()
    balance = serializers.DictField()