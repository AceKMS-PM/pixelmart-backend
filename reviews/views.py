from rest_framework import viewsets, permissions

from .models import Review, Message, Notification


class ReviewViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        # Admins see all; others see only reviews they wrote or reviews for their store products
        if getattr(user, 'role', None) == 'admin':
            return Review.objects.all()
        return Review.objects.filter(
            # reviews the user wrote OR reviews on products in their store
            __import__('django.db.models', fromlist=['Q']).Q(reviewer=user) |
            __import__('django.db.models', fromlist=['Q']).Q(product__store__owner=user)
        ).distinct()

    def perform_create(self, serializer):
        serializer.save(reviewer=self.request.user)


class MessageViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        from django.db.models import Q
        return Message.objects.filter(Q(sender=user) | Q(receiver=user))

    def perform_create(self, serializer):
        serializer.save(sender=self.request.user)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)