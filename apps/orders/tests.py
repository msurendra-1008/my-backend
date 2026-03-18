from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from accounts.models import User
from apps.upa_tree.models import UPATree
from apps.wallet.models import Wallet
from apps.products.models import Category, Product, ProductVariant
from apps.orders.models import Address, Cart, CartItem, Order


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_upa(mobile="9000000001", password="testpass123"):
    from apps.authentication.utils import generate_upa_id
    u = User.objects.create_user(
        password=password, mobile=mobile,
        first_name="Test", role="upa_user",
        upa_id=generate_upa_id(),
    )
    Wallet.objects.get_or_create(user=u)
    UPATree.objects.get_or_create(user=u, defaults={"parent_user": None, "leg": None})
    return u


def make_variant(name="Variant A", mrp="100.00", stock=10):
    cat, _ = Category.objects.get_or_create(name="TestCat", slug="testcat")
    prod, _ = Product.objects.get_or_create(
        slug="test-product",
        defaults={"name": "Test Product", "category": cat, "mrp": Decimal(mrp)},
    )
    variant, _ = ProductVariant.objects.get_or_create(
        product=prod, sku=f"SKU-{name}",
        defaults={
            "name": name,
            "variant_type": "size",
            "mrp": Decimal(mrp),
            "stock_quantity": stock,
            "is_active": True,
        },
    )
    return variant


def add_to_cart(user, variant, qty=1):
    cart, _ = Cart.objects.get_or_create(user=user)
    item, created = CartItem.objects.get_or_create(cart=cart, variant=variant)
    if not created:
        item.quantity += qty
    else:
        item.quantity = qty
    item.save()
    return cart


def make_address(user):
    return Address.objects.create(
        user=user,
        name="Test User",
        phone="9000000001",
        address_line="123 Main St",
        city="Mumbai",
        state="Maharashtra",
        pincode="400001",
        is_default=True,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class CheckoutInitiateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_upa(mobile="9100000001")
        self.client.force_authenticate(user=self.user)
        self.variant = make_variant(name="Size S", mrp="200.00", stock=5)
        self.address = make_address(self.user)
        add_to_cart(self.user, self.variant, qty=1)

    def test_initiate_creates_draft_order(self):
        """Initiate must create a pending draft Order and return internal_order_id."""
        resp = self.client.post("/api/v1/checkout/initiate/", {
            "address_id": str(self.address.id),
            "wallet_amount": "0",
        })
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIn("internal_order_id", resp.data)

        order = Order.objects.get(pk=resp.data["internal_order_id"])
        self.assertEqual(order.user, self.user)
        self.assertEqual(order.payment_status, "pending")
        self.assertEqual(order.order_status, "pending")

    def test_initiate_empty_cart_returns_400(self):
        Cart.objects.filter(user=self.user).delete()
        resp = self.client.post("/api/v1/checkout/initiate/", {
            "address_id": str(self.address.id),
            "wallet_amount": "0",
        })
        self.assertEqual(resp.status_code, 400)

    def test_initiate_unauthenticated_returns_401(self):
        self.client.logout()
        resp = self.client.post("/api/v1/checkout/initiate/", {
            "address_id": str(self.address.id),
            "wallet_amount": "0",
        })
        self.assertIn(resp.status_code, [401, 403])


class CheckoutConfirmTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_upa(mobile="9200000001")
        self.client.force_authenticate(user=self.user)
        self.variant = make_variant(name="Size M", mrp="300.00", stock=10)
        self.address = make_address(self.user)
        add_to_cart(self.user, self.variant, qty=2)

    def _initiate(self, wallet_amount="0"):
        resp = self.client.post("/api/v1/checkout/initiate/", {
            "address_id": str(self.address.id),
            "wallet_amount": wallet_amount,
        })
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.data

    def test_confirm_updates_order_status_to_confirmed(self):
        """After confirm, order.payment_status='paid' and order.order_status='confirmed'."""
        init = self._initiate()
        internal_order_id = init["internal_order_id"]

        # Verify draft order starts pending
        draft = Order.objects.get(pk=internal_order_id)
        self.assertEqual(draft.payment_status, "pending")
        self.assertEqual(draft.order_status, "pending")

        resp = self.client.post("/api/v1/checkout/confirm/", {
            "internal_order_id":   internal_order_id,
            "address_id":          str(self.address.id),
            "wallet_amount":       "0",
            "razorpay_order_id":   init.get("razorpay_order_id", ""),
            "razorpay_payment_id": "mock_pay_test123",
            "razorpay_signature":  "mock_sig",
        })
        self.assertEqual(resp.status_code, 201, resp.data)

        # Fetch updated order from DB and verify correct row was updated
        order = Order.objects.get(pk=internal_order_id)
        self.assertEqual(order.payment_status, "paid",
                         f"Expected payment_status='paid', got {order.payment_status!r}")
        self.assertEqual(order.order_status, "confirmed",
                         f"Expected order_status='confirmed', got {order.order_status!r}")
        self.assertEqual(order.razorpay_payment_id, "mock_pay_test123")

    def test_confirm_does_not_create_extra_order(self):
        """Confirm must update the existing draft, not create a second Order."""
        before_count = Order.objects.filter(user=self.user).count()
        init = self._initiate()

        self.client.post("/api/v1/checkout/confirm/", {
            "internal_order_id":   init["internal_order_id"],
            "address_id":          str(self.address.id),
            "wallet_amount":       "0",
            "razorpay_order_id":   init.get("razorpay_order_id", ""),
            "razorpay_payment_id": "mock_pay_dup",
            "razorpay_signature":  "mock_sig",
        })

        after_count = Order.objects.filter(user=self.user).count()
        # Initiate created 1 draft; confirm must NOT create another
        self.assertEqual(after_count, before_count + 1)

    def test_confirm_deducts_stock(self):
        """Stock must be reduced by the quantity ordered."""
        stock_before = self.variant.stock_quantity  # 10
        init = self._initiate()
        self.client.post("/api/v1/checkout/confirm/", {
            "internal_order_id":   init["internal_order_id"],
            "address_id":          str(self.address.id),
            "wallet_amount":       "0",
            "razorpay_order_id":   init.get("razorpay_order_id", ""),
            "razorpay_payment_id": "mock_pay_stock",
            "razorpay_signature":  "mock_sig",
        })
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, stock_before - 2)

    def test_confirm_clears_cart(self):
        """Cart must be empty after a successful confirm."""
        init = self._initiate()
        self.client.post("/api/v1/checkout/confirm/", {
            "internal_order_id":   init["internal_order_id"],
            "address_id":          str(self.address.id),
            "wallet_amount":       "0",
            "razorpay_order_id":   init.get("razorpay_order_id", ""),
            "razorpay_payment_id": "mock_pay_cart",
            "razorpay_signature":  "mock_sig",
        })
        cart = Cart.objects.get(user=self.user)
        self.assertEqual(cart.items.count(), 0)

    def test_confirm_wrong_internal_order_id_returns_404(self):
        """Confirm with a random UUID must return 404."""
        import uuid
        self._initiate()
        resp = self.client.post("/api/v1/checkout/confirm/", {
            "internal_order_id":   str(uuid.uuid4()),
            "address_id":          str(self.address.id),
            "wallet_amount":       "0",
            "razorpay_order_id":   "mock_order_xyz",
            "razorpay_payment_id": "mock_pay_bad",
            "razorpay_signature":  "mock_sig",
        })
        self.assertEqual(resp.status_code, 404)

    def test_confirm_creates_order_items(self):
        """OrderItems must be created from the current cart."""
        init = self._initiate()
        resp = self.client.post("/api/v1/checkout/confirm/", {
            "internal_order_id":   init["internal_order_id"],
            "address_id":          str(self.address.id),
            "wallet_amount":       "0",
            "razorpay_order_id":   init.get("razorpay_order_id", ""),
            "razorpay_payment_id": "mock_pay_items",
            "razorpay_signature":  "mock_sig",
        })
        self.assertEqual(resp.status_code, 201)
        order = Order.objects.get(pk=init["internal_order_id"])
        self.assertEqual(order.items.count(), 1)
        item = order.items.first()
        self.assertEqual(item.quantity, 2)


class CheckoutWithWalletTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = make_upa(mobile="9300000001")
        self.wallet = Wallet.objects.get(user=self.user)
        self.wallet.balance = Decimal("500.00")
        self.wallet.save()
        self.client.force_authenticate(user=self.user)
        self.variant = make_variant(name="Size L", mrp="400.00", stock=3)
        self.address = make_address(self.user)
        add_to_cart(self.user, self.variant, qty=1)

    def test_wallet_only_payment_debits_wallet(self):
        """Full wallet payment must debit the wallet and mark order paid."""
        init_resp = self.client.post("/api/v1/checkout/initiate/", {
            "address_id":   str(self.address.id),
            "wallet_amount": "400.00",
        })
        self.assertEqual(init_resp.status_code, 200, init_resp.data)
        # razorpay_amount should be 0 (wallet covers full amount)
        self.assertEqual(init_resp.data["razorpay_amount"], "0.00")

        resp = self.client.post("/api/v1/checkout/confirm/", {
            "internal_order_id":   init_resp.data["internal_order_id"],
            "address_id":          str(self.address.id),
            "wallet_amount":       "400.00",
            "razorpay_order_id":   "",
            "razorpay_payment_id": "wallet_only",
            "razorpay_signature":  "wallet_only",
        })
        self.assertEqual(resp.status_code, 201, resp.data)

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.balance, Decimal("100.00"))

        order = Order.objects.get(pk=init_resp.data["internal_order_id"])
        self.assertEqual(order.payment_status, "paid")
        self.assertEqual(order.order_status, "confirmed")
        self.assertEqual(order.wallet_used, Decimal("400.00"))
