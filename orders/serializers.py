from rest_framework import serializers
from .models import Order, OrderItem, Coupon, Payout


# ── Order Item ────────────────────────────────────────────────────────────────

class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = [
            'id', 'product', 'variant',
            'title', 'sku', 'image_url',
            'quantity', 'unit_price', 'total_price',
        ]
        read_only_fields = ['id', 'total_price']


# ── Order — customer view ─────────────────────────────────────────────────────

class OrderCustomerSerializer(serializers.ModelSerializer):
    """
    Returned to the customer who placed the order.
    EXCLUDED: commission_amount (internal), payment_reference (sensitive),
              billing_address (invoice endpoint only).
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
        read_only_fields = fields  # customers cannot mutate orders via this serializer


# ── Order — vendor view ───────────────────────────────────────────────────────

class OrderVendorSerializer(serializers.ModelSerializer):
    """
    Returned to the vendor who owns the store.
    Adds: customer name + email (needed for fulfilment), commission_amount.
    EXCLUDED: full billing_address (privacy), payment_reference (no need).
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
    """Full detail for admins — all fields including payment_reference."""
    items = OrderItemSerializer(source='order_items', many=True, read_only=True)

    class Meta:
        model = Order
        fields = '__all__'


# ── Coupon ────────────────────────────────────────────────────────────────────

class CouponSerializer(serializers.ModelSerializer):
    """
    Vendor-facing coupon management.
    used_count is read-only — never client-writable.
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
    Returned to customers on coupon validation.
    EXCLUDED: used_count, max_uses, store internals.
    """
    class Meta:
        model = Coupon
        fields = ['code', 'discount_type', 'value', 'expires_at']


# ── Payout ────────────────────────────────────────────────────────────────────

class PayoutSerializer(serializers.ModelSerializer):
    """
    Vendor-facing payout history.
    EXCLUDED: failure_reason (admin only), external_ref (internal).
    """
    class Meta:
        model = Payout
        fields = [
            'id', 'amount', 'currency', 'method',
            'destination', 'status', 'processed_at', 'created_at',
        ]
        read_only_fields = ['id', 'status', 'processed_at', 'created_at']


class PayoutAdminSerializer(serializers.ModelSerializer):
    """Admin sees everything including failure_reason and external_ref."""
    class Meta:
        model = Payout
        fields = '__all__'