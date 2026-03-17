from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from apps.wallet.models import Wallet
from apps.products.models import (
    Category, Product, ProductImage, ProductVariant, UPADiscountSettings,
)

User = get_user_model()


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_admin(email='admin@test.com', password='admin1234'):
    return User.objects.create_user(password=password, email=email, first_name='Admin', role='admin')


def make_employee(email='emp@test.com', password='emp1234', permissions=None):
    user = User.objects.create_user(
        password=password, email=email, first_name='Emp', role='employee',
    )
    from apps.users.models import EmployeeProfile
    EmployeeProfile.objects.create(user=user, permissions=permissions or [])
    return user


def make_upa(mobile='9000000099', password='pass1234'):
    user = User.objects.create_user(
        password=password, mobile=mobile, first_name='UPA', role='upa_user',
        upa_id=f'UPA-{mobile[-4:]}',
    )
    Wallet.objects.create(user=user)
    return user


def make_category(name='Test Category'):
    return Category.objects.create(name=name)


def make_product(category, name='Test Product', sku='SKU001', mrp='100.00',
                 is_published=False, **kwargs):
    return Product.objects.create(
        name=name, sku=sku, mrp=Decimal(mrp),
        category=category, is_published=is_published, **kwargs,
    )


def make_variant(product, name='500g', sku='VAR001', mrp='100.00', stock=20):
    return ProductVariant.objects.create(
        product=product, name=name, sku=sku,
        mrp=Decimal(mrp), stock_quantity=stock,
    )


# ── Tests ──────────────────────────────────────────────────────────────────────

class ProductDefaultPublishedTest(APITestCase):
    """Create product → published=False by default."""

    def test_default_not_published(self):
        cat = make_category()
        p   = make_product(cat)
        self.assertFalse(p.is_published)


class ProductListPublicFilterTest(APITestCase):
    """GET /products/ filtering."""

    def setUp(self):
        self.cat  = make_category()
        self.pub  = make_product(self.cat, name='Published', sku='PUB001', is_published=True)
        self.unp  = make_product(self.cat, name='Unpublished', sku='UNP001', is_published=False)
        self.admin = make_admin()
        make_variant(self.pub, stock=15)
        make_variant(self.unp, stock=0, sku='VAR002')

    def test_guest_sees_only_published(self):
        resp = self.client.get('/api/v1/products/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [p['name'] for p in resp.data['results']]
        self.assertIn('Published', names)
        self.assertNotIn('Unpublished', names)

    def test_admin_sees_all(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        resp = client.get('/api/v1/products/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [p['name'] for p in resp.data['results']]
        self.assertIn('Published', names)
        self.assertIn('Unpublished', names)

    def test_filter_by_category(self):
        other_cat = make_category(name='Other')
        make_product(other_cat, name='Other Product', sku='OTH001', is_published=True)
        resp = self.client.get(f'/api/v1/products/?category={self.cat.slug}')
        names = [p['name'] for p in resp.data['results']]
        self.assertIn('Published', names)
        self.assertNotIn('Other Product', names)

    def test_search(self):
        make_product(self.cat, name='Special Item', sku='SPEC01', is_published=True)
        resp = self.client.get('/api/v1/products/?search=Special')
        names = [p['name'] for p in resp.data['results']]
        self.assertIn('Special Item', names)
        self.assertNotIn('Published', names)

    def test_in_stock_filter(self):
        # pub has stock=15, unp has stock=0
        resp = self.client.get('/api/v1/products/?in_stock=true')
        names = [p['name'] for p in resp.data['results']]
        self.assertIn('Published', names)


class ProductDetailTest(APITestCase):
    """GET /products/{slug}/ → full detail with variants + images."""

    def test_detail(self):
        cat = make_category()
        p   = make_product(cat, is_published=True)
        v   = make_variant(p)
        resp = self.client.get(f'/api/v1/products/{p.slug}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['slug'], p.slug)
        self.assertTrue(len(resp.data['variants']) >= 1)
        self.assertEqual(resp.data['variants'][0]['sku'], v.sku)


class UPAPriceTest(APITestCase):
    """UPA price logic — global %, product override %, price override."""

    def setUp(self):
        self.cat    = make_category()
        self.upa    = make_upa()
        self.client = APIClient()
        self.client.force_authenticate(user=self.upa)

        # Reset global discount
        s = UPADiscountSettings.get()
        s.global_discount_percent = Decimal('10.00')
        s.save()

    def test_global_discount(self):
        p = make_product(self.cat, mrp='200.00', is_published=True)
        make_variant(p)
        resp = self.client.get(f'/api/v1/products/{p.slug}/upa-price/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['product']['upa_price'], '180.00')  # 10% off 200

    def test_product_discount_override(self):
        p = make_product(
            self.cat, mrp='200.00', is_published=True,
            upa_discount_override=Decimal('20.00'), sku='OVRD01',
        )
        make_variant(p, sku='VOVRD01')
        resp = self.client.get(f'/api/v1/products/{p.slug}/upa-price/')
        self.assertEqual(resp.data['product']['upa_price'], '160.00')  # 20% off 200

    def test_product_price_override(self):
        p = make_product(
            self.cat, mrp='200.00', is_published=True,
            upa_price_override=Decimal('150.00'), sku='POVRD01',
        )
        make_variant(p, sku='VPOVRD01')
        resp = self.client.get(f'/api/v1/products/{p.slug}/upa-price/')
        self.assertEqual(resp.data['product']['upa_price'], '150.00')  # exact override


class UPADiscountSettingsTest(APITestCase):
    """PATCH /upa-discount/ → updates global discount, affects products."""

    def setUp(self):
        self.admin  = make_admin(email='admin2@test.com')
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_update_global_discount(self):
        resp = self.client.patch('/api/v1/upa-discount/', {'global_discount_percent': '15.00'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(resp.data['global_discount_percent']), Decimal('15.00'))

    def test_updated_discount_affects_products(self):
        self.client.patch('/api/v1/upa-discount/', {'global_discount_percent': '25.00'})
        upa = make_upa(mobile='9000000011')
        cat = make_category(name='UPATest')
        p   = make_product(cat, mrp='100.00', is_published=True, sku='UPAT01')
        make_variant(p, sku='VUPAT01')
        c = APIClient()
        c.force_authenticate(user=upa)
        resp = c.get(f'/api/v1/products/{p.slug}/upa-price/')
        self.assertEqual(resp.data['product']['upa_price'], '75.00')  # 25% off


class EmployeePermissionTest(APITestCase):
    """Employee with/without products.edit permission."""

    def setUp(self):
        self.cat = make_category(name='EmpCat')

    def test_employee_with_permission_can_create(self):
        emp = make_employee(email='emp1@test.com', permissions=['products.edit'])
        client = APIClient()
        client.force_authenticate(user=emp)
        resp = client.post('/api/v1/products/', {
            'name': 'Emp Product', 'sku': 'EMP001', 'mrp': '50.00',
            'category': str(self.cat.id),
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_employee_without_permission_gets_403(self):
        emp = make_employee(email='emp2@test.com', permissions=[])
        client = APIClient()
        client.force_authenticate(user=emp)
        resp = client.post('/api/v1/products/', {
            'name': 'Hack Product', 'sku': 'HCK001', 'mrp': '50.00',
        })
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class TogglePublishTest(APITestCase):
    """PATCH /toggle-publish/ → flips is_published."""

    def test_toggle_publish(self):
        admin  = make_admin(email='admin3@test.com')
        cat    = make_category(name='PubCat')
        p      = make_product(cat, sku='TPUB01', is_published=False)
        client = APIClient()
        client.force_authenticate(user=admin)
        resp = client.patch(f'/api/v1/products/{p.slug}/toggle-publish/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertTrue(resp.data['is_published'])
        p.refresh_from_db()
        self.assertTrue(p.is_published)


class UploadImageTest(APITestCase):
    """POST /products/{slug}/upload-image/ → image saved, is_primary set."""

    def test_upload_image(self):
        import io
        from PIL import Image as PILImage
        admin  = make_admin(email='admin4@test.com')
        cat    = make_category(name='ImgCat')
        p      = make_product(cat, sku='IMG001')
        client = APIClient()
        client.force_authenticate(user=admin)

        # Create a minimal valid image in memory
        buf = io.BytesIO()
        img = PILImage.new('RGB', (10, 10), color='red')
        img.save(buf, format='JPEG')
        buf.seek(0)
        buf.name = 'test.jpg'

        resp = client.post(
            f'/api/v1/products/{p.slug}/upload-image/',
            {'image': buf, 'alt_text': 'Test', 'is_primary': 'true'},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(resp.data['is_primary'])
        self.assertEqual(ProductImage.objects.filter(product=p).count(), 1)
