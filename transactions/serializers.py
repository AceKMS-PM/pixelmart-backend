from rest_framework import serializers
from .models import Transaction


class TransactionSerializer(serializers.ModelSerializer):
    """
    Vendor-facing transaction history.
    EXCLUDED:
      - metadata (may contain internal payment processor data, webhook IDs)
      - balance_before (balance_after is sufficient; before can be inferred)
      - reference is kept — vendors may need it for support disputes
    """
    class Meta:
        model = Transaction
        fields = [
            'id',
            'transaction_type', 'direction',
            'amount', 'currency',
            'balance_after',
            'status',
            'reference', 'description',
            'processed_at', 'created_at',
        ]
        read_only_fields = fields  # ledger is always read-only


class TransactionAdminSerializer(serializers.ModelSerializer):
    """Admin sees everything including metadata, balance_before, and raw reference."""
    class Meta:
        model = Transaction
        fields = '__all__'
        read_only_fields = fields