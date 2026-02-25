from rest_framework import serializers
from .models import Order, OrderItem, Coupon, Payout


# ── Order Item ────────────────────────────────────────────────────────────────

class OrderItemSerializer(serializers.ModelSerializer):
    # OrderItem n'hérite pas de TimeStampedModel — champ uuid standalone conservé
    class Meta:
        model = OrderItem
        fields = [
            'uuid', 'product', 'variant',
            'title', 'sku', 'image_url',
            'quantity', 'unit_price', 'total_price',
        ]
        read_only_fields = ['uuid', 'total_price']


# ── Order — customer view ─────────────────────────────────────────────────────

class OrderCustomerSerializer(serializers.ModelSerializer):
    """
    Retourné au client ayant passé la commande.
    EXCLU : commission_amount (interne), payment_reference (sensible),
            billing_address (endpoint facture uniquement).
    """
    items = OrderItemSerializer(source='order_items', many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'status', 'payment_status', 'payment_method',
            'items',
            'subtotal', 'shipping_amount', 'discount_amount', 'total_amount', 'currency',
            'shipping_address',
            'tracking_number', 'carrier', 'estimated_delivery', 'delivered_at',
            'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = fields


# ── Order — vendor view ───────────────────────────────────────────────────────

class OrderVendorSerializer(serializers.ModelSerializer):
    """
    Retourné au vendeur propriétaire de la boutique.
    Ajoute : nom + email client (nécessaire pour l'expédition), commission_amount.
    EXCLU : billing_address (vie privée), payment_reference (inutile côté vendor).
    """
    customer_name = serializers.CharField(source='customer.name', read_only=True)
    customer_email = serializers.EmailField(source='customer.email', read_only=True)
    items = OrderItemSerializer(source='order_items', many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'order_number',
            'customer_name', 'customer_email',
            'status', 'payment_status', 'payment_method',
            'items',
            'subtotal', 'shipping_amount', 'discount_amount',
            'total_amount', 'commission_amount', 'currency',
            'shipping_address',
            'tracking_number', 'carrier', 'estimated_delivery', 'delivered_at',
            'notes', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'order_number', 'customer_name', 'customer_email',
            'payment_status', 'payment_method',
            'subtotal', 'shipping_amount', 'discount_amount',
            'total_amount', 'commission_amount', 'currency',
            'created_at',
        ]


# ── Order — admin view ────────────────────────────────────────────────────────

class OrderAdminSerializer(serializers.ModelSerializer):
    """Admin — tous les champs dont payment_reference."""
    items = OrderItemSerializer(source='order_items', many=True, read_only=True)

    class Meta:
        model = Order
        fields = '__all__'


# ── Coupon ────────────────────────────────────────────────────────────────────

class CouponSerializer(serializers.ModelSerializer):
    """
    Gestion vendor des coupons.
    used_count est read-only — jamais modifiable par le client.
    """
    class Meta:
        model = Coupon
        fields = [
            'id', 'code', 'discount_type', 'value',
            'min_order_amount', 'max_uses', 'max_uses_per_user', 'used_count',
            'applicable_to', 'starts_at', 'expires_at', 'is_active',
            'created_at',
        ]
        read_only_fields = ['id', 'used_count', 'created_at']


class CouponPublicSerializer(serializers.ModelSerializer):
    """
    Retourné au client lors de la validation d'un coupon.
    EXCLU : used_count, max_uses, config interne boutique.
    """
    class Meta:
        model = Coupon
        fields = ['code', 'discount_type', 'value', 'expires_at']


# ── Payout ────────────────────────────────────────────────────────────────────

class PayoutSerializer(serializers.ModelSerializer):
    """
    Historique des virements côté vendor.
    EXCLU : failure_reason (admin only), external_ref (interne).
    transaction_id exposé en lecture seule — permet au vendor de croiser
    avec son historique de transactions si besoin.
    """
    transaction_id = serializers.PrimaryKeyRelatedField(
        source='transaction', read_only=True
    )

    class Meta:
        model = Payout
        fields = [
            'id', 'amount', 'currency', 'method',
            'destination', 'status',
            'transaction_id',
            'processed_at', 'created_at',
        ]
        read_only_fields = ['id', 'status', 'transaction_id', 'processed_at', 'created_at']


class PayoutAdminSerializer(serializers.ModelSerializer):
    """Admin — tous les champs dont failure_reason, external_ref et transaction."""
    class Meta:
        model = Payout
        fields = '__all__'