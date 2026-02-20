from rest_framework import serializers
from .models import Review, Message, Notification
from users.serializers import PublicUserSerializer


# ── Review ────────────────────────────────────────────────────────────────────

class ReviewPublicSerializer(serializers.ModelSerializer):
    """
    Shown publicly on a product page.
    EXCLUDED:
      - `flagged` (internal moderation flag — leaks moderation state)
      - `is_published` (internal)
      - `is_verified` can stay — it's a trust signal customers value
      - `customer` shown as minimal public profile (name + avatar only)
      - `order` ID excluded — customers shouldn't see each other's order IDs
    """
    author = PublicUserSerializer(source='customer', read_only=True)

    class Meta:
        model = Review
        fields = [
            'id', 'author',
            'rating', 'title', 'body', 'images',
            'is_verified',
            'vendor_reply', 'replied_at',
            'created_at',
        ]


class ReviewCreateSerializer(serializers.ModelSerializer):
    """
    Used when a customer POSTs a new review.
    `product`, `order`, `customer`, `store` are injected server-side — never from client.
    `is_published`, `is_verified`, `flagged`, `vendor_reply` are all server-controlled.
    """
    class Meta:
        model = Review
        fields = ['rating', 'title', 'body', 'images']

    def validate_rating(self, value):
        if not (1 <= value <= 5):
            raise serializers.ValidationError('Rating must be between 1 and 5.')
        return value


class ReviewVendorSerializer(serializers.ModelSerializer):
    """
    Vendor replying to a review on their store.
    Can ONLY set vendor_reply. Everything else is read-only.
    """
    author = PublicUserSerializer(source='customer', read_only=True)

    class Meta:
        model = Review
        fields = [
            'id', 'author',
            'rating', 'title', 'body', 'images',
            'is_verified', 'is_published',
            'vendor_reply', 'replied_at',
            'created_at',
        ]
        read_only_fields = [
            'id', 'author', 'rating', 'title', 'body', 'images',
            'is_verified', 'is_published', 'replied_at', 'created_at',
        ]


class ReviewAdminSerializer(serializers.ModelSerializer):
    """Admin sees and can set all fields including flagged, is_published."""
    class Meta:
        model = Review
        fields = '__all__'


# ── Message ───────────────────────────────────────────────────────────────────

class MessageSerializer(serializers.ModelSerializer):
    """
    Inbox / outbox messages.
    `sender` is read-only (injected from request.user in perform_create).
    `is_auto` is server-only — never let clients set it.
    `read_at` is set server-side when the receiver reads.
    """
    sender_name = serializers.CharField(source='sender.name', read_only=True)
    receiver_name = serializers.CharField(source='receiver.name', read_only=True)

    class Meta:
        model = Message
        fields = [
            'id', 'thread_id',
            'sender', 'sender_name',
            'receiver', 'receiver_name',
            'order', 'store',
            'content', 'attachments',
            'is_read', 'read_at',
            'created_at',
        ]
        read_only_fields = [
            'id', 'sender', 'sender_name', 'receiver_name',
            'is_read', 'read_at', 'created_at',
        ]
        # `is_auto` intentionally excluded from all client-facing fields


# ── Notification ──────────────────────────────────────────────────────────────

class NotificationSerializer(serializers.ModelSerializer):
    """
    User notifications — read-only from client perspective.
    EXCLUDED: `channels`, `sent_via` (delivery internals), `metadata` (may contain
    internal IDs from payment providers or webhooks).
    """
    class Meta:
        model = Notification
        fields = [
            'id', 'notification_type',
            'title', 'body', 'link',
            'is_read',
            'created_at',
        ]
        read_only_fields = fields