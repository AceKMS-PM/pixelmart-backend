import uuid
from django.db import models
from django.conf import settings
from common.models import TimeStampedModel


class Coupon(TimeStampedModel):
    DISCOUNT_TYPE_CHOICES = [
        ('percentage', 'Percentage'),
        ('fixed_amount', 'Fixed Amount'),
        ('free_shipping', 'Free Shipping'),
    ]

    APPLICABLE_CHOICES = [
        ('all', 'All Products'),
        ('specific_products', 'Specific Products'),
        ('specific_categories', 'Specific Categories'),
    ]

    store = models.ForeignKey('stores.Store', on_delete=models.CASCADE, related_name='coupons')
    code = models.CharField(max_length=20, unique=True)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPE_CHOICES)
    value = models.PositiveIntegerField()
    min_order_amount = models.PositiveIntegerField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    max_uses_per_user = models.PositiveIntegerField(default=1)
    used_count = models.PositiveIntegerField(default=0)
    applicable_to = models.CharField(max_length=20, choices=APPLICABLE_CHOICES, default='all')
    starts_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.code


class Order(TimeStampedModel):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]

    PAYMENT_METHOD_CHOICES = [
        ('stripe_card', 'Stripe Card'),
        ('moneroo_mtn', 'MTN Mobile Money'),
        ('moneroo_orange', 'Orange Money'),
        ('moneroo_wave', 'Wave'),
        ('balance', 'Store Balance'),
    ]

    order_number = models.CharField(max_length=20, unique=True)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders')
    store = models.ForeignKey('stores.Store', on_delete=models.CASCADE, related_name='orders')

    items = models.JSONField(default=list)
    subtotal = models.PositiveIntegerField()
    shipping_amount = models.PositiveIntegerField(default=0)
    discount_amount = models.PositiveIntegerField(default=0)
    total_amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default='EUR')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, null=True)
    payment_reference = models.CharField(max_length=100, null=True, blank=True)

    shipping_address = models.JSONField()
    billing_address = models.JSONField(null=True, blank=True)
    tracking_number = models.CharField(max_length=100, null=True, blank=True)
    carrier = models.CharField(max_length=50, null=True, blank=True)
    estimated_delivery = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(max_length=500, null=True, blank=True)
    coupon = models.ForeignKey(Coupon, on_delete=models.SET_NULL, null=True, blank=True)
    commission_amount = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.order_number


class OrderItem(models.Model):
    # OrderItem n'hérite pas de TimeStampedModel — uuid standalone conservé
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='order_items')
    product = models.ForeignKey('products.Product', on_delete=models.PROTECT)
    variant = models.ForeignKey('products.ProductVariant', on_delete=models.PROTECT, null=True, blank=True)

    title = models.CharField(max_length=200)
    sku = models.CharField(max_length=100, null=True, blank=True)
    image_url = models.URLField(null=True, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.PositiveIntegerField()
    total_price = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.order.order_number} - {self.title}"


class Payout(TimeStampedModel):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    METHOD_CHOICES = [
        ('bank_transfer', 'Bank Transfer'),
        ('mobile_money', 'Mobile Money'),
        ('stripe_connect', 'Stripe Connect'),
    ]

    store = models.ForeignKey('stores.Store', on_delete=models.CASCADE, related_name='payouts')
    amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default='EUR')
    method = models.CharField(max_length=20, choices=METHOD_CHOICES)
    destination = models.JSONField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    processed_at = models.DateTimeField(null=True, blank=True)
    external_ref = models.CharField(max_length=100, null=True, blank=True)
    failure_reason = models.TextField(null=True, blank=True)

    # Lien vers l'écriture de ledger créée atomiquement avec ce payout.
    # SET_NULL car si une Transaction est annulée/supprimée par erreur admin,
    # on veut conserver l'historique du payout (audit trail).
    transaction = models.OneToOneField(
        'transactions.Transaction',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payout',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.store.name} - {self.amount}"