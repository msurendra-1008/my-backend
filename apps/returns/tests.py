"""
apps.returns — 13 tests covering the full return/exchange lifecycle.
"""
import io
from decimal import Decimal
from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from apps.authentication.utils import generate_upa_id
from apps.orders.models import Order, OrderItem
from apps.products.models import Category, Product, ProductVariant
from apps.returns.models import ReturnRequest, ReturnSettings
from apps.wallet.models import Wallet


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_upa(mobile="9800000001", password="pass"):
    u = User.objects.create_user(
        password=password, mobile=mobile,
        first_name="Test", role="upa_user",
        upa_id=generate_upa_id(),
    )
    Wallet.objects.get_or_create(user=u)
    return u


def make_admin(mobile="9800000099"):
    return User.objects.create_user(
        password="pass", mobile=mobile,
        first_name="Admin", role="admin",
    )


def make_variant(name="V1", mrp="500.00", upa_override="400.00", stock=10):
    cat, _ = Category.objects.get_or_create(name="Cat", slug="cat")
    prod, _ = Product.objects.get_or_create(
        slug="test-prod",
        defaults={"name": "Test Product", "category": cat, "mrp": Decimal(mrp)},
    )
    variant, _ = ProductVariant.objects.get_or_create(
        product=prod, sku=f"SKU-{name}",
        defaults={
            "name": name,
            "variant_type": "size",
            "mrp": Decimal(mrp),
            "upa_price_override": Decimal(upa_override),
            "stock_quantity": stock,
            "is_active": True,
        },
    )
    return variant


def make_delivered_item(user, qty=2, upa_price="400.00", days_ago=1):
    """Create a delivered OrderItem with delivered_at set."""
    variant = make_variant()
    order = Order.objects.create(
        user=user,
        address_name="Test", address_phone="9999999999",
        address_line="123 St", address_city="City",
        address_state="State", address_pincode="400001",
        amount_payable=Decimal(upa_price) * qty,
        payment_status="paid", order_status="delivered",
    )
    item = OrderItem.objects.create(
        order=order,
        variant=variant,
        product_name="Test Product",
        variant_name=variant.name,
        sku=variant.sku,
        mrp=Decimal("500.00"),
        upa_price=Decimal(upa_price),
        quantity=qty,
        line_total=Decimal(upa_price) * qty,
        status="delivered",
        delivered_at=timezone.now() - timedelta(days=days_ago),
    )
    return item


# ── Tests ─────────────────────────────────────────────────────────────────────

class ReturnRequestTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user   = make_upa(mobile="9800000001")
        self.admin  = make_admin()
        ReturnSettings.objects.all().delete()
        ReturnSettings.objects.create(
            return_window_days=7,
            predefined_reasons=["Damaged product", "Changed my mind"],
        )

    # 1 ──────────────────────────────────────────────────────────────────────
    def test_user_can_raise_return_for_delivered_item(self):
        """Raising a return for a delivered item sets OrderItem → return_requested."""
        self.client.force_authenticate(user=self.user)
        item = make_delivered_item(self.user)

        resp = self.client.post("/api/v1/returns/", {
            "order_item_id": str(item.id),
            "request_type":  "return",
            "return_qty":    1,
            "reason":        "Changed my mind",
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        item.refresh_from_db()
        self.assertEqual(item.status, "return_requested")
        self.assertEqual(ReturnRequest.objects.count(), 1)

    # 2 ──────────────────────────────────────────────────────────────────────
    def test_cannot_raise_for_non_delivered_item(self):
        """Return request on a non-delivered item must return 400."""
        self.client.force_authenticate(user=self.user)
        variant = make_variant(name="V2")
        order = Order.objects.create(
            user=self.user,
            address_name="T", address_phone="9", address_line="L",
            address_city="C", address_state="S", address_pincode="0",
            amount_payable=Decimal("400"), payment_status="paid",
            order_status="shipped",
        )
        item = OrderItem.objects.create(
            order=order, variant=variant,
            product_name="P", variant_name="V2", sku=variant.sku,
            mrp=Decimal("500"), upa_price=Decimal("400"),
            quantity=1, line_total=Decimal("400"), status="shipped",
        )
        resp = self.client.post("/api/v1/returns/", {
            "order_item_id": str(item.id),
            "request_type":  "return",
            "return_qty":    1,
            "reason":        "Damaged product",
        })
        self.assertEqual(resp.status_code, 400)

    # 3 ──────────────────────────────────────────────────────────────────────
    def test_cannot_raise_outside_return_window(self):
        """Return request outside the window (8 days ago) must return 400."""
        self.client.force_authenticate(user=self.user)
        item = make_delivered_item(self.user, days_ago=8)  # 8 days > window of 7

        resp = self.client.post("/api/v1/returns/", {
            "order_item_id": str(item.id),
            "request_type":  "return",
            "return_qty":    1,
            "reason":        "Changed my mind",
        })
        self.assertEqual(resp.status_code, 400)

    # 4 ──────────────────────────────────────────────────────────────────────
    def test_cannot_raise_duplicate_active_request(self):
        """A second request for the same item (while first is active) returns 400."""
        self.client.force_authenticate(user=self.user)
        item = make_delivered_item(self.user)

        self.client.post("/api/v1/returns/", {
            "order_item_id": str(item.id),
            "request_type":  "return",
            "return_qty":    1,
            "reason":        "Changed my mind",
        })
        # Second attempt
        resp = self.client.post("/api/v1/returns/", {
            "order_item_id": str(item.id),
            "request_type":  "return",
            "return_qty":    1,
            "reason":        "Changed my mind",
        })
        self.assertEqual(resp.status_code, 400)

    # 5 ──────────────────────────────────────────────────────────────────────
    def test_return_qty_exceeds_ordered_qty(self):
        """return_qty > item.quantity must return 400."""
        self.client.force_authenticate(user=self.user)
        item = make_delivered_item(self.user, qty=1)

        resp = self.client.post("/api/v1/returns/", {
            "order_item_id": str(item.id),
            "request_type":  "return",
            "return_qty":    5,
            "reason":        "Changed my mind",
        })
        self.assertEqual(resp.status_code, 400)

    # 6 ──────────────────────────────────────────────────────────────────────
    def test_exchange_with_out_of_stock_variant(self):
        """Exchange request with an out-of-stock variant must return 400."""
        self.client.force_authenticate(user=self.user)
        item = make_delivered_item(self.user, qty=1)

        # Create a second variant of the same product with 0 stock
        other_variant, _ = ProductVariant.objects.get_or_create(
            product=item.variant.product, sku="SKU-OOS",
            defaults={
                "name": "OOS Variant", "variant_type": "size",
                "mrp": Decimal("500"), "upa_price_override": Decimal("400"),
                "stock_quantity": 0, "is_active": True,
            },
        )
        resp = self.client.post("/api/v1/returns/", {
            "order_item_id":      str(item.id),
            "request_type":       "exchange",
            "return_qty":         1,
            "exchange_variant_id": str(other_variant.id),
            "reason":             "Size/variant issue",
        })
        self.assertEqual(resp.status_code, 400)

    # 7 ──────────────────────────────────────────────────────────────────────
    def test_exchange_variant_must_be_same_product(self):
        """Exchange with a variant from a different product returns 400."""
        self.client.force_authenticate(user=self.user)
        item = make_delivered_item(self.user, qty=1)

        # Different product — supply a unique sku so it doesn't conflict
        cat, _ = Category.objects.get_or_create(name="Cat2", slug="cat2")
        other_prod = Product.objects.create(
            name="Other Product", slug="other-prod-7",
            category=cat, mrp=Decimal("500"), sku="PROD-OTHER-7",
        )
        other_variant = ProductVariant.objects.create(
            product=other_prod, sku="SKU-DIFF-PROD",
            name="Other V", variant_type="size",
            mrp=Decimal("500"), upa_price_override=Decimal("400"),
            stock_quantity=10, is_active=True,
        )
        resp = self.client.post("/api/v1/returns/", {
            "order_item_id":      str(item.id),
            "request_type":       "exchange",
            "return_qty":         1,
            "exchange_variant_id": str(other_variant.id),
            "reason":             "Size/variant issue",
        })
        self.assertEqual(resp.status_code, 400)

    # 8 ──────────────────────────────────────────────────────────────────────
    def test_upload_photo_saved_and_max_3_enforced(self):
        """Photos are saved; uploading a 4th returns 400."""
        self.client.force_authenticate(user=self.user)
        item = make_delivered_item(self.user)
        # Raise request first
        resp = self.client.post("/api/v1/returns/", {
            "order_item_id": str(item.id),
            "request_type":  "return",
            "return_qty":    1,
            "reason":        "Damaged product",
        })
        rr_id = resp.data["id"]

        url = f"/api/v1/returns/{rr_id}/upload-photo/"
        for i in range(3):
            img = SimpleUploadedFile(
                f"test{i}.jpg",
                b"\xff\xd8\xff\xe0" + b"\x00" * 10,
                content_type="image/jpeg",
            )
            r = self.client.post(url, {"photo": img}, format="multipart")
            self.assertEqual(r.status_code, 201, f"Upload {i+1} failed: {r.data}")

        # 4th photo should fail
        img4 = SimpleUploadedFile("test4.jpg", b"\xff\xd8\xff\xe0", content_type="image/jpeg")
        r4 = self.client.post(url, {"photo": img4}, format="multipart")
        self.assertEqual(r4.status_code, 400)

    # 9 ──────────────────────────────────────────────────────────────────────
    def test_admin_approves_return_credits_wallet_restocks(self):
        """Approve return → wallet credited, stock restocked, item → refunded."""
        self.client.force_authenticate(user=self.user)
        item = make_delivered_item(self.user, qty=2, upa_price="400.00")

        stock_before = item.variant.stock_quantity

        resp = self.client.post("/api/v1/returns/", {
            "order_item_id": str(item.id),
            "request_type":  "return",
            "return_qty":    2,
            "reason":        "Damaged product",
        })
        rr_id = resp.data["id"]

        # Admin approves
        self.client.force_authenticate(user=self.admin)
        resp2 = self.client.patch(f"/api/v1/returns/{rr_id}/approve/")
        self.assertEqual(resp2.status_code, 200, resp2.data)

        # Wallet credited: 400.00 × 2 = 800.00
        wallet = Wallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, Decimal("800.00"))

        # Stock restocked
        item.variant.refresh_from_db()
        self.assertEqual(item.variant.stock_quantity, stock_before + 2)

        # OrderItem → refunded
        item.refresh_from_db()
        self.assertEqual(item.status, "refunded")

    # 10 ─────────────────────────────────────────────────────────────────────
    def test_admin_approves_exchange_adjusts_stock_both_ways(self):
        """Approve exchange → old stock up, new stock down, item → exchanged."""
        self.client.force_authenticate(user=self.user)
        item = make_delivered_item(self.user, qty=1)

        # Create a second variant with sufficient stock
        other_variant, _ = ProductVariant.objects.get_or_create(
            product=item.variant.product, sku="SKU-EX",
            defaults={
                "name": "Exchange V", "variant_type": "size",
                "mrp": Decimal("500"), "upa_price_override": Decimal("400"),
                "stock_quantity": 5, "is_active": True,
            },
        )
        old_stock_before  = item.variant.stock_quantity
        new_stock_before  = other_variant.stock_quantity

        resp = self.client.post("/api/v1/returns/", {
            "order_item_id":      str(item.id),
            "request_type":       "exchange",
            "return_qty":         1,
            "exchange_variant_id": str(other_variant.id),
            "reason":             "Size/variant issue",
        })
        rr_id = resp.data["id"]

        self.client.force_authenticate(user=self.admin)
        resp2 = self.client.patch(f"/api/v1/returns/{rr_id}/approve/")
        self.assertEqual(resp2.status_code, 200, resp2.data)

        item.variant.refresh_from_db()
        other_variant.refresh_from_db()
        self.assertEqual(item.variant.stock_quantity, old_stock_before + 1)
        self.assertEqual(other_variant.stock_quantity, new_stock_before - 1)

        item.refresh_from_db()
        self.assertEqual(item.status, "exchanged")

    # 11 ─────────────────────────────────────────────────────────────────────
    def test_admin_rejects_reverts_item_to_delivered(self):
        """Reject return → OrderItem status reverts to 'delivered'."""
        self.client.force_authenticate(user=self.user)
        item = make_delivered_item(self.user)

        resp = self.client.post("/api/v1/returns/", {
            "order_item_id": str(item.id),
            "request_type":  "return",
            "return_qty":    1,
            "reason":        "Changed my mind",
        })
        rr_id = resp.data["id"]

        self.client.force_authenticate(user=self.admin)
        resp2 = self.client.patch(f"/api/v1/returns/{rr_id}/reject/", {
            "admin_notes": "Request does not meet criteria."
        }, format="json")
        self.assertEqual(resp2.status_code, 200, resp2.data)

        item.refresh_from_db()
        self.assertEqual(item.status, "delivered")

        rr = ReturnRequest.objects.get(pk=rr_id)
        self.assertEqual(rr.status, "rejected")

    # 12 ─────────────────────────────────────────────────────────────────────
    def test_refund_amount_is_upa_price_x_return_qty(self):
        """Refund uses upa_price at checkout, not current product price."""
        self.client.force_authenticate(user=self.user)
        item = make_delivered_item(self.user, qty=3, upa_price="350.00")

        # Mutate product price to simulate a price change
        item.variant.upa_price_override = Decimal("999.00")
        item.variant.save(update_fields=["upa_price_override"])

        resp = self.client.post("/api/v1/returns/", {
            "order_item_id": str(item.id),
            "request_type":  "return",
            "return_qty":    3,
            "reason":        "Damaged product",
        })
        rr_id = resp.data["id"]

        self.client.force_authenticate(user=self.admin)
        self.client.patch(f"/api/v1/returns/{rr_id}/approve/")

        wallet = Wallet.objects.get(user=self.user)
        # Should be 350 × 3 = 1050, NOT 999 × 3
        self.assertEqual(wallet.balance, Decimal("1050.00"))
