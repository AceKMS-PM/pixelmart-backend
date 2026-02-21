from rest_framework import viewsets, mixins, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound
from django.utils import timezone

from .models import Review, Message, Notification
from .serializers import (
    ReviewPublicSerializer,
    ReviewCreateSerializer,
    ReviewVendorSerializer,
    ReviewAdminSerializer,
    MessageSerializer,
    NotificationSerializer,
)


def _role(user):
    return getattr(user, 'role', 'customer')


# ── Reviews ───────────────────────────────────────────────────────────────────

class ReviewViewSet(viewsets.ModelViewSet):
    """
    GET  /reviews/           → public (published only)
    GET  /reviews/{id}/      → public
    POST /reviews/           → authenticated customer (must have ordered the product)
    PATCH /reviews/{id}/     → vendor (reply only) OR admin (all fields)
    DELETE /reviews/{id}/    → admin only
    """
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        role = _role(user) if user.is_authenticated else None

        if role == 'admin':
            return Review.objects.select_related('customer', 'product', 'store').all()

        if role == 'vendor':
            # Vendors see all reviews on their store (incl. unpublished, for moderation)
            return Review.objects.select_related('customer', 'product', 'store').filter(
                store__owner=user
            )

        # Public / customer: published reviews only
        return Review.objects.select_related('customer', 'product', 'store').filter(
            is_published=True
        )

    def get_serializer_class(self):
        role = _role(self.request.user) if self.request.user.is_authenticated else None
        if role == 'admin':
            return ReviewAdminSerializer
        if role == 'vendor':
            return ReviewVendorSerializer
        if self.action == 'create':
            return ReviewCreateSerializer
        return ReviewPublicSerializer

    def perform_create(self, serializer):
        user = self.request.user
        if _role(user) != 'customer':
            raise PermissionDenied('Only customers can write reviews.')

        # These are UUIDs (now used as PKs directly)
        product_id = self.request.data.get('product')
        order_id = self.request.data.get('order')

        from orders.models import Order, OrderItem
        from products.models import Product

        # Verify the customer actually ordered this product
        if not OrderItem.objects.filter(
            order__customer=user,
            order__id=order_id,
            product__id=product_id,
        ).exists():
            raise ValidationError('You can only review products you have purchased.')

        try:
            product = Product.objects.get(id=product_id)
            order = Order.objects.get(id=order_id, customer=user)
        except Exception:
            raise ValidationError('Invalid product or order.')

        serializer.save(
            customer=user,
            product=product,
            order=order,
            store=product.store,
        )

    def update(self, request, *args, **kwargs):
        review = self.get_object()
        role = _role(request.user)

        if role == 'customer':
            raise PermissionDenied('Customers cannot edit reviews after submission.')

        if role == 'vendor':
            if review.store.owner != request.user:
                raise PermissionDenied('You can only reply to reviews on your own store.')
            allowed_fields = {'vendor_reply'}
            disallowed = set(request.data.keys()) - allowed_fields
            if disallowed:
                raise PermissionDenied(f'Vendors may only set: {allowed_fields}.')
            review.vendor_reply = request.data.get('vendor_reply', review.vendor_reply)
            review.replied_at = timezone.now()
            review.save(update_fields=['vendor_reply', 'replied_at'])
            return Response(ReviewVendorSerializer(review).data)

        # Admin: full update via serializer
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if _role(request.user) != 'admin':
            raise PermissionDenied('Only admins can delete reviews.')
        return super().destroy(request, *args, **kwargs)


# ── Messages ──────────────────────────────────────────────────────────────────

class MessageViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Messages are immutable after sending (no update/delete).
    Sender is always request.user — never from request body.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MessageSerializer
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        if _role(user) == 'admin':
            return Message.objects.select_related('sender', 'receiver').all()
        return Message.objects.filter(
            sender=user
        ).union(
            Message.objects.filter(receiver=user)
        ).order_by('-created_at')

    def perform_create(self, serializer):
        serializer.save(sender=self.request.user)

    @action(detail=True, methods=['post'])
    def mark_read(self, request, id=None):
        message = self.get_object()
        if message.receiver != request.user:
            raise PermissionDenied('You can only mark your own messages as read.')
        if not message.is_read:
            message.is_read = True
            message.read_at = timezone.now()
            message.save(update_fields=['is_read', 'read_at'])
        return Response(MessageSerializer(message).data)


# ── Notifications ─────────────────────────────────────────────────────────────

class NotificationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Notifications are server-generated — clients can only read and mark as read."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = NotificationSerializer
    lookup_field = 'id'

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=True, methods=['post'])
    def mark_read(self, request, id=None):
        notif = self.get_object()
        notif.is_read = True
        notif.save(update_fields=['is_read'])
        return Response(NotificationSerializer(notif).data)

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        self.get_queryset().filter(is_read=False).update(is_read=True)
        return Response({'message': 'All notifications marked as read.'})