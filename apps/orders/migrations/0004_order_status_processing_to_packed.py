from django.db import migrations, models


def processing_to_packed(apps, schema_editor):
    Order = apps.get_model('orders', 'Order')
    Order.objects.filter(order_status='processing').update(order_status='packed')


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0003_add_orderitem_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='order',
            name='order_status',
            field=models.CharField(
                choices=[
                    ('pending',   'Pending'),
                    ('confirmed', 'Confirmed'),
                    ('packed',    'Packed'),
                    ('shipped',   'Shipped'),
                    ('delivered', 'Delivered'),
                    ('cancelled', 'Cancelled'),
                ],
                default='pending',
                max_length=15,
            ),
        ),
        migrations.RunPython(processing_to_packed, migrations.RunPython.noop),
    ]
