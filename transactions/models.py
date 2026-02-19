from django.db import models
from common.models import TimeStampedModel


class Transaction(TimeStampedModel):
    TYPE_CHOICES = [
        ('sale', 'Sale'),
        ('refund', 'Refund'),
        ('payout', 'Payout'),
        ('fee', 'Fee'),
        ('credit', 'Credit'),
        ('transfer', 'Transfer'),
        ('ad_payment', 'Ad Payment'),
        ('subscription', 'Subscription'),
    ]
    
    DIRECTION_CHOICES = [
        ('credit', 'Credit'),
        ('debit', 'Debit'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('reversed', 'Reversed'),
    ]

    store = models.ForeignKey('stores.Store', on_delete=models.CASCADE, related_name='transactions')
    order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default='EUR')
    
    balance_before = models.PositiveIntegerField()
    balance_after = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    reference = models.CharField(max_length=100, null=True, blank=True)
    description = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.store.name} - {self.transaction_type} - {self.amount}"
