from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from common.models import TimeStampedModel


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('is_verified', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser, TimeStampedModel):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('vendor', 'Vendor'),
        ('customer', 'Customer'),
    ]
    
    AUTH_PROVIDER_CHOICES = [
        ('email', 'Email'),
        ('google', 'Google'),
        ('facebook', 'Facebook'),
    ]
    
    username = None
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='customer')
    auth_provider = models.CharField(max_length=20, choices=AUTH_PROVIDER_CHOICES, default='email')
    
    is_2fa_enabled = models.BooleanField(default=False)
    totp_secret = models.CharField(max_length=255, null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    is_banned = models.BooleanField(default=False)
    
    last_login_at = models.DateTimeField(null=True, blank=True)
    locale = models.CharField(max_length=5, default='fr')
    phone = models.CharField(max_length=20, null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    def __str__(self):
        return self.email

    @property
    def is_vendor(self):
        return self.role == 'vendor'

    @property
    def is_customer(self):
        return self.role == 'customer'
