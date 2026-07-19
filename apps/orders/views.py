from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework import status, viewsets, serializers as s
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, inline_serializer

from core.mixins import LoginRequiredMixin
from apps.authentication.permissions import IsAdmin, IsAdminOrEmployee, IsUPAUser
from apps.products.models import ProductVariant
from apps.products.utils import get_upa_price
from apps.wallet.models import Wallet, WalletTransaction
from .models import Address, Cart, CartItem, Order, OrderItem, RETURN_EXCHANGE_STATUSES
from .razorpay import create_razorpay_order, verify_razorpay_signature
from .serializers import (
    AddressSerializer,
    CartSerializer, CartItemSerializer,
    CheckoutInitiateSerializer, CheckoutConfirmSerializer,
    OrderListSerializer, OrderDetailSerializer,
    AdminOrderUpdateSerializer,
)


class _OrderPagination(PageNumberPagination):
    page_size = 20


# ── Address ───────────────────────────────────────────────────────────────────

class AddressViewSet(LoginRequiredMixin, viewsets.ModelViewSet):
    serializer_class = AddressSerializer

    def get_permissions(self):
        return [IsUPAUser()]

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        user = self.request.user
        # First address auto-becomes default
        is_first = not Address.objects.filter(user=user).exists()
        serializer.save(user=user, is_default=serializer.validated_data.get("is_default", is_first))

    @extend_schema(tags=["Addresses"])
    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, pk=None):
        addr = get_object_or_404(Address, pk=pk, user=request.user)
        Address.objects.filter(user=request.user, is_default=True).update(is_default=False)
        addr.is_default = True
        addr.save(update_fields=["is_default"])
        return Response(AddressSerializer(addr).data)


# ── Cart ──────────────────────────────────────────────────────────────────────

class CartViewSet(LoginRequiredMixin, viewsets.ViewSet):

    def get_permissions(self):
        return [IsUPAUser()]

    def _get_or_create_cart(self):
        cart, _ = Cart.objects.get_or_create(user=self.request.user)
        return cart

    @extend_schema(tags=["Cart"])
    def list(self, request):
        cart = self._get_or_create_cart()
        cart_data = CartSerializer(
            cart,
            context={"request": request},
        ).data
        return Response(cart_data)

    @extend_schema(tags=["Cart"])
    @action(detail=False, methods=["post"], url_path="add")
    def add_item(self, request):
        variant_id = request.data.get("variant_id")
        quantity   = int(request.data.get("quantity", 1))
        if not variant_id:
            return Response({"detail": "variant_id required."}, status=400)
        variant = get_object_or_404(ProductVariant, pk=variant_id, is_active=True)
        if variant.stock_quantity < quantity:
            return Response({"detail": "Insufficient stock."}, status=400)

        cart = self._get_or_create_cart()
        item, created = CartItem.objects.get_or_create(cart=cart, variant=variant)
        if not created:
            item.quantity += quantity
        else:
            item.quantity = quantity
        item.save()
        return Response(
            CartSerializer(cart, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(tags=["Cart"])
    @action(detail=True, methods=["patch"], url_path="update")
    def update_item(self, request, pk=None):
        cart = self._get_or_create_cart()
        item = get_object_or_404(CartItem, pk=pk, cart=cart)
        qty  = int(request.data.get("quantity", item.quantity))
        if qty <= 0:
            item.delete()
        else:
            if item.variant.stock_quantity < qty:
                return Response({"detail": "Insufficient stock."}, status=400)
            item.quantity = qty
            item.save()
        return Response(CartSerializer(cart, context={"request": request}).data)

    @extend_schema(tags=["Cart"])
    @action(detail=True, methods=["delete"], url_path="remove")
    def remove_item(self, request, pk=None):
        cart = self._get_or_create_cart()
        item = get_object_or_404(CartItem, pk=pk, cart=cart)
        item.delete()
        return Response(CartSerializer(cart, context={"request": request}).data)

    @extend_schema(tags=["Cart"])
    @action(detail=False, methods=["delete"], url_path="clear")
    def clear(self, request):
        cart = self._get_or_create_cart()
        cart.items.all().delete()
        return Response({"detail": "Cart cleared."})


# ── Checkout ──────────────────────────────────────────────────────────────────

def _compute_cart_totals(cart):
    """Returns (subtotal, upa_discount, amount_payable, items_data)."""
    subtotal      = Decimal("0")
    discount      = Decimal("0")
    other_total   = Decimal("0")
    gst_total     = Decimal("0")
    items_data    = []

    for item in cart.items.select_related("variant__product").all():
        pdata   = get_upa_price(item.variant)
        mrp     = Decimal(pdata["mrp"])
        upa     = Decimal(pdata["upa_price"])
        product = item.variant.product
        qty     = item.quantity

        subtotal += mrp * qty
        discount += (mrp - upa) * qty

        if product.other_charges_type == 'flat':
            other_per_unit = Decimal(str(product.other_charges or 0))
        else:
            other_per_unit = upa * Decimal(str(product.other_charges or 0)) / 100
        item_other = (other_per_unit * qty).quantize(Decimal("0.01"), ROUND_HALF_UP)
        other_total += item_other

        gst_pct   = Decimal(str(product.gst_percentage or 0))
        item_gst  = (upa * gst_pct / 100 * qty).quantize(Decimal("0.01"), ROUND_HALF_UP)
        gst_total += item_gst

        line_total = (upa * qty + item_other + item_gst).quantize(Decimal("0.01"), ROUND_HALF_UP)

        items_data.append({
            "variant":      item.variant,
            "product_name": product.name,
            "variant_name": item.variant.name,
            "sku":          item.variant.sku,
            "mrp":          mrp,
            "upa_price":    upa,
            "quantity":     qty,
            "line_total":   line_total,
            "other_charges": item_other,
            "gst_amount":   item_gst,
        })

    q           = lambda d: d.quantize(Decimal("0.01"), ROUND_HALF_UP)  # noqa: E731
    amount_payable = q(subtotal - discount + other_total + gst_total)
    return q(subtotal), q(discount), amount_payable, items_data


class CheckoutInitiateView(LoginRequiredMixin, APIView):
    permission_classes = [IsUPAUser]

    @extend_schema(tags=["Checkout"])
    def post(self, request):
        ser = CheckoutInitiateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        address = get_object_or_404(Address, pk=data["address_id"], user=request.user)

        try:
            cart = Cart.objects.get(user=request.user)
        except Cart.DoesNotExist:
            return Response({"detail": "Cart is empty."}, status=400)

        if not cart.items.exists():
            return Response({"detail": "Cart is empty."}, status=400)

        # Validate stock
        for item in cart.items.select_related("variant").all():
            if item.variant.stock_quantity < item.quantity:
                return Response(
                    {"detail": f"'{item.variant.name}' only has {item.variant.stock_quantity} in stock."},
                    status=400,
                )

        subtotal, upa_discount, amount_payable, items_data = _compute_cart_totals(cart)

        # Wallet cap
        wallet_amount = min(data["wallet_amount"], amount_payable)
        try:
            wallet = Wallet.objects.get(user=request.user)
            wallet_amount = min(wallet_amount, wallet.balance)
        except Wallet.DoesNotExist:
            wallet_amount = Decimal("0")

        wallet_amount   = wallet_amount.quantize(Decimal("0.01"), ROUND_HALF_UP)
        razorpay_amount = (amount_payable - wallet_amount).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # Create (or replace) a draft Order so confirm can fetch it by ID
        draft_order = Order.objects.create(
            user=request.user,
            address_name=address.name,
            address_phone=address.phone,
            address_line=address.address_line,
            address_city=address.city,
            address_state=address.state,
            address_pincode=address.pincode,
            subtotal=subtotal,
            upa_discount=upa_discount,
            amount_payable=amount_payable,
            wallet_used=wallet_amount,
            razorpay_amount=razorpay_amount,
            payment_status="pending",
            order_status="pending",
        )

        # Snapshot OrderItems at initiate time (price-locked)
        for idata in items_data:
            OrderItem.objects.create(
                order=draft_order,
                variant=idata["variant"],
                product_name=idata["product_name"],
                variant_name=idata["variant_name"],
                sku=idata["sku"],
                mrp=idata["mrp"],
                upa_price=idata["upa_price"],
                quantity=idata["quantity"],
                line_total=idata["line_total"],
                other_charges=idata["other_charges"],
                gst_amount=idata["gst_amount"],
                status="pending",
            )

        result = {
            "internal_order_id": str(draft_order.id),
            "address": AddressSerializer(address).data,
            "subtotal":        str(subtotal),
            "upa_discount":    str(upa_discount),
            "amount_payable":  str(amount_payable),
            "wallet_used":     str(wallet_amount),
            "razorpay_amount": str(razorpay_amount),
        }

        if razorpay_amount > Decimal("0"):
            amount_paise = int((razorpay_amount * 100).quantize(Decimal("1")))
            rz = create_razorpay_order(amount_paise)
            result["razorpay_order_id"] = rz["razorpay_order_id"]
            result["razorpay_key_id"]   = ""
            from django.conf import settings as djsettings
            if not djsettings.MOCK_PAYMENT_MODE:
                result["razorpay_key_id"] = djsettings.RAZORPAY_KEY_ID
        else:
            result["razorpay_order_id"] = ""
            result["razorpay_key_id"]   = ""

        return Response(result)


class CheckoutConfirmView(LoginRequiredMixin, APIView):
    permission_classes = [IsUPAUser]

    @extend_schema(tags=["Checkout"])
    def post(self, request):
        ser = CheckoutConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        order = get_object_or_404(
            Order,
            pk=data["internal_order_id"],
            user=request.user,
            payment_status="pending",
        )

        existing_items = list(order.items.select_related("variant__product").all())

        if existing_items:
            return self._confirm_with_items(request, order, existing_items, data)
        return self._confirm_from_cart(request, order, data)

    def _confirm_with_items(self, request, order, existing_items, data):
        """Confirm path for orders that have pre-snapshotted OrderItems (new flow)."""
        PRICE_LOCK_HOURS = 24
        hours_since = (timezone.now() - order.created_at).total_seconds() / 3600
        price_locked = hours_since <= PRICE_LOCK_HOURS

        q = lambda d: d.quantize(Decimal("0.01"), ROUND_HALF_UP)

        if not price_locked:
            for item in existing_items:
                pdata   = get_upa_price(item.variant)
                product = item.variant.product
                qty     = item.quantity
                mrp     = Decimal(pdata["mrp"])
                upa     = Decimal(pdata["upa_price"])
                if product.other_charges_type == "flat":
                    other = Decimal(str(product.other_charges or 0)) * qty
                else:
                    other = upa * Decimal(str(product.other_charges or 0)) / 100 * qty
                other = q(other)
                gst   = q(upa * Decimal(str(product.gst_percentage or 0)) / 100 * qty)
                lt    = q(upa * qty + other + gst)
                item.mrp          = mrp
                item.upa_price    = upa
                item.other_charges = other
                item.gst_amount   = gst
                item.line_total   = lt
                item.save(update_fields=["mrp", "upa_price", "other_charges", "gst_amount", "line_total"])

        items_data = [
            {
                "variant":      i.variant,
                "product_name": i.product_name,
                "variant_name": i.variant_name,
                "sku":          i.sku,
                "mrp":          i.mrp,
                "upa_price":    i.upa_price,
                "quantity":     i.quantity,
                "line_total":   i.line_total,
                "other_charges": i.other_charges or Decimal("0"),
                "gst_amount":   i.gst_amount   or Decimal("0"),
            }
            for i in existing_items
        ]

        subtotal       = q(sum(d["mrp"] * d["quantity"]                      for d in items_data))
        upa_discount   = q(sum((d["mrp"] - d["upa_price"]) * d["quantity"]   for d in items_data))
        amount_payable = q(sum(d["line_total"]                                for d in items_data))

        wallet_amount   = order.wallet_used
        razorpay_amount = order.razorpay_amount

        try:
            wallet = Wallet.objects.get(user=request.user)
        except Wallet.DoesNotExist:
            wallet = None

        if razorpay_amount > Decimal("0"):
            if not verify_razorpay_signature(
                data["razorpay_order_id"],
                data["razorpay_payment_id"],
                data["razorpay_signature"],
            ):
                return Response({"detail": "Payment verification failed."}, status=400)

        with transaction.atomic():
            for idata in items_data:
                variant = ProductVariant.objects.select_for_update().get(pk=idata["variant"].pk)
                if variant.stock_quantity < idata["quantity"]:
                    return Response(
                        {"detail": f"'{variant.name}' went out of stock."},
                        status=400,
                    )

            order.payment_status      = "paid"
            order.order_status        = "confirmed"
            order.razorpay_payment_id = data["razorpay_payment_id"]
            order.razorpay_order_id   = data["razorpay_order_id"]
            order.razorpay_signature  = data["razorpay_signature"]
            order.subtotal            = subtotal
            order.upa_discount        = upa_discount
            order.amount_payable      = amount_payable
            order.save(update_fields=[
                "payment_status", "order_status",
                "razorpay_payment_id", "razorpay_order_id", "razorpay_signature",
                "subtotal", "upa_discount", "amount_payable",
            ])

            from apps.warehouse.utils import deduct_stock as fifo_deduct
            order_ref = str(order.id)[:20]
            for idata in items_data:
                variant = idata["variant"]
                qty     = idata["quantity"]
                try:
                    fifo_deduct(variant, qty, performed_by=request.user, reference=order_ref)
                except ValueError:
                    ProductVariant.objects.filter(pk=variant.pk).update(
                        stock_quantity=variant.stock_quantity - qty
                    )

            if wallet and wallet_amount > Decimal("0"):
                wallet.balance -= wallet_amount
                wallet.save(update_fields=["balance"])
                WalletTransaction.objects.create(
                    wallet=wallet,
                    type="debit",
                    amount=wallet_amount,
                    reason="Payment for order",
                    reference=data["razorpay_order_id"] or "wallet-only",
                )

            order.items.all().update(status="confirmed")

            try:
                cart = Cart.objects.get(user=request.user)
                variant_ids = [d["variant"].pk for d in items_data]
                cart.items.filter(variant_id__in=variant_ids).delete()
            except Cart.DoesNotExist:
                pass

        self._post_confirm_hooks(order)
        return Response(OrderDetailSerializer(order).data, status=status.HTTP_201_CREATED)

    def _confirm_from_cart(self, request, order, data):
        """Legacy confirm path: compute items from the current cart."""
        try:
            cart = Cart.objects.get(user=request.user)
        except Cart.DoesNotExist:
            return Response({"detail": "Cart is empty."}, status=400)

        if not cart.items.exists():
            return Response({"detail": "Cart is empty."}, status=400)

        subtotal, upa_discount, amount_payable, items_data = _compute_cart_totals(cart)

        wallet_amount = data["wallet_amount"]
        try:
            wallet = Wallet.objects.get(user=request.user)
        except Wallet.DoesNotExist:
            wallet = None
            wallet_amount = Decimal("0")

        if wallet:
            wallet_amount = min(wallet_amount, wallet.balance, amount_payable)
        else:
            wallet_amount = Decimal("0")

        wallet_amount   = wallet_amount.quantize(Decimal("0.01"), ROUND_HALF_UP)
        razorpay_amount = (amount_payable - wallet_amount).quantize(Decimal("0.01"), ROUND_HALF_UP)

        if razorpay_amount > Decimal("0"):
            if not verify_razorpay_signature(
                data["razorpay_order_id"],
                data["razorpay_payment_id"],
                data["razorpay_signature"],
            ):
                return Response({"detail": "Payment verification failed."}, status=400)

        with transaction.atomic():
            for idata in items_data:
                variant = ProductVariant.objects.select_for_update().get(pk=idata["variant"].pk)
                if variant.stock_quantity < idata["quantity"]:
                    return Response(
                        {"detail": f"'{variant.name}' went out of stock."},
                        status=400,
                    )

            order.payment_status      = "paid"
            order.order_status        = "confirmed"
            order.razorpay_payment_id = data["razorpay_payment_id"]
            order.razorpay_order_id   = data["razorpay_order_id"]
            order.razorpay_signature  = data["razorpay_signature"]
            order.subtotal            = subtotal
            order.upa_discount        = upa_discount
            order.amount_payable      = amount_payable
            order.wallet_used         = wallet_amount
            order.razorpay_amount     = razorpay_amount
            order.save(update_fields=[
                "payment_status", "order_status",
                "razorpay_payment_id", "razorpay_order_id", "razorpay_signature",
                "subtotal", "upa_discount", "amount_payable",
                "wallet_used", "razorpay_amount",
            ])

            from apps.warehouse.utils import deduct_stock as fifo_deduct
            order_ref = str(order.id)[:20]
            for idata in items_data:
                variant = idata["variant"]
                qty     = idata["quantity"]
                try:
                    fifo_deduct(variant, qty, performed_by=request.user, reference=order_ref)
                except ValueError:
                    ProductVariant.objects.filter(pk=variant.pk).update(
                        stock_quantity=variant.stock_quantity - qty
                    )

            if wallet and wallet_amount > Decimal("0"):
                wallet.balance -= wallet_amount
                wallet.save(update_fields=["balance"])
                WalletTransaction.objects.create(
                    wallet=wallet,
                    type="debit",
                    amount=wallet_amount,
                    reason="Payment for order",
                    reference=data["razorpay_order_id"] or "wallet-only",
                )

            for idata in items_data:
                OrderItem.objects.create(
                    order=order,
                    variant=idata["variant"],
                    product_name=idata["product_name"],
                    variant_name=idata["variant_name"],
                    sku=idata["sku"],
                    mrp=idata["mrp"],
                    upa_price=idata["upa_price"],
                    quantity=idata["quantity"],
                    line_total=idata["line_total"],
                    other_charges=idata["other_charges"],
                    gst_amount=idata["gst_amount"],
                )

            order.items.all().update(status="confirmed")
            cart.items.all().delete()

        self._post_confirm_hooks(order)
        return Response(OrderDetailSerializer(order).data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _post_confirm_hooks(order):
        import logging
        from apps.commissions.utils import create_commission_breakup
        _logger = logging.getLogger(__name__)
        if order.user:
            for item in order.items.select_related("variant__product").all():
                try:
                    create_commission_breakup(item)
                except Exception as e:
                    _logger.error("Commission breakup failed for item %s: %s", item.id, e)
        try:
            from apps.company_wallet.utils import record_order_received
            record_order_received(order)
        except Exception as e:
            _logger.error("CompanyWallet record_order_received failed: %s", e)


# ── User Orders ───────────────────────────────────────────────────────────────

class UserOrderViewSet(LoginRequiredMixin, viewsets.ReadOnlyModelViewSet):
    pagination_class = _OrderPagination

    def get_permissions(self):
        return [IsUPAUser()]

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user).prefetch_related("items")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return OrderDetailSerializer
        return OrderListSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    @extend_schema(
        tags=["Orders"],
        summary="Get delivery OTP for customer's order",
        responses={200: inline_serializer('DeliveryOTPResponse', fields={
            'otp':    s.CharField(),
            'status': s.CharField(),
        })},
    )
    @action(detail=True, methods=["get"], url_path="delivery-otp")
    def delivery_otp(self, request, pk=None):
        order = self.get_object()
        try:
            assignment = order.delivery_assignment
            if assignment.status in ('assigned', 'picked_up'):
                return Response({'otp': assignment.otp, 'status': assignment.status})
        except Exception:
            pass
        return Response({'otp': None, 'status': None})

    @action(detail=True, methods=["post"], url_path="mark-satisfied")
    def mark_satisfied(self, request, pk=None):
        order = self.get_object()

        if order.user != request.user:
            return Response({"error": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        if order.order_status not in ["confirmed", "packed", "shipped", "delivered"]:
            return Response({"error": "Order cannot be marked satisfied."}, status=status.HTTP_400_BAD_REQUEST)

        if order.is_satisfied:
            return Response({"error": "Order already marked as satisfied."}, status=status.HTTP_400_BAD_REQUEST)

        # Block if any item has an active return or exchange request
        from apps.returns.models import ReturnRequest, ACTIVE_REQUEST_STATUSES
        active_items = (
            ReturnRequest.objects
            .filter(order_item__order=order, status__in=ACTIVE_REQUEST_STATUSES)
            .values_list('order_item__product_name', flat=True)
        )
        if active_items.exists():
            names = ', '.join(active_items[:3])
            return Response(
                {"error": f"Cannot mark as satisfied while return/exchange requests are pending for: {names}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Block if any exchange buffer is still active (window not yet expired).
        # We hold the entire order's commission until all items are clear.
        from apps.commissions.models import CommissionBreakup as CB
        active_buffers = CB.objects.filter(
            order_item__order=order,
            status='exchange_hold',
            return_window_expires__gt=timezone.now(),
        )
        if active_buffers.exists():
            latest_expiry = active_buffers.order_by('-return_window_expires').first().return_window_expires
            local_expiry  = timezone.localtime(latest_expiry)
            return Response(
                {"error": (
                    f"Exchange buffer active until {local_expiry.strftime('%d %b %Y, %I:%M %p')}. "
                    "Commission will be released automatically after that."
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            order.is_satisfied = True
            order.satisfied_at = timezone.now()
            order.satisfied_by = request.user
            order.save(update_fields=["is_satisfied", "satisfied_at", "satisfied_by"])

            # Credit the entire order's commission in one pass once all items are clear.
            # — pending_window items: cleanly delivered, no return/exchange
            # — exchange_hold items: exchange resolved, buffer expired
            # Cancelled breakups (returned items) are skipped automatically.
            if order.order_status == 'delivered':
                from apps.commissions.utils import process_commission_breakup
                now = timezone.now()
                for item in order.items.select_related("commission_breakup").all():
                    try:
                        breakup = item.commission_breakup
                        if breakup.status == 'pending_window' and item.status == 'delivered':
                            process_commission_breakup(breakup, processed_by=request.user)
                        elif (
                            breakup.status == 'exchange_hold'
                            and breakup.return_window_expires
                            and breakup.return_window_expires <= now
                        ):
                            process_commission_breakup(breakup, processed_by=request.user)
                    except Exception:
                        pass

            # Lock out returns on cleanly delivered items —
            # items already in a return/exchange flow keep their own state.
            order.items.filter(status='delivered').update(
                return_window_blocked=True,
                return_window_blocked_reason="satisfied",
            )

        if order.order_status == 'delivered':
            message = "Order marked as satisfied. Commissions credited to upline wallets."
        else:
            message = "Order marked as satisfied. Commissions will be credited once the order is delivered."

        return Response({
            "message": message,
            "satisfied_at": order.satisfied_at,
        })

    @action(detail=True, methods=["get"], url_path="payment-info")
    def payment_info(self, request, pk=None):
        """Return items with stock/price status, addresses, and wallet balance for the pay sheet."""
        order = self.get_object()
        if order.payment_status != "pending" or order.order_status != "pending":
            return Response({"error": "Order is not pending."}, status=400)

        PRICE_LOCK_HOURS = 24
        hours_since  = (timezone.now() - order.created_at).total_seconds() / 3600
        price_locked = hours_since <= PRICE_LOCK_HOURS

        order_items = list(order.items.select_related("variant__product").all())

        # Legacy orders (created before item-snapshotting) have no OrderItems.
        # Fall back to the current cart so the user can still see what they're paying for.
        if not order_items:
            try:
                cart = Cart.objects.get(user=request.user)
                _, _, _, cart_items_data = _compute_cart_totals(cart)
            except Cart.DoesNotExist:
                cart_items_data = []

            items_out = []
            for idata in cart_items_data:
                variant = idata["variant"]
                qty     = idata["quantity"]
                stock   = variant.stock_quantity
                items_out.append({
                    "id":               None,
                    "product_name":     idata["product_name"],
                    "variant_name":     idata["variant_name"],
                    "variant_id":       str(variant.id),
                    "sku":              idata["sku"],
                    "quantity":         qty,
                    "mrp":              str(idata["mrp"]),
                    "upa_price":        str(idata["upa_price"]),
                    "upa_price_locked": str(idata["upa_price"]),
                    "line_total":       str(idata["line_total"]),
                    "price_changed":    False,
                    "stock_quantity":   stock,
                    "stock_ok":         stock >= qty,
                    "stock_shortfall":  max(0, qty - stock),
                    "legacy":           True,
                })
        else:
            items_out = []
            for item in order_items:
                stock           = item.variant.stock_quantity
                stock_ok        = stock >= item.quantity
                stock_shortfall = max(0, item.quantity - stock)

                if not price_locked:
                    pdata         = get_upa_price(item.variant)
                    current_upa   = Decimal(pdata["upa_price"])
                    price_changed = current_upa != item.upa_price
                else:
                    current_upa   = item.upa_price
                    price_changed = False

                items_out.append({
                    "id":               str(item.id),
                    "product_name":     item.product_name,
                    "variant_name":     item.variant_name,
                    "variant_id":       str(item.variant_id) if item.variant_id else None,
                    "sku":              item.sku,
                    "quantity":         item.quantity,
                    "mrp":              str(item.mrp),
                    "upa_price":        str(current_upa),
                    "upa_price_locked": str(item.upa_price),
                    "line_total":       str(item.line_total),
                    "price_changed":    price_changed,
                    "stock_quantity":   stock,
                    "stock_ok":         stock_ok,
                    "stock_shortfall":  stock_shortfall,
                    "legacy":           False,
                })

        try:
            wallet_balance = str(Wallet.objects.get(user=request.user).balance)
        except Wallet.DoesNotExist:
            wallet_balance = "0.00"

        addresses   = Address.objects.filter(user=request.user)
        default_addr = addresses.filter(is_default=True).first() or addresses.first()

        return Response({
            "order_id":            str(order.id),
            "order_number":        order.order_number,
            "price_locked":        price_locked,
            "hours_since_created": round(hours_since, 1),
            "amount_payable":      str(order.amount_payable),
            "wallet_used":         str(order.wallet_used),
            "razorpay_amount":     str(order.razorpay_amount),
            "items":               items_out,
            "wallet_balance":      wallet_balance,
            "addresses":           AddressSerializer(addresses, many=True).data,
            "default_address_id":  str(default_addr.id) if default_addr else None,
        })

    @action(detail=True, methods=["post"], url_path="remove-item")
    def remove_item(self, request, pk=None):
        """Remove one item from a pending order and sync it out of the cart."""
        order = self.get_object()
        if order.payment_status != "pending":
            return Response({"error": "Can only modify pending orders."}, status=400)

        item_id = request.data.get("item_id")
        if not item_id:
            return Response({"error": "item_id required."}, status=400)

        try:
            item = order.items.get(id=item_id)
        except OrderItem.DoesNotExist:
            return Response({"error": "Item not found."}, status=404)

        variant = item.variant
        item.delete()

        try:
            Cart.objects.get(user=request.user).items.filter(variant=variant).delete()
        except Cart.DoesNotExist:
            pass

        if not order.items.exists():
            order.delete()
            return Response({"order_cancelled": True})

        q = lambda d: d.quantize(Decimal("0.01"), ROUND_HALF_UP)
        remaining = list(order.items.all())
        order.subtotal       = q(sum(i.mrp * i.quantity       for i in remaining))
        order.upa_discount   = q(sum((i.mrp - i.upa_price) * i.quantity for i in remaining))
        order.amount_payable = q(sum(i.line_total             for i in remaining))
        order.wallet_used    = min(order.wallet_used, order.amount_payable)
        order.razorpay_amount = q(order.amount_payable - order.wallet_used)
        order.save(update_fields=["subtotal", "upa_discount", "amount_payable", "wallet_used", "razorpay_amount"])

        return Response({"order_cancelled": False, "amount_payable": str(order.amount_payable)})

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel_pending(self, request, pk=None):
        """Cancel a pending order (deletes it entirely)."""
        order = self.get_object()
        if order.payment_status != "pending" or order.order_status != "pending":
            return Response({"error": "Only pending orders can be cancelled."}, status=400)
        order.delete()
        return Response({"message": "Order cancelled."})

    @action(detail=True, methods=["post"], url_path="retry-payment")
    def retry_payment(self, request, pk=None):
        """Create a fresh Razorpay order for a specific pending order, applying wallet choice."""
        order = self.get_object()

        if order.payment_status != "pending" or order.order_status != "pending":
            return Response({"error": "Only pending orders can be retried."}, status=400)

        try:
            wallet_amount = Decimal(str(request.data.get("wallet_amount", "0"))).quantize(Decimal("0.01"), ROUND_HALF_UP)
        except Exception:
            wallet_amount = Decimal("0")

        try:
            wallet = Wallet.objects.get(user=request.user)
            wallet_amount = min(wallet_amount, wallet.balance, order.amount_payable)
        except Wallet.DoesNotExist:
            wallet_amount = Decimal("0")

        razorpay_amount = (order.amount_payable - wallet_amount).quantize(Decimal("0.01"), ROUND_HALF_UP)
        order.wallet_used     = wallet_amount
        order.razorpay_amount = razorpay_amount

        result = {
            "internal_order_id": str(order.id),
            "amount_payable":    str(order.amount_payable),
            "wallet_used":       str(wallet_amount),
            "razorpay_amount":   str(razorpay_amount),
            "razorpay_order_id": "",
            "razorpay_key_id":   "",
        }

        if razorpay_amount > Decimal("0"):
            amount_paise = int((razorpay_amount * 100).quantize(Decimal("1")))
            rz = create_razorpay_order(amount_paise)
            order.razorpay_order_id = rz["razorpay_order_id"]
            result["razorpay_order_id"] = rz["razorpay_order_id"]
            from django.conf import settings as djsettings
            if not djsettings.MOCK_PAYMENT_MODE:
                result["razorpay_key_id"] = djsettings.RAZORPAY_KEY_ID

        order.save(update_fields=["wallet_used", "razorpay_amount", "razorpay_order_id"])
        return Response(result)


# ── Admin Orders ──────────────────────────────────────────────────────────────

class AdminOrderViewSet(LoginRequiredMixin, viewsets.ModelViewSet):
    pagination_class = _OrderPagination
    http_method_names = ["get", "patch", "head", "options"]

    def get_permissions(self):
        return [IsAdminOrEmployee()]

    def get_queryset(self):
        qs = Order.objects.select_related("user").prefetch_related(
            "items",
            "items__commission_breakup",
            "items__commission_breakup__entries",
        )
        params = self.request.query_params

        # Only exclude offline orders from the LIST — retrieve must work for any order
        if self.action == 'list':
            include_offline = params.get("include_offline", "").lower() == "true"
            if not include_offline:
                qs = qs.filter(is_offline=False)

        search = params.get("search", "").strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(order_number__icontains=search) |
                Q(user__mobile__icontains=search) |
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search)
            )

        order_status = params.get("order_status", "")
        if order_status:
            qs = qs.filter(order_status=order_status)

        payment_status = params.get("payment_status", "")
        if payment_status:
            qs = qs.filter(payment_status=payment_status)

        date_from = params.get("date_from", "")
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        date_to = params.get("date_to", "")
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        return qs

    def get_serializer_class(self):
        if self.action == "partial_update":
            return AdminOrderUpdateSerializer
        if self.action == "retrieve":
            return OrderDetailSerializer
        return OrderListSerializer

    def partial_update(self, request, *args, **kwargs):
        order = self.get_object()
        ser = AdminOrderUpdateSerializer(order, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()

        # Auto-assign delivery partner when order is packed
        new_order_status = ser.validated_data.get("order_status")
        if new_order_status == 'packed':
            try:
                from apps.delivery.utils import auto_assign_if_enabled
                auto_assign_if_enabled(order, assigned_by=request.user)
            except Exception:
                pass

        # Sync item statuses (exclude return/exchange flow items)
        if new_order_status:
            items_qs = order.items.exclude(status__in=RETURN_EXCHANGE_STATUSES)
            if new_order_status == "delivered":
                from django.utils import timezone as tz
                items_qs.filter(delivered_at__isnull=True).update(
                    status=new_order_status, delivered_at=tz.now()
                )
                items_qs.filter(delivered_at__isnull=False).update(status=new_order_status)
            else:
                items_qs.update(status=new_order_status)

        if new_order_status == 'delivered':
            try:
                from apps.commissions.models import CommissionBreakup
                from apps.commissions.utils import process_commission_breakup
                from apps.returns.models import ReturnSettings
                from datetime import timedelta
                from django.utils import timezone
                ret_settings = ReturnSettings.get()
                window_days = ret_settings.return_window_days
                for item in order.items.exclude(status__in=RETURN_EXCHANGE_STATUSES):
                    try:
                        breakup = item.commission_breakup
                        if breakup.return_window_expires is None:
                            delivered_time = item.delivered_at or timezone.now()
                            breakup.return_window_expires = delivered_time + timedelta(days=window_days)
                            breakup.save()
                    except CommissionBreakup.DoesNotExist:
                        pass

                # If the customer already marked this order satisfied, credit
                # commissions now that delivery is confirmed.
                if order.is_satisfied:
                    for item in order.items.exclude(status__in=RETURN_EXCHANGE_STATUSES):
                        try:
                            breakup = item.commission_breakup
                            if breakup.status == 'pending_window':
                                process_commission_breakup(breakup, processed_by=request.user)
                        except Exception:
                            pass
            except Exception:
                pass

        # Re-fetch with fresh item data — queryset .update() doesn't
        # invalidate the prefetch cache on the in-memory order instance.
        order = Order.objects.select_related("user").prefetch_related(
            "items",
            "items__commission_breakup",
            "items__commission_breakup__entries",
        ).get(pk=order.pk)
        return Response(OrderDetailSerializer(order).data)
