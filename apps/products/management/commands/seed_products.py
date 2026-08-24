from django.core.management.base import BaseCommand
from apps.products.models import Category, Brand, Product, ProductVariant


PRODUCTS = [
    {
        'slug':        'sprint-xt200-running-shoe',
        'name':        'Sprint XT200 Running Shoe',
        'description': (
            'Lightweight running shoe with breathable mesh upper, EVA midsole cushioning, '
            'and rubber outsole for superior grip. Ideal for daily training and road runs.'
        ),
        'category':    {'name': "Men's Footwear",  'short_code': 'MF'},
        'brand':       'Sprint',
        'barcode':     '8901000000001',
        'extra_fields': {'Material': 'Mesh + Rubber', 'Closure': 'Lace-up',
                         'Sole': 'EVA', 'Warranty': '6 months'},
        'variant_type': 'size',
        'variants': [
            {'name': 'UK 6',  'sku': 'SPXT200-UK6',  'mrp': '2499.00', 'stock': 10,
             'attrs': {'size': '6'}},
            {'name': 'UK 7',  'sku': 'SPXT200-UK7',  'mrp': '2499.00', 'stock': 40,
             'attrs': {'size': '7'}},
            {'name': 'UK 8',  'sku': 'SPXT200-UK8',  'mrp': '2499.00', 'stock': 55,
             'attrs': {'size': '8'}},
            {'name': 'UK 9',  'sku': 'SPXT200-UK9',  'mrp': '2499.00', 'stock': 30,
             'attrs': {'size': '9'}},
            {'name': 'UK 10', 'sku': 'SPXT200-UK10', 'mrp': '2699.00', 'stock': 18,
             'attrs': {'size': '10'}},
            {'name': 'UK 11', 'sku': 'SPXT200-UK11', 'mrp': '2699.00', 'stock': 4,
             'attrs': {'size': '11'}},
        ],
    },
    {
        'slug':        'fitzone-dryflex-sports-tshirt',
        'name':        'FitZone DryFlex Sports T-Shirt',
        'description': (
            'Premium moisture-wicking polyester T-shirt with DryFlex technology. '
            'Anti-odour treatment, flatlock seams for chafe-free comfort.'
        ),
        'category':    {'name': 'Sports Apparel', 'short_code': 'SA'},
        'brand':       'FitZone',
        'barcode':     '8901000000002',
        'extra_fields': {'Fabric': '100% Polyester', 'Fit': 'Regular',
                         'GSM': '160', 'Care': 'Machine washable'},
        'variant_type': 'colour',
        'variants': [
            {'name': 'Black',       'sku': 'FZDF-BLACK',   'mrp': '899.00', 'stock': 60,
             'attrs': {'colour': 'black'}},
            {'name': 'White',       'sku': 'FZDF-WHITE',   'mrp': '899.00', 'stock': 45,
             'attrs': {'colour': 'white'}},
            {'name': 'Navy Blue',   'sku': 'FZDF-NAVY',    'mrp': '899.00', 'stock': 35,
             'attrs': {'colour': 'navy'}},
            {'name': 'Royal Blue',  'sku': 'FZDF-ROYAL',   'mrp': '899.00', 'stock': 20,
             'attrs': {'colour': 'royal'}},
            {'name': 'Olive Green', 'sku': 'FZDF-OLIVE',   'mrp': '949.00', 'stock': 8,
             'attrs': {'colour': 'olive'}},
            {'name': 'Charcoal',    'sku': 'FZDF-CHARCOA', 'mrp': '949.00', 'stock': 12,
             'attrs': {'colour': 'charcoal'}},
        ],
    },
    {
        'slug':        'nutrabay-gold-whey-protein',
        'name':        'Nutrabay Gold Whey Protein – Chocolate',
        'description': (
            'Premium whey protein concentrate with 24g protein per serving. '
            'Enriched with digestive enzymes. No artificial colours.'
        ),
        'category':    {'name': 'Nutrition', 'short_code': 'NUT'},
        'brand':       'Nutrabay',
        'barcode':     '8901000000003',
        'extra_fields': {'Flavour': 'Chocolate', 'Protein/serving': '24g',
                         'Carbs/serving': '4g', 'Fat/serving': '2g'},
        'variant_type': 'weight',
        'variants': [
            {'name': '500 g', 'sku': 'NBGWP-500G', 'mrp': '1099.00', 'stock': 25,
             'attrs': {'weight': '500g'}},
            {'name': '1 kg',  'sku': 'NBGWP-1KG',  'mrp': '1999.00', 'stock': 40,
             'attrs': {'weight': '1kg'}},
            {'name': '2 kg',  'sku': 'NBGWP-2KG',  'mrp': '3699.00', 'stock': 20,
             'attrs': {'weight': '2kg'}},
            {'name': '3 kg',  'sku': 'NBGWP-3KG',  'mrp': '5299.00', 'stock': 10,
             'attrs': {'weight': '3kg'}},
            {'name': '5 kg',  'sku': 'NBGWP-5KG',  'mrp': '8499.00', 'stock': 3,
             'attrs': {'weight': '5kg'}},
        ],
    },
    {
        'slug':        'fitzone-pro-resistance-bands',
        'name':        'FitZone Pro Resistance Bands',
        'description': (
            'Heavy-duty latex resistance bands for strength training, physio rehab, '
            'and stretching. Each band is 1.2 m long with textured grip ends.'
        ),
        'category':    {'name': 'Gym Equipment', 'short_code': 'GE'},
        'brand':       'FitZone',
        'barcode':     '8901000000004',
        'extra_fields': {'Material': 'Natural Latex', 'Length': '1.2 m',
                         'Includes': 'Carry pouch', 'Warranty': '1 year'},
        'variant_type': 'other',
        'variants': [
            {'name': 'X-Light – 5 kg',   'sku': 'FZRB-XLIGHT',  'mrp': '399.00', 'stock': 30,
             'attrs': {'resistance': 'x-light', 'max_kg': '5'}},
            {'name': 'Light – 10 kg',    'sku': 'FZRB-LIGHT',   'mrp': '449.00', 'stock': 25,
             'attrs': {'resistance': 'light',   'max_kg': '10'}},
            {'name': 'Medium – 15 kg',   'sku': 'FZRB-MEDIUM',  'mrp': '499.00', 'stock': 40,
             'attrs': {'resistance': 'medium',  'max_kg': '15'}},
            {'name': 'Heavy – 22 kg',    'sku': 'FZRB-HEAVY',   'mrp': '549.00', 'stock': 18,
             'attrs': {'resistance': 'heavy',   'max_kg': '22'}},
            {'name': 'X-Heavy – 32 kg',  'sku': 'FZRB-XHEAVY',  'mrp': '599.00', 'stock': 6,
             'attrs': {'resistance': 'x-heavy', 'max_kg': '32'}},
            {'name': 'XX-Heavy – 45 kg', 'sku': 'FZRB-XXHEAVY', 'mrp': '649.00', 'stock': 0,
             'attrs': {'resistance': 'xx-heavy','max_kg': '45'}},
        ],
    },
    {
        'slug':        'nutrabay-daily-multivitamin',
        'name':        'Nutrabay Daily Multivitamin',
        'description': (
            'Complete daily multivitamin with 26 essential vitamins and minerals. '
            'Supports immunity, energy, and bone health. Vegetarian capsules.'
        ),
        'category':    {'name': 'Health & Wellness', 'short_code': 'HW'},
        'brand':       'Nutrabay',
        'barcode':     '8901000000005',
        'extra_fields': {'Form': 'Capsules', 'Vegetarian': 'Yes',
                         'Vitamins': '26 nutrients', 'Usage': '1 capsule daily'},
        'variant_type': 'other',
        'variants': [
            {'name': '30 Capsules',  'sku': 'NBMV-30CAP',  'mrp': '449.00',  'stock': 35,
             'attrs': {'pack_size': '30cap'}},
            {'name': '60 Capsules',  'sku': 'NBMV-60CAP',  'mrp': '799.00',  'stock': 50,
             'attrs': {'pack_size': '60cap'}},
            {'name': '90 Capsules',  'sku': 'NBMV-90CAP',  'mrp': '1099.00', 'stock': 30,
             'attrs': {'pack_size': '90cap'}},
            {'name': '120 Capsules', 'sku': 'NBMV-120CAP', 'mrp': '1399.00', 'stock': 20,
             'attrs': {'pack_size': '120cap'}},
            {'name': '180 Capsules', 'sku': 'NBMV-180CAP', 'mrp': '1899.00', 'stock': 5,
             'attrs': {'pack_size': '180cap'}},
            {'name': '365 Capsules', 'sku': 'NBMV-365CAP', 'mrp': '3499.00', 'stock': 2,
             'attrs': {'pack_size': '365cap'}},
        ],
    },
]


class Command(BaseCommand):
    help = 'Seed 5 demo products with 5-6 variants each for testing the shop UI'

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('\n=== Seeding products ===\n'))

        for data in PRODUCTS:
            # Category
            cat_slug = data['category']['name'].lower().replace(' ', '-').replace("'", '')
            cat, _ = Category.objects.get_or_create(
                slug=cat_slug,
                defaults=dict(
                    name=data['category']['name'],
                    short_code=data['category']['short_code'],
                    depth=0,
                    is_active=True,
                    field_schema={},
                )
            )

            # Brand
            brand_slug = data['brand'].lower().replace(' ', '-')
            brand, _ = Brand.objects.get_or_create(
                slug=brand_slug,
                defaults=dict(name=data['brand'], is_active=True)
            )

            # Product
            prod, created = Product.objects.get_or_create(
                slug=data['slug'],
                defaults=dict(
                    name=data['name'],
                    description=data['description'],
                    category=cat,
                    brand=brand,
                    barcode=data['barcode'],
                    is_published=True,
                    extra_fields=data['extra_fields'],
                )
            )
            status = self.style.SUCCESS('CREATED') if created else self.style.WARNING('EXISTS ')
            self.stdout.write(f'  [{status}] {prod.name}')

            # Variants
            for i, v in enumerate(data['variants']):
                variant, vc = ProductVariant.objects.update_or_create(
                    sku=v['sku'],
                    defaults=dict(
                        product=prod,
                        name=v['name'],
                        variant_type=data['variant_type'],
                        attributes=v['attrs'],
                        mrp=v['mrp'],
                        stock_quantity=v['stock'],
                        is_active=True,
                        order=i,
                    )
                )
                marker = self.style.SUCCESS('✓') if vc else '↺'
                self.stdout.write(
                    f'         {marker}  {v["name"]:<18}  MRP ₹{v["mrp"]:<10}  stock={v["stock"]}'
                )

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Done! Now set UPA pricing + commission from the admin panel.'))
        self.stdout.write('')
