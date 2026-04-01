# Generated manually
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('app_products', '0001_initial'),
        ('vendors', '0002_vendorproduct_vendorproductimage_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Tender
        migrations.CreateModel(
            name='Tender',
            fields=[
                ('id', models.UUIDField(
                    default=uuid.uuid4, editable=False,
                    primary_key=True, serialize=False)),
                ('tender_number', models.CharField(max_length=30, unique=True)),
                ('title', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True)),
                ('status', models.CharField(
                    choices=[
                        ('draft', 'Draft'),
                        ('open', 'Open'),
                        ('closed', 'Closed'),
                        ('awarded', 'Awarded'),
                        ('cancelled', 'Cancelled'),
                    ],
                    default='draft', max_length=20)),
                ('bidding_deadline', models.DateTimeField(blank=True, null=True)),
                ('closed_at', models.DateTimeField(blank=True, null=True)),
                ('awarded_at', models.DateTimeField(blank=True, null=True)),
                ('cancellation_reason', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('awarded_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='awarded_tenders',
                    to=settings.AUTH_USER_MODEL)),
                ('closed_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='closed_tenders',
                    to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='created_tenders',
                    to=settings.AUTH_USER_MODEL)),
            ],
        ),
        # 2. VendorBid (FK to Tender — no dep on TenderItem)
        migrations.CreateModel(
            name='VendorBid',
            fields=[
                ('id', models.UUIDField(
                    default=uuid.uuid4, editable=False,
                    primary_key=True, serialize=False)),
                ('status', models.CharField(
                    choices=[
                        ('bid_submitted', 'Bid Submitted'),
                        ('under_negotiation', 'Under Negotiation'),
                        ('bid_revised', 'Bid Revised'),
                        ('awarded', 'Awarded'),
                        ('not_awarded', 'Not Awarded'),
                    ],
                    default='bid_submitted', max_length=25)),
                ('overall_notes', models.TextField(blank=True)),
                ('negotiation_notes', models.TextField(blank=True)),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('update_count', models.PositiveIntegerField(default=0)),
                ('tender', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='bids',
                    to='tender.tender')),
                ('vendor', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='tender_bids',
                    to='vendors.vendorprofile')),
            ],
            options={'unique_together': {('tender', 'vendor')}},
        ),
        # 3. TenderItem (FK to Tender + VendorBid for awarded_bid)
        migrations.CreateModel(
            name='TenderItem',
            fields=[
                ('id', models.UUIDField(
                    default=uuid.uuid4, editable=False,
                    primary_key=True, serialize=False)),
                ('required_quantity', models.PositiveIntegerField()),
                ('target_price', models.DecimalField(
                    blank=True, decimal_places=2, max_digits=10, null=True)),
                ('notes', models.TextField(blank=True)),
                ('awarded_bid', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='awarded_items',
                    to='tender.vendorbid')),
                ('awarded_to', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='awarded_tender_items',
                    to='vendors.vendorprofile')),
                ('product', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    to='app_products.product')),
                ('tender', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items',
                    to='tender.tender')),
            ],
        ),
        # 4. VendorBidItem
        migrations.CreateModel(
            name='VendorBidItem',
            fields=[
                ('id', models.UUIDField(
                    default=uuid.uuid4, editable=False,
                    primary_key=True, serialize=False)),
                ('supply_quantity', models.PositiveIntegerField()),
                ('price_per_unit', models.DecimalField(
                    decimal_places=2, max_digits=10)),
                ('dispatch_date', models.DateField()),
                ('monthly_breakdown', models.JSONField(default=list)),
                ('notes', models.TextField(blank=True)),
                ('bid', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='items',
                    to='tender.vendorbid')),
                ('tender_item', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='bid_items',
                    to='tender.tenderitem')),
            ],
            options={'unique_together': {('bid', 'tender_item')}},
        ),
    ]
