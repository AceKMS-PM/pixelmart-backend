from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from common.models import TimeStampedModel
from common.encryption import encrypt, decrypt


class UserManager(BaseUserManager):
    """
    Custom manager — email is the unique identifier, no username.
    """

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user  = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('is_verified', True)
        extra_fields.setdefault('is_active', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """
    Custom user model — email login, no username, role-based access.

    Inheritance:
      AbstractBaseUser  → password hashing, last_login, is_active
      PermissionsMixin  → groups, user_permissions, is_superuser, has_perm()
      TimeStampedModel  → uuid (public API identifier), created_at, updated_at

    No first_name / last_name — single `name` field only.
    No date_joined — created_at from TimeStampedModel serves that purpose.

    TOTP secret:
      Stored encrypted via the `totp_secret` property (Fernet / AES-128-CBC).
      Underlying DB column: totp_secret_encrypted.
      When calling save(update_fields=[...]), use '_totp_secret_encrypted'
      (the real Django field name), never 'totp_secret' (which is a property).

    Email verification (Option B — strict):
      is_verified starts False on registration. No tokens are issued at
      registration. LoginView blocks login until is_verified is True.
      Tokens are issued only after the user clicks the verification link.

    Soft delete:
      deleted_at set on DELETE /auth/me/delete/.
      is_active set False simultaneously to block login immediately.
      A scheduled task purges records where deleted_at < now() - 30 days.
    """

    ROLE_CHOICES = [
        ('admin',    'Admin'),
        ('vendor',   'Vendor'),
        ('customer', 'Customer'),
    ]

    AUTH_PROVIDER_CHOICES = [
        ('email',    'Email'),
        ('google',   'Google'),
        ('facebook', 'Facebook'),
    ]

    # ── Core identity ─────────────────────────────────────────
    email         = models.EmailField(unique=True)
    name          = models.CharField(max_length=255)
    avatar        = models.ImageField(upload_to='avatars/', null=True, blank=True)
    role          = models.CharField(max_length=20, choices=ROLE_CHOICES, default='customer')
    auth_provider = models.CharField(
        max_length=20, choices=AUTH_PROVIDER_CHOICES, default='email'
    )

    # ── Django internals (required by AbstractBaseUser / admin) ──
    is_staff  = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    # ── 2FA ───────────────────────────────────────────────────
    is_2fa_enabled = models.BooleanField(default=False)

    # Fernet-encrypted TOTP secret.
    # Always access via the `totp_secret` property — never this field directly.
    _totp_secret_encrypted = models.TextField(
        db_column='totp_secret_encrypted',
        null=True,
        blank=True,
    )

    # ── Status flags ──────────────────────────────────────────
    is_verified = models.BooleanField(default=False)
    is_banned   = models.BooleanField(default=False)

    # Soft delete — set by DeleteAccountView, cleared by purge job after 30d
    deleted_at = models.DateTimeField(null=True, blank=True)

    # ── Profile metadata ──────────────────────────────────────
    last_login_at = models.DateTimeField(null=True, blank=True)
    locale        = models.CharField(max_length=5, default='fr')
    phone         = models.CharField(max_length=20, null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = ['name']

    class Meta:
        verbose_name        = 'user'
        verbose_name_plural = 'users'
        ordering            = ['-created_at']

    def __str__(self):
        return self.email

    # ── TOTP secret — encrypted property ─────────────────────

    @property
    def totp_secret(self) -> str:
        """
        Decrypt and return the plaintext TOTP secret.
        Returns '' if no secret has been set.
        Raises ValueError if decryption fails (wrong key / corrupted data).
        Callers must catch ValueError and return HTTP 500.
        """
        return decrypt(self._totp_secret_encrypted or '')

    @totp_secret.setter
    def totp_secret(self, value: str | None) -> None:
        """
        Encrypt and store the TOTP secret.
        Pass None to clear it (e.g. on 2FA disable).

        Save afterwards with:
            user.save(update_fields=['_totp_secret_encrypted'])
        """
        self._totp_secret_encrypted = encrypt(value) if value else None

    # ── Convenience role checks ───────────────────────────────

    @property
    def is_vendor(self) -> bool:
        return self.role == 'vendor'

    @property
    def is_customer(self) -> bool:
        return self.role == 'customer'