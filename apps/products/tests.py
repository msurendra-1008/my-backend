from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

from apps.wallet.models import Wallet
from apps.products.models import (
    Brand, Category, Product, ProductImage, ProductVariant, UPADiscountSettings,
    generate_product_sku, generate_variant_sku, build_variant_combinations,
)

User = get_user_model()


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_admin(email='admin@test.com', password='admin1234'):
    return User.objects.create_user(
        password=password, email=email, first_name='Admin', role='admin',
    )


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


def make_category_hierarchy(prefix='Test'):
    """Create a full 4-level chain and return all 4 objects."""
    group = Category.objects.create(name=f'{prefix} Group',           depth=0, short_code=prefix[:2].upper())
    parent = Category.objects.create(name=f'{prefix} Parent',         depth=1, short_code=f'{prefix[:2]}P', parent=group)
    sub    = Category.objects.create(name=f'{prefix} Sub',            depth=2, short_code=f'{prefix[:2]}S', parent=parent)
    leaf   = Category.objects.create(
        name=f'{prefix} Category', depth=3,
        short_code=f'{prefix[:2]}C', parent=sub,
        field_schema={
            'product_fields': [
                {'key': 'brand_detail', 'label': 'Brand Detail', 'type': 'text', 'required': False},
                {'key': 'grade',        'label': 'Grade',        'type': 'select', 'required': True,
                 'options': ['A', 'B', 'C']},
            ],
            'variant_attributes': [
                {'key': 'weight', 'label': 'Weight', 'type': 'select',
                 'options': ['500g', '1kg', '2kg', '5kg']},
            ],
        },
    )
    return group, parent, sub, leaf


def make_brand(name='Test Brand'):
    return Brand.objects.create(name=name)


def make_category(name='Test Category', depth=0):
    return Category.objects.create(name=name, depth=depth)


def make_product(category, name='Test Product', sku='SKU001', mrp='100.00',
                 is_published=False, **kwargs):
    return Product.objects.create(
        name=name, sku=sku, mrp=Decimal(mrp),
        category=category, is_published=is_published, **kwargs,
    )


def make_variant(product, name='500g', sku='VAR001', mrp='100.00', stock=20, attrs=None):
    return ProductVariant.objects.create(
        product=product, name=name, sku=sku,
        mrp=Decimal(mrp), stock_quantity=stock,
        attributes=attrs or {},
    )


# ── Category Hierarchy Tests ──────────────────────────────────────────────────

class CategoryDepthValidationTest(APITestCase):
    """Category creation must respect parent-depth rules."""

    def setUp(self):
        self.admin  = make_admin()
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.group, self.parent, self.sub, self.leaf = make_category_hierarchy()

    def test_create_group_no_parent(self):
        resp = self.client.post('/api/v1/categories/', {
            'name': 'New Group', 'depth': 0, 'short_code': 'NG',
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['depth'], 0)

    def test_create_parent_with_correct_parent(self):
        resp = self.client.post('/api/v1/categories/', {
            'name': 'New Parent', 'depth': 1,
            'short_code': 'NP', 'parent': str(self.group.id),
        })
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_create_parent_with_wrong_parent_depth_rejected(self):
        resp = self.client.post('/api/v1/categories/', {
            'name': 'Bad Parent', 'depth': 1,
            'parent': str(self.leaf.id),  # leaf is depth=3, should be 0
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_group_with_parent_rejected(self):
        resp = self.client.post('/api/v1/categories/', {
            'name': 'Bad Group', 'depth': 0,
            'parent': str(self.group.id),
        })
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_category_tree_endpoint(self):
        resp = self.client.get('/api/v1/categories/tree/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # Should contain at least one root
        self.assertTrue(len(resp.data) >= 1)
        root = next((r for r in resp.data if r['name'] == self.group.name), None)
        self.assertIsNotNone(root)
        # Root should have children
        self.assertEqual(root['depth'], 0)

    def test_children_endpoint(self):
        resp = self.client.get(f'/api/v1/categories/{self.group.slug}/children/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [c['name'] for c in resp.data]
        self.assertIn(self.parent.name, names)

    def test_filter_by_depth(self):
        resp = self.client.get('/api/v1/categories/?depth=3')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        depths = [c['depth'] for c in resp.data['results']]
        self.assertTrue(all(d == 3 for d in depths))

    def test_filter_by_parent(self):
        resp = self.client.get(f'/api/v1/categories/?parent={self.group.id}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [c['name'] for c in resp.data['results']]
        self.assertIn(self.parent.name, names)

    def test_update_schema_on_leaf(self):
        schema = {
            'product_fields': [
                {'key': 'origin', 'label': 'Origin', 'type': 'text', 'required': False},
            ],
            'variant_attributes': [
                {'key': 'weight', 'label': 'Weight', 'type': 'select',
                 'options': ['1kg', '5kg']},
            ],
        }
        resp = self.client.patch(
            f'/api/v1/categories/{self.leaf.slug}/schema/',
            {'field_schema': schema},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.leaf.refresh_from_db()
        self.assertIn('origin', [f['key'] for f in self.leaf.field_schema['product_fields']])

    def test_update_schema_on_non_leaf_rejected(self):
        resp = self.client.patch(
            f'/api/v1/categories/{self.group.slug}/schema/',
            {'field_schema': {}},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


# ── Brand Tests ───────────────────────────────────────────────────────────────

class BrandCRUDTest(APITestCase):
    """Brand create, list, update, delete."""

    def setUp(self):
        self.admin  = make_admin(email='admin2@test.com')
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_create_brand(self):
        resp = self.client.post('/api/v1/brands/', {'name': 'India Gate', 'is_active': True})
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['name'], 'India Gate')
        self.assertIn('slug', resp.data)

    def test_list_brands(self):
        make_brand('Brand A')
        make_brand('Brand B')
        resp = self.client.get('/api/v1/brands/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [b['name'] for b in resp.data['results']]
        self.assertIn('Brand A', names)
        self.assertIn('Brand B', names)

    def test_update_brand(self):
        brand = make_brand('Old Name')
        resp  = self.client.patch(f'/api/v1/brands/{brand.slug}/', {'name': 'New Name'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        brand.refresh_from_db()
        self.assertEqual(brand.name, 'New Name')

    def test_delete_brand(self):
        brand = make_brand('Delete Me')
        resp  = self.client.delete(f'/api/v1/brands/{brand.slug}/')
        self.assertEqual(resp.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Brand.objects.filter(slug=brand.slug).exists())

    def test_search_brands(self):
        make_brand('Tata Salt')
        make_brand('Amul Butter')
        resp = self.client.get('/api/v1/brands/?search=Tata')
        names = [b['name'] for b in resp.data['results']]
        self.assertIn('Tata Salt', names)
        self.assertNotIn('Amul Butter', names)

    def test_guest_can_list_brands(self):
        make_brand('Public Brand')
        resp = self.client.get('/api/v1/brands/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_guest_cannot_create_brand(self):
        client = APIClient()  # unauthenticated
        resp   = client.post('/api/v1/brands/', {'name': 'Hack Brand'})
        self.assertIn(resp.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])


# ── Product Creation with Auto-Variants Tests ─────────────────────────────────

class ProductCreationWithVariantsTest(APITestCase):
    """New product creation flow with variant_combinations."""

    def setUp(self):
        self.admin = make_admin(email='admin3@test.com')
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        _, _, _, self.leaf = make_category_hierarchy(prefix='Food')
        self.brand = make_brand('India Gate')

    def test_create_product_with_variants_generates_skus(self):
        resp = self.client.post('/api/v1/products/', {
            'name':        'Basmati Rice',
            'description': 'Premium basmati',
            'category':    str(self.leaf.id),
            'brand':       str(self.brand.id),
            'extra_fields': {'grade': 'A'},
            'variant_combinations': [
                {'attributes': {'weight': '500g'}, 'stock_quantity': 100},
                {'attributes': {'weight': '1kg'},  'stock_quantity': 50},
            ],
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        # Verify product SKU was auto-generated
        product = Product.objects.get(slug=resp.data['slug'])
        self.assertIsNotNone(product.sku)
        self.assertNotEqual(product.sku, '')

        # Verify variants were created
        variants = list(product.variants.all())
        self.assertEqual(len(variants), 2)

        # Verify variant SKUs and attributes
        attr_weights = {v.attributes.get('weight') for v in variants}
        self.assertEqual(attr_weights, {'500g', '1kg'})

        # Each variant SKU should be unique and contain product SKU as prefix
        skus = [v.sku for v in variants]
        self.assertEqual(len(set(skus)), 2)
        for sku in skus:
            self.assertTrue(sku.startswith(product.sku.split('-')[0]))

    def test_create_product_no_variants(self):
        resp = self.client.post('/api/v1/products/', {
            'name':     'Simple Product',
            'category': str(self.leaf.id),
            'extra_fields': {'grade': 'B'},
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        product = Product.objects.get(slug=resp.data['slug'])
        self.assertEqual(product.variants.count(), 0)
        self.assertIsNotNone(product.sku)

    def test_category_must_be_depth_3(self):
        group = Category.objects.create(name='Bad Group', depth=0)
        resp  = self.client.post('/api/v1/products/', {
            'name':     'Bad Product',
            'category': str(group.id),
            'extra_fields': {},
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('depth', str(resp.data).lower())

    def test_required_extra_field_missing_rejected(self):
        # 'grade' is required in our test schema
        resp = self.client.post('/api/v1/products/', {
            'name':        'Missing Fields Product',
            'category':    str(self.leaf.id),
            'extra_fields': {},   # grade is required but missing
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('extra_fields', resp.data)

    def test_stock_quantity_stored_per_variant(self):
        resp = self.client.post('/api/v1/products/', {
            'name':     'Stocked Product',
            'category': str(self.leaf.id),
            'extra_fields': {'grade': 'A'},
            'variant_combinations': [
                {'attributes': {'weight': '500g'}, 'stock_quantity': 75},
                {'attributes': {'weight': '5kg'},  'stock_quantity': 10},
            ],
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        product  = Product.objects.get(slug=resp.data['slug'])
        stocks   = {v.attributes['weight']: v.stock_quantity for v in product.variants.all()}
        self.assertEqual(stocks['500g'], 75)
        self.assertEqual(stocks['5kg'],  10)

    def test_sku_uniqueness_across_products(self):
        """Two products in same category get unique SKUs."""
        payload = {
            'name':     'Rice Product 1',
            'category': str(self.leaf.id),
            'extra_fields': {'grade': 'A'},
        }
        resp1 = self.client.post('/api/v1/products/', payload, format='json')
        payload['name'] = 'Rice Product 2'
        resp2 = self.client.post('/api/v1/products/', payload, format='json')
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp2.status_code, status.HTTP_201_CREATED)
        self.assertNotEqual(
            Product.objects.get(slug=resp1.data['slug']).sku,
            Product.objects.get(slug=resp2.data['slug']).sku,
        )

    def test_product_detail_includes_brand_and_extra_fields(self):
        resp = self.client.post('/api/v1/products/', {
            'name':        'Branded Product',
            'category':    str(self.leaf.id),
            'brand':       str(self.brand.id),
            'extra_fields': {'grade': 'A', 'brand_detail': 'Premium'},
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        detail = self.client.get(f'/api/v1/products/{resp.data["slug"]}/')
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data['brand']['name'], 'India Gate')
        self.assertEqual(detail.data['extra_fields']['grade'], 'A')


# ── SKU Generation Unit Tests ─────────────────────────────────────────────────

class SKUGenerationTest(APITestCase):
    """Test SKU utility functions directly."""

    def test_build_variant_combinations_single_attr(self):
        combos = build_variant_combinations([
            {'key': 'weight', 'values': ['500g', '1kg', '2kg']},
        ])
        self.assertEqual(len(combos), 3)
        self.assertIn({'weight': '500g'}, combos)

    def test_build_variant_combinations_two_attrs(self):
        combos = build_variant_combinations([
            {'key': 'weight', 'values': ['500g', '1kg']},
            {'key': 'color',  'values': ['Red', 'Blue']},
        ])
        self.assertEqual(len(combos), 4)
        self.assertIn({'weight': '500g', 'color': 'Red'},  combos)
        self.assertIn({'weight': '1kg',  'color': 'Blue'}, combos)

    def test_build_variant_combinations_empty(self):
        combos = build_variant_combinations([])
        self.assertEqual(combos, [{}])

    def test_product_sku_uses_category_short_codes(self):
        _, _, _, leaf = make_category_hierarchy(prefix='Rice')
        brand   = make_brand('Brand X')
        product = Product(name='Rice Product', category=leaf, brand=brand)
        sku     = generate_product_sku(product)
        self.assertIn('RI', sku)   # from hierarchy short codes

    def test_variant_sku_uses_product_sku_as_prefix(self):
        _, _, _, leaf = make_category_hierarchy(prefix='Elec')
        product = Product.objects.create(name='Test', category=leaf, sku='EL-ELP-ELS-ELC-001')
        variant = ProductVariant(product=product, attributes={'weight': '1kg'}, sku='__placeholder__')
        sku     = generate_variant_sku(variant, product.sku)
        self.assertTrue(sku.startswith('EL-'))
        self.assertIn('1KG', sku)


# ── Existing Product Tests (updated to work with new models) ──────────────────

class ProductDefaultPublishedTest(APITestCase):
    def test_default_not_published(self):
        cat = make_category()
        p   = make_product(cat)
        self.assertFalse(p.is_published)


class ProductListPublicFilterTest(APITestCase):

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
        resp  = self.client.get(f'/api/v1/products/?category={self.cat.slug}')
        names = [p['name'] for p in resp.data['results']]
        self.assertIn('Published', names)
        self.assertNotIn('Other Product', names)

    def test_search(self):
        make_product(self.cat, name='Special Item', sku='SPEC01', is_published=True)
        resp  = self.client.get('/api/v1/products/?search=Special')
        names = [p['name'] for p in resp.data['results']]
        self.assertIn('Special Item', names)
        self.assertNotIn('Published', names)

    def test_in_stock_filter(self):
        resp = self.client.get('/api/v1/products/?in_stock=true')
        names = [p['name'] for p in resp.data['results']]
        self.assertIn('Published', names)


class ProductDetailTest(APITestCase):

    def test_detail(self):
        cat  = make_category()
        p    = make_product(cat, is_published=True)
        v    = make_variant(p)
        resp = self.client.get(f'/api/v1/products/{p.slug}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['slug'], p.slug)
        self.assertTrue(len(resp.data['variants']) >= 1)
        self.assertEqual(resp.data['variants'][0]['sku'], v.sku)


class UPAPriceTest(APITestCase):

    def setUp(self):
        self.cat    = make_category()
        self.upa    = make_upa()
        self.client = APIClient()
        self.client.force_authenticate(user=self.upa)
        s = UPADiscountSettings.get()
        s.global_discount_percent = Decimal('10.00')
        s.save()

    def test_global_discount(self):
        p = make_product(self.cat, mrp='200.00', is_published=True)
        make_variant(p)
        resp = self.client.get(f'/api/v1/products/{p.slug}/upa-price/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['product']['upa_price'], '180.00')

    def test_product_discount_override(self):
        p = make_product(
            self.cat, mrp='200.00', is_published=True,
            upa_discount_override=Decimal('20.00'), sku='OVRD01',
        )
        make_variant(p, sku='VOVRD01')
        resp = self.client.get(f'/api/v1/products/{p.slug}/upa-price/')
        self.assertEqual(resp.data['product']['upa_price'], '160.00')

    def test_product_price_override(self):
        p = make_product(
            self.cat, mrp='200.00', is_published=True,
            upa_price_override=Decimal('150.00'), sku='POVRD01',
        )
        make_variant(p, sku='VPOVRD01')
        resp = self.client.get(f'/api/v1/products/{p.slug}/upa-price/')
        self.assertEqual(resp.data['product']['upa_price'], '150.00')


class UPADiscountSettingsTest(APITestCase):

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
        self.assertEqual(resp.data['product']['upa_price'], '75.00')


class EmployeePermissionTest(APITestCase):

    def setUp(self):
        _, _, _, self.leaf = make_category_hierarchy(prefix='Emp')

    def test_employee_with_permission_can_create(self):
        emp    = make_employee(email='emp1@test.com', permissions=['products.edit'])
        client = APIClient()
        client.force_authenticate(user=emp)
        resp = client.post('/api/v1/products/', {
            'name':         'Emp Product',
            'category':     str(self.leaf.id),
            'extra_fields': {'grade': 'A'},  # grade is required in the test schema
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_employee_without_permission_gets_403(self):
        emp    = make_employee(email='emp2@test.com', permissions=[])
        client = APIClient()
        client.force_authenticate(user=emp)
        resp = client.post('/api/v1/products/', {
            'name': 'Hack Product', 'extra_fields': {},
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class TogglePublishTest(APITestCase):

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

    def test_upload_image(self):
        import io
        from PIL import Image as PILImage
        admin  = make_admin(email='admin4@test.com')
        cat    = make_category(name='ImgCat')
        p      = make_product(cat, sku='IMG001')
        client = APIClient()
        client.force_authenticate(user=admin)

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
