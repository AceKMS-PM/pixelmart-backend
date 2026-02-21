import uuid
from django.db import models


class TimeStampedModel(models.Model):
    """
    Abstract base model for all PixelMart models.

    Uses UUID as the primary key so that:
    - Internal row counts are never leaked via sequential integer IDs in URLs
    - Foreign keys throughout the project are automatically UUID-typed
    - No second `uuid` field is needed — one identifier only
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True