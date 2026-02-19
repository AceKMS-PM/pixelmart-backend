from django.db import models
from django.conf import settings
from common.models import TimeStampedModel


class Store(TimeStampedModel):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('pending', 'Pending'),
        ('closed', 'Closed'),
    ]
    
    SUBSCRIPTION_CHOICES = [
        ('free', 'Free'),
        ('pro', 'Pro'),
        ('business', 'Business'),
    ]
    
    LEVEL_CHOICES = [
        ('bronze', 'Bronze'),
        ('silver', 'Silver'),
        ('gold', 'Gold'),
        ('platinum', 'Platinum'),
    ]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='stores')
    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.TextField(max_length=2000, null=True, blank=True)
    logo = models.ImageField(upload_to='store_logos/', null=True, blank=True)
    banner = models.ImageField(upload_to='store_banners/', null=True, blank=True)
    theme_id = models.CharField(max_length=50, default='default')
    primary_color = models.CharField(max_length=7, null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    subscription_tier = models.CharField(max_length=20, choices=SUBSCRIPTION_CHOICES, default='free')
    subscription_ends_at = models.DateTimeField(null=True, blank=True)
    
    balance = models.PositiveIntegerField(default=0)
    pending_balance = models.PositiveIntegerField(default=0)
    commission_rate = models.PositiveIntegerField(default=500)
    
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default='bronze')
    total_orders = models.PositiveIntegerField(default=0)
    avg_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    is_verified = models.BooleanField(default=False)
    
    country = models.CharField(max_length=2)
    currency = models.CharField(max_length=3, default='EUR')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def calculate_level(self):
        if self.total_orders >= 2000:
            return 'platinum'
        elif self.total_orders >= 500:
            return 'gold'
        elif self.total_orders >= 100:
            return 'silver'
        return 'bronze'
