from django.db import models
from django.conf import settings
from common.models import TimeStampedModel


class Category(TimeStampedModel):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    icon = models.ImageField(upload_to='category_icons/', null=True, blank=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class Product(TimeStampedModel):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('archived', 'Archived'),
        ('out_of_stock', 'Out of Stock'),
    ]

    store = models.ForeignKey('stores.Store', on_delete=models.CASCADE, related_name='products')
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(max_length=5000)
    short_description = models.CharField(max_length=300, null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    tags = models.JSONField(default=list, blank=True)
    images = models.JSONField(default=list)
    
    price = models.PositiveIntegerField()
    compare_price = models.PositiveIntegerField(null=True, blank=True)
    cost_price = models.PositiveIntegerField(null=True, blank=True)
    
    sku = models.CharField(max_length=100, null=True, blank=True)
    barcode = models.CharField(max_length=50, null=True, blank=True)
    
    track_inventory = models.BooleanField(default=True)
    quantity = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=5)
    
    weight = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    is_digital = models.BooleanField(default=False)
    digital_file = models.FileField(upload_to='digital_products/', null=True, blank=True)
    
    seo_title = models.CharField(max_length=70, null=True, blank=True)
    seo_description = models.CharField(max_length=160, null=True, blank=True)
    
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class ProductVariant(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    store = models.ForeignKey('stores.Store', on_delete=models.CASCADE, related_name='variants')
    
    title = models.CharField(max_length=200)
    options = models.JSONField(default=list)
    
    price = models.PositiveIntegerField(null=True, blank=True)
    compare_price = models.PositiveIntegerField(null=True, blank=True)
    sku = models.CharField(max_length=100, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    
    image = models.ImageField(upload_to='variant_images/', null=True, blank=True)
    weight = models.PositiveIntegerField(null=True, blank=True)
    is_available = models.BooleanField(default=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.product.title} - {self.title}"
