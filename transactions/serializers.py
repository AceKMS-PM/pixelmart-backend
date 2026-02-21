from rest_framework import serializers
from .models import Transaction


class TransactionSerializer(serializers.ModelSerializer):
    """
    Vendor-facing transaction history.
    Shows enough for a vendor to understand their ledger.
    EXCLUDED:
      - `metadata` (JSONField — may contain internal payment processor data, webhook IDs, etc.)
      - `balance_before` / `balance_after` (only balance_after is useful to show; before can be inferred)
      - `reference` is kept as it may be needed for dispute resolution with support
    """
    class Meta:
        model = Transaction
        fields = [
            'uuid',
            'transaction_type', 'direction',
            'amount', 'currency',
            'balance_after',
            'status',
            'reference', 'description',
            'processed_at', 'created_at',
        ]
        read_only_fields = fields  # transactions are always read-only for vendors


class TransactionAdminSerializer(serializers.ModelSerializer):
    """Admin sees everything including metadata, balance_before, and raw reference."""
    class Meta:
        model = Transaction
        fields = '__all__'
        read_only_fields = fields