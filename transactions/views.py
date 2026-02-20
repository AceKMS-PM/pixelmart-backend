from rest_framework import viewsets, permissions
from .models import Transaction
from .serializers import TransactionSerializer, TransactionAdminSerializer


class TransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only ledger.
    Vendors: see their own store's transactions (no metadata, no balance_before).
    Admins: see all transactions with full detail.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'role', None) == 'admin':
            return Transaction.objects.select_related('store', 'order').all()
        return Transaction.objects.filter(store__owner=user).select_related('store', 'order')

    def get_serializer_class(self):
        if getattr(self.request.user, 'role', None) == 'admin':
            return TransactionAdminSerializer
        return TransactionSerializer