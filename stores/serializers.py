from rest_framework import serializers
from django.utils.text import slugify
from stores.models import Store


class PublicStoreSerializer(serializers.ModelSerializer):
    """Safe read-only serializer — no financial or internal data."""
    owner_name = serializers.CharField(source='owner.name', read_only=True)

    class Meta:
        model = Store
        fields = [
            'id', 'owner_name', 'name', 'slug', 'description',
            'logo', 'banner', 'theme_id', 'primary_color',
            'subscription_tier', 'level', 'total_orders', 'avg_rating',
            'is_verified', 'country', 'currency', 'created_at',
        ]


class StoreSerializer(serializers.ModelSerializer):
    """
    Full serializer for the store owner.
    NOTE: commission_rate is intentionally excluded — it is an internal
    platform rate that vendors do not need to see directly. They see
    their subscription_tier which determines the rate.
    """
    owner_name = serializers.CharField(source='owner.name', read_only=True)

    class Meta:
        model = Store
        fields = [
            'id', 'owner', 'owner_name', 'name', 'slug', 'description',
            'logo', 'banner', 'theme_id', 'primary_color', 'status',
            'subscription_tier', 'subscription_ends_at', 'balance',
            'pending_balance', 'level', 'total_orders', 'avg_rating',
            'is_verified', 'country', 'currency', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'owner', 'slug', 'balance', 'pending_balance',
            'level', 'total_orders', 'avg_rating', 'is_verified',
            'created_at', 'updated_at',
        ]


class StoreAdminSerializer(serializers.ModelSerializer):
    """Admin-only serializer — includes commission_rate and all internal fields."""
    owner_name = serializers.CharField(source='owner.name', read_only=True)

    class Meta:
        model = Store
        fields = [
            'id', 'owner', 'owner_name', 'name', 'slug', 'description',
            'logo', 'banner', 'theme_id', 'primary_color', 'status',
            'subscription_tier', 'subscription_ends_at', 'balance',
            'pending_balance', 'commission_rate', 'level', 'total_orders',
            'avg_rating', 'is_verified', 'country', 'currency',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class StoreCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = ['name', 'description', 'logo', 'banner', 'country', 'currency']

    def create(self, validated_data):
        base_slug = slugify(validated_data['name'])
        slug = base_slug
        for counter in range(1, 1000):
            if not Store.objects.filter(slug=slug).exists():
                break
            slug = f'{base_slug}-{counter}'
        else:
            raise serializers.ValidationError(
                {'name': 'Could not generate a unique slug for this store name.'}
            )

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