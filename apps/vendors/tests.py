"""
apps.vendors — tests covering vendor registration, auth, profile, admin flow, and vendor products.
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from apps.products.models import Category, Product
from .models import VendorDocument, VendorProfile, VendorProduct


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_category(name="Textiles"):
    cat, _ = Category.objects.get_or_create(name=name, defaults={'slug': name.lower()})
    return cat


def make_admin(mobile="9900000099"):
    return User.objects.create_user(password="pass", mobile=mobile, first_name="Admin", role="admin")


REGISTER_DATA = {
    "company_name":  "Acme Supplies",
    "gst_number":    "22AAAAA0000A1Z5",
    "contact_name":  "Raj Kumar",
    "mobile":        "9900000001",
    "email":         "raj@acme.com",
    "address_line1": "123 Market Street",
    "city":          "Mumbai",
    "state":         "Maharashtra",
    "pincode":       "400001",
    "password":      "secret123",
}


def register_vendor(client, extra=None):
    cat = make_category()
    data = {**REGISTER_DATA, "category_ids": [str(cat.id)]}
    if extra:
        data.update(extra)
    return client.post("/api/v1/vendor/register/", data, format="json")


def login_vendor(client, mobile="9900000001", password="secret123"):
    return client.post("/api/v1/vendor/login/", {"identifier": mobile, "password": password}, format="json")


# ── Tests ─────────────────────────────────────────────────────────────────────

class VendorRegisterTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_creates_user_and_profile(self):
        """Vendor registers → User with role=vendor, VendorProfile with status=pending"""
        res = register_vendor(self.client)
        self.assertEqual(res.status_code, 201)
        user = User.objects.get(mobile="9900000001")
        self.assertEqual(user.role, "vendor")
        profile = user.vendor_profile
        self.assertEqual(profile.status, "pending")
        self.assertEqual(profile.company_name, "Acme Supplies")

    def test_duplicate_gst_returns_400(self):
        """Duplicate GST number → 400"""
        register_vendor(self.client)
        res = register_vendor(self.client, extra={"mobile": "9900000002", "email": "other@acme.com"})
        self.assertEqual(res.status_code, 400)

    def test_no_category_returns_400(self):
        """No category selected → 400"""
        data = {**REGISTER_DATA, "category_ids": []}
        res = self.client.post("/api/v1/vendor/register/", data, format="json")
        self.assertEqual(res.status_code, 400)


class VendorLoginTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        register_vendor(self.client)

    def test_login_returns_tokens_and_profile(self):
        """Vendor login → returns tokens + profile with status=pending"""
        res = login_vendor(self.client)
        self.assertEqual(res.status_code, 200)
        self.assertIn("access", res.data)
        self.assertIn("profile", res.data)
        self.assertEqual(res.data["profile"]["status"], "pending")

    def test_login_wrong_password_returns_400(self):
        """Vendor login wrong password → 400"""
        res = login_vendor(self.client, password="wrongpass")
        self.assertEqual(res.status_code, 400)


class VendorProfileTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        register_vendor(self.client)
        res = login_vendor(self.client)
        self.token = res.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

    def test_get_me_as_vendor(self):
        """GET /vendor/me/ as vendor → own profile"""
        res = self.client.get("/api/v1/vendor/profile/me/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["company_name"], "Acme Supplies")

    def test_get_me_as_upa_returns_403(self):
        """GET /vendor/me/ as UPA user → 403"""
        upa = User.objects.create_user(password="pass", mobile="9900001111", role="upa_user")
        c = APIClient()
        from rest_framework_simplejwt.tokens import RefreshToken
        token = str(RefreshToken.for_user(upa).access_token)
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        res = c.get("/api/v1/vendor/profile/me/")
        self.assertEqual(res.status_code, 403)

    def test_vendor_uploads_document(self):
        """Vendor uploads document → saved correctly"""
        dummy = SimpleUploadedFile("test.pdf", b"file content", content_type="application/pdf")
        res = self.client.post(
            "/api/v1/vendor/profile/me/documents/",
            {"label": "GST Certificate", "file": dummy},
            format="multipart",
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["label"], "GST Certificate")

    def test_vendor_updates_profile(self):
        """Vendor updates contact/address → saved"""
        res = self.client.patch(
            "/api/v1/vendor/profile/me/update/",
            {"contact_name": "Ramesh Kumar", "city": "Pune"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["contact_name"], "Ramesh Kumar")
        self.assertEqual(res.data["city"], "Pune")

    def test_vendor_cannot_change_company_name(self):
        """Vendor cannot change company_name → 400"""
        res = self.client.patch(
            "/api/v1/vendor/profile/me/update/",
            {"company_name": "Hacked Corp"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)

    def test_vendor_cannot_change_gst_number(self):
        """Vendor cannot change gst_number → 400"""
        res = self.client.patch(
            "/api/v1/vendor/profile/me/update/",
            {"gst_number": "99BBBBB0000B2Z6"},
            format="json",
        )
        self.assertEqual(res.status_code, 400)


class VendorAdminTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        register_vendor(self.client)
        self.admin = make_admin()
        from rest_framework_simplejwt.tokens import RefreshToken
        token = str(RefreshToken.for_user(self.admin).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.vendor_id = VendorProfile.objects.first().id

    def test_admin_list_vendors(self):
        """GET /vendor/admin/ as admin → paginated vendor list"""
        res = self.client.get("/api/v1/vendor/admin/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("results", res.data)
        self.assertIn("stats", res.data)

    def test_vendor_cannot_access_admin_list(self):
        """GET /vendor/admin/ as vendor → 403"""
        register_vendor(self.client.__class__(), extra={"mobile": "9900002222", "email": "v2@acme.com", "gst_number": "33CCCCC0000C3Z7"})
        c = APIClient()
        res2 = login_vendor(c, mobile="9900002222")
        vendor_token = res2.data["access"] if res2.status_code == 200 else None
        # Use original registration client to get vendor token
        c2 = APIClient()
        register_vendor(c2, extra={"mobile": "9900003333", "email": "v3@acme.com", "gst_number": "44DDDDD0000D4Z8"})
        lr = login_vendor(c2, mobile="9900003333")
        c2.credentials(HTTP_AUTHORIZATION=f"Bearer {lr.data['access']}")
        res = c2.get("/api/v1/vendor/admin/")
        self.assertEqual(res.status_code, 403)

    def test_admin_approves_vendor(self):
        """Admin approves vendor → status=approved, approved_by set"""
        res = self.client.patch(f"/api/v1/vendor/admin/{self.vendor_id}/approve/", {}, format="json")
        self.assertEqual(res.status_code, 200)
        profile = VendorProfile.objects.get(pk=self.vendor_id)
        self.assertEqual(profile.status, "approved")
        self.assertEqual(profile.approved_by, self.admin)

    def test_admin_reject_without_reason_returns_400(self):
        """Admin rejects without reason → 400"""
        res = self.client.patch(f"/api/v1/vendor/admin/{self.vendor_id}/reject/", {}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_admin_rejects_with_reason(self):
        """Admin rejects with reason → status=rejected"""
        res = self.client.patch(
            f"/api/v1/vendor/admin/{self.vendor_id}/reject/",
            {"reason": "Incomplete documentation provided."},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        profile = VendorProfile.objects.get(pk=self.vendor_id)
        self.assertEqual(profile.status, "rejected")

    def test_admin_requests_docs(self):
        """Admin requests docs → status=docs_requested, note visible"""
        res = self.client.patch(
            f"/api/v1/vendor/admin/{self.vendor_id}/request-docs/",
            {"admin_notes": "Please upload PAN card copy."},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        profile = VendorProfile.objects.get(pk=self.vendor_id)
        self.assertEqual(profile.status, "docs_requested")
        self.assertEqual(profile.admin_notes, "Please upload PAN card copy.")


# ── Vendor Product Tests ───────────────────────────────────────────────────────

PRODUCT_DATA = {
    "name":        "Premium Cotton Fabric",
    "description": "High quality cotton",
    "sku":         "FABRIC-001",
    "variants": [
        {"name": "White 1m", "variant_type": "size", "sku": "FABRIC-001-W", "mrp": "250.00", "is_active": True},
    ],
}


def make_approved_vendor(mobile="9800000001", gst="55EEEEE0000E5Z9", email="vendor@test.com"):
    """Creates a vendor user and approves them directly."""
    cat = Category.objects.get_or_create(name="Fabrics", defaults={"slug": "fabrics"})[0]
    user = User.objects.create_user(password="pass", mobile=mobile, email=email, role="vendor",
                                    first_name="Test", last_name="Vendor")
    profile = VendorProfile.objects.create(
        user=user, company_name="Test Co", gst_number=gst,
        contact_name="Test Vendor", address_line1="123 Road",
        city="Delhi", state="Delhi", pincode="110001", status="approved",
    )
    profile.categories.add(cat)
    return profile


def vendor_token(profile):
    return str(RefreshToken.for_user(profile.user).access_token)


class VendorProductCreateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.profile = make_approved_vendor()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {vendor_token(self.profile)}")

    def test_approved_vendor_can_create_product(self):
        """Approved vendor submits a product → 201, status=pending_approval"""
        data = {**PRODUCT_DATA, "category_name": "Fabrics"}
        res = self.client.post("/api/v1/vendor/products/", data, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["status"], "pending_approval")
        self.assertEqual(VendorProduct.objects.count(), 1)

    def test_pending_vendor_cannot_create_product(self):
        """Pending (not approved) vendor → 403"""
        user2 = User.objects.create_user(password="pass", mobile="9800000002", role="vendor", first_name="P", last_name="V")
        cat = Category.objects.first()
        profile2 = VendorProfile.objects.create(
            user=user2, company_name="Pending Co", gst_number="66FFFFF0000F6Z0",
            contact_name="P V", address_line1="1 Road", city="Delhi", state="Delhi",
            pincode="110001", status="pending",
        )
        profile2.categories.add(cat)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {vendor_token(profile2)}")
        res = c.post("/api/v1/vendor/products/", {**PRODUCT_DATA, "category_name": "Fabrics"}, format="json")
        self.assertEqual(res.status_code, 403)

    def test_product_requires_at_least_one_variant(self):
        """Submitting product with no variants → 400"""
        data = {**PRODUCT_DATA, "variants": [], "category_name": "Fabrics"}
        res = self.client.post("/api/v1/vendor/products/", data, format="json")
        self.assertEqual(res.status_code, 400)
        self.assertIn("variants", res.data)

    def test_new_category_created_inline(self):
        """Submitting a product with unknown category_name → new Category created"""
        data = {**PRODUCT_DATA, "sku": "FABRIC-099", "variants": [
            {"name": "Red 1m", "variant_type": "colour", "sku": "FABRIC-099-R", "mrp": "300.00", "is_active": True}
        ], "category_name": "Unique Brand New Category"}
        res = self.client.post("/api/v1/vendor/products/", data, format="json")
        self.assertEqual(res.status_code, 201)
        self.assertTrue(Category.objects.filter(name__iexact="Unique Brand New Category").exists())

    def test_vendor_can_list_own_products(self):
        """Vendor lists own products → only own products returned"""
        self.client.post("/api/v1/vendor/products/", {**PRODUCT_DATA, "category_name": "Fabrics"}, format="json")
        res = self.client.get("/api/v1/vendor/products/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["count"], 1)

    def test_edit_approved_product_resets_to_pending(self):
        """Editing an approved product → status resets to pending_approval"""
        res = self.client.post("/api/v1/vendor/products/", {**PRODUCT_DATA, "category_name": "Fabrics"}, format="json")
        pid = res.data["id"]
        vp = VendorProduct.objects.get(pk=pid)
        vp.status = "approved"
        vp.save()
        res2 = self.client.patch(f"/api/v1/vendor/products/{pid}/", {"name": "Updated Name"}, format="json")
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.data["status"], "pending_approval")

    def test_deactivate_and_reactivate_product(self):
        """Vendor deactivates product → not_continued; reactivates → pending_approval"""
        res = self.client.post("/api/v1/vendor/products/", {**PRODUCT_DATA, "category_name": "Fabrics"}, format="json")
        pid = res.data["id"]
        res2 = self.client.patch(f"/api/v1/vendor/products/{pid}/deactivate/", {}, format="json")
        self.assertEqual(res2.data["status"], "not_continued")
        res3 = self.client.patch(f"/api/v1/vendor/products/{pid}/reactivate/", {}, format="json")
        self.assertEqual(res3.data["status"], "pending_approval")


class VendorProductAdminTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.profile = make_approved_vendor()
        # Create a vendor product
        vc = APIClient()
        vc.credentials(HTTP_AUTHORIZATION=f"Bearer {vendor_token(self.profile)}")
        res = vc.post("/api/v1/vendor/products/", {**PRODUCT_DATA, "category_name": "Fabrics"}, format="json")
        self.product_id = res.data["id"]
        # Admin client
        self.admin = User.objects.create_user(password="pass", mobile="9900009999", role="admin", first_name="Admin")
        admin_tok = str(RefreshToken.for_user(self.admin).access_token)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {admin_tok}")

    def test_admin_list_vendor_products(self):
        """Admin lists vendor products → paginated + stats"""
        res = self.client.get("/api/v1/vendor/admin-products/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("stats", res.data)
        self.assertEqual(res.data["count"], 1)

    def test_admin_approve_creates_catalog_product(self):
        """Admin approves vendor product → catalog Product created, is_published=False, stock=0"""
        res = self.client.patch(f"/api/v1/vendor/admin-products/{self.product_id}/approve/", {}, format="json")
        self.assertEqual(res.status_code, 200)
        vp = VendorProduct.objects.get(pk=self.product_id)
        self.assertEqual(vp.status, "approved")
        self.assertIsNotNone(vp.catalog_product)
        cat_product = vp.catalog_product
        self.assertFalse(cat_product.is_published)
        self.assertEqual(cat_product.variants.first().stock_quantity, 0)
        self.assertEqual(str(res.data["catalog_product_id"]), str(cat_product.id))

    def test_admin_reject_without_reason_returns_400(self):
        """Admin rejects without reason → 400"""
        res = self.client.patch(f"/api/v1/vendor/admin-products/{self.product_id}/reject/", {}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_admin_reject_with_reason(self):
        """Admin rejects with reason → status=rejected"""
        res = self.client.patch(
            f"/api/v1/vendor/admin-products/{self.product_id}/reject/",
            {"reason": "Poor quality images."},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        vp = VendorProduct.objects.get(pk=self.product_id)
        self.assertEqual(vp.status, "rejected")
        self.assertEqual(vp.rejection_reason, "Poor quality images.")
