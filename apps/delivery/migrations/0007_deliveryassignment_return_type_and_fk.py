import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('delivery', '0006_deliveryassignment_assignment_type_and_more'),
        ('returns',  '0006_returnrequest_pickup_dispatched_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='deliveryassignment',
            name='assignment_type',
            field=models.CharField(
                choices=[
                    ('order',    'Order Delivery'),
                    ('exchange', 'Exchange Delivery'),
                    ('return',   'Return Pickup'),
                ],
                default='order',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='deliveryassignment',
            name='return_request',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='return_pickup',
                to='returns.returnrequest',
            ),
        ),
    ]
