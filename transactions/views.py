from rest_framework import viewsets, permissions

from .models import Transaction


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Transaction.objects.filter(store__owner=self.request.user)
