"""
Migration: category depth/short_code/field_schema, Brand model,
Product.brand + extra_fields, ProductVariant.attributes + nullable mrp.
"""
import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app_products', '0005_product_sku_mrp_optional'),
    ]

    operations = [
        # ── Category: rename related_name subcategories → children ────────────
        migrations.AlterField(
            model_name='category',
            name='parent',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='children',
                to='app_products.category',
            ),
        ),

        # ── Category: add depth ───────────────────────────────────────────────
        migrations.AddField(
            model_name='category',
            name='depth',
            field=models.PositiveSmallIntegerField(
                choices=[
                    (0, 'Category Group'),
                    (1, 'Parent Category'),
                    (2, 'Sub Category'),
                    (3, 'Product Category'),
                ],
                default=0,
            ),
        ),

        # ── Category: add short_code ──────────────────────────────────────────
        migrations.AddField(
            model_name='category',
            name='short_code',
            field=models.CharField(
                blank=True, max_length=10,
                help_text='Short uppercase code used in auto-generated SKUs e.g. GR, RC',
            ),
        ),

        # ── Category: add field_schema ────────────────────────────────────────
        migrations.AddField(
            model_name='category',
            name='field_schema',
            field=models.JSONField(
                blank=True, default=dict,
                help_text='Only used at depth=3. Defines dynamic product fields and variant attributes.',
            ),
        ),

        # ── Brand: create model ───────────────────────────────────────────────
        migrations.CreateModel(
            name='Brand',
            fields=[
                ('id',         models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('name',       models.CharField(max_length=120)),
                ('slug',       models.SlugField(blank=True, max_length=140, unique=True)),
                ('logo',       models.ImageField(blank=True, null=True, upload_to='brands/')),
                ('is_active',  models.BooleanField(default=True)),
            ],
            options={'ordering': ['name']},
        ),

        # ── Product: add brand FK ─────────────────────────────────────────────
        migrations.AddField(
            model_name='product',
            name='brand',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='products',
                to='app_products.brand',
            ),
        ),

        # ── Product: add extra_fields ─────────────────────────────────────────
        migrations.AddField(
            model_name='product',
            name='extra_fields',
            field=models.JSONField(
                blank=True, default=dict,
                help_text='Dynamic field values defined by the Product Category field_schema',
            ),
        ),

        # ── ProductVariant: add attributes ────────────────────────────────────
        migrations.AddField(
            model_name='productvariant',
            name='attributes',
            field=models.JSONField(
                blank=True, default=dict,
                help_text='Attribute key-value pairs e.g. {"weight": "1kg", "color": "Red"}',
            ),
        ),

        # ── ProductVariant: make mrp nullable ─────────────────────────────────
        migrations.AlterField(
            model_name='productvariant',
            name='mrp',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=12, null=True,
                help_text='Set via Pricing page',
            ),
        ),
    ]
