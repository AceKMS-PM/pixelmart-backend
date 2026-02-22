from django.db import transaction as db_transaction
from django.utils import timezone
from rest_framework import viewsets, mixins, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import Order, Coupon, Payout
from .serializers import (
    OrderCustomerSerializer,
    OrderVendorSerializer,
    OrderAdminSerializer,
    CouponSerializer,
    CouponPublicSerializer,
    PayoutSerializer,
    PayoutAdminSerializer,
)
from stores.models import Store


def _role(user):
    return getattr(user, 'role', 'customer')


# ── Orders ────────────────────────────────────────────────────────────────────

class OrderViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Customers : list + retrieve leurs propres commandes (lecture seule).
    Vendors   : list + retrieve commandes de leur boutique, update status/tracking.
    Admins    : accès complet.

    La création de commande est intentionnellement absente ici.
    Elle vivra dans un endpoint checkout atomique dédié
    (payment intent + réservation inventaire + création Order).
    """
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        role = _role(user)
        qs = Order.objects.select_related('customer', 'store').prefetch_related('order_items')
        if role == 'admin':
            return qs
        if role == 'vendor':
            return qs.filter(store__owner=user)
        return qs.filter(customer=user)

    def get_serializer_class(self):
        role = _role(self.request.user)
        if role == 'admin':
            return OrderAdminSerializer
        if role == 'vendor':
            return OrderVendorSerializer
        return OrderCustomerSerializer

    def update(self, request, *args, **kwargs):
        if _role(request.user) == 'customer':
            raise PermissionDenied('Customers cannot modify orders.')
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if _role(request.user) == 'customer':
            raise PermissionDenied('Customers cannot modify orders.')
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)


# ── Coupons ───────────────────────────────────────────────────────────────────

class CouponViewSet(viewsets.ModelViewSet):
    """Vendor-only — gestion des coupons de leur boutique."""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = CouponSerializer
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        if _role(user) == 'admin':
            return Coupon.objects.all()
        return Coupon.objects.filter(store__owner=user)

    def perform_create(self, serializer):
        store_slug = self.request.data.get('store_slug')
        try:
            store = Store.objects.get(slug=store_slug, owner=self.request.user)
        except Store.DoesNotExist:
            raise ValidationError({'store_slug': 'Store not found or you do not own it.'})
        serializer.save(store=store)

    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def validate(self, request):
        """
        Checkout : valider un code coupon et retourner uniquement les infos de remise.
        Ne retourne pas la config interne (used_count, max_uses, etc.).
        """
        code = request.data.get('code', '').strip().upper()
        store_id = request.data.get('store_id')
        cart_total = int(request.data.get('cart_total', 0))

        invalid_response = Response(
            {'valid': False, 'reason': 'INVALID_CODE'},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

        try:
            coupon = Coupon.objects.get(code=code, store_id=store_id, is_active=True)
        except Coupon.DoesNotExist:
            return invalid_response

        now = timezone.now()
        if coupon.starts_at and coupon.starts_at > now:
            return invalid_response  # pas encore actif — même erreur générique (pas d'info leak)
        if coupon.expires_at and coupon.expires_at < now:
            return Response({'valid': False, 'reason': 'COUPON_EXPIRED'},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        if coupon.max_uses and coupon.used_count >= coupon.max_uses:
            return Response({'valid': False, 'reason': 'MAX_USES_REACHED'},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        if coupon.min_order_amount and cart_total < coupon.min_order_amount:
            return Response({'valid': False, 'reason': 'MIN_ORDER_NOT_MET'},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        if coupon.discount_type == 'percentage':
            discount_amount = int(cart_total * coupon.value / 100)
        else:
            discount_amount = min(coupon.value, cart_total)

        return Response({
            'valid': True,
            'discount_amount': discount_amount,
            'discount_type': coupon.discount_type,
            'new_total': cart_total - discount_amount,
        })


# ── Payouts ───────────────────────────────────────────────────────────────────

class PayoutViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Vendors demandent des virements (POST) et consultent leur historique (GET).
    Update / delete interdits — les payouts sont immuables une fois créés.
    Admins voient tous les payouts avec détail complet.

    Workflow atomique à la création :
    1. Vérifications métier (rôle, 2FA, solde, pas de payout en cours)
    2. Dans une transaction DB atomique :
       a. Créer la Transaction de ledger (type=payout, direction=debit)
       b. Déduire store.balance
       c. Créer le Payout lié à cette Transaction
    Si l'une des étapes échoue, tout est annulé — aucune donnée partielle.
    """
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        user = self.request.user
        if _role(user) == 'admin':
            return Payout.objects.select_related('store', 'initiated_by', 'transaction').all()
        return Payout.objects.select_related('transaction').filter(store__owner=user)

    def get_serializer_class(self):
        if _role(self.request.user) == 'admin':
            return PayoutAdminSerializer
        return PayoutSerializer

    def perform_create(self, serializer):
        from django.conf import settings as django_settings
        from transactions.models import Transaction

        user = self.request.user

        # ── Vérifications métier ───────────────────────────────────────────
        if _role(user) != 'vendor':
            raise PermissionDenied('Only vendors can request payouts.')

        if not user.is_2fa_enabled:
            raise PermissionDenied('2FA must be enabled before requesting a payout.')

        store_slug = self.request.data.get('store_slug')
        try:
            store = Store.objects.get(slug=store_slug, owner=user)
        except Store.DoesNotExist:
            raise ValidationError({'store_slug': 'Store not found or you do not own it.'})

        # Règle spec : pas de payout 'processing' en cours sur la même boutique
        if Payout.objects.filter(store=store, status='processing').exists():
            raise ValidationError(
                {'store_slug': 'A payout is already being processed for this store. '
                               'Please wait for it to complete before requesting another.'}
            )

        min_amount = getattr(django_settings, 'MIN_PAYOUT_AMOUNT', 100)
        amount = serializer.validated_data.get('amount', 0)

        if amount < min_amount:
            raise ValidationError({'amount': f'Minimum payout is {min_amount} cents.'})

        if store.balance < amount:
            raise ValidationError({'amount': 'Insufficient balance.'})

        # ── Création atomique : Transaction + déduction solde + Payout ────
        with db_transaction.atomic():
            balance_before = store.balance
            balance_after = balance_before - amount

            # 1. Écriture de ledger immuable
            ledger_entry = Transaction.objects.create(
                store=store,
                transaction_type='payout',
                direction='debit',
                amount=amount,
                currency=serializer.validated_data.get('currency', store.currency),
                balance_before=balance_before,
                balance_after=balance_after,
                status='pending',
                description=f"Payout request — {serializer.validated_data.get('method', '')}",
            )

            # 2. Déduction du solde boutique
            store.balance = balance_after
            store.save(update_fields=['balance'])

            # 3. Création du payout lié à la transaction
            serializer.save(
                store=store,
                initiated_by=user,
                transaction=ledger_entry,
            )