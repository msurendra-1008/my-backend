"""
apps.vendors — 16 tests covering the vendor registration, auth, profile, and admin flow.
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from apps.products.models import Category
from .models import VendorDocument, VendorProfile


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
