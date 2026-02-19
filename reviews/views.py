from rest_framework import viewsets, permissions

from .models import Review, Message, Notification


class ReviewViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Review.objects.all()


class MessageViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Message.objects.filter(sender=self.request.user) | Message.objects.filter(receiver=self.request.user)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)
