from django.db import models
from django.conf import settings
from common.models import TimeStampedModel


class Review(TimeStampedModel):
    product = models.ForeignKey('products.Product', on_delete=models.CASCADE, related_name='reviews')
    order = models.ForeignKey('orders.Order', on_delete=models.CASCADE, related_name='reviews')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    store = models.ForeignKey('stores.Store', on_delete=models.CASCADE, related_name='reviews')
    
    rating = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=100, null=True, blank=True)
    body = models.TextField(max_length=2000, null=True, blank=True)
    images = models.JSONField(default=list, blank=True)
    
    is_verified = models.BooleanField(default=True)
    is_published = models.BooleanField(default=False)
    
    vendor_reply = models.TextField(max_length=1000, null=True, blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    flagged = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['product', 'order', 'customer']

    def __str__(self):
        return f"{self.product.title} - {self.rating} stars"


class Message(TimeStampedModel):
    thread_id = models.CharField(max_length=100)
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages')
    receiver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='received_messages')
    
    order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='messages')
    store = models.ForeignKey('stores.Store', on_delete=models.SET_NULL, null=True, blank=True, related_name='messages')
    
    content = models.TextField(max_length=2000)
    attachments = models.JSONField(default=list, blank=True)
    
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    is_auto = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender.email} -> {self.receiver.email}"


class Notification(TimeStampedModel):
    TYPE_CHOICES = [
        ('order_new', 'New Order'),
        ('order_status', 'Order Status'),
        ('low_stock', 'Low Stock'),
        ('payment', 'Payment'),
        ('review', 'Review'),
        ('system', 'System'),
        ('promo', 'Promo'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    title = models.CharField(max_length=100)
    body = models.TextField(max_length=500)
    link = models.URLField(null=True, blank=True)
    
    is_read = models.BooleanField(default=False)
    channels = models.JSONField(default=list)
    sent_via = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} - {self.title}"
