from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0004_order_status_processing_to_packed'),
    ]

    operations = [
        migrations.AddField(
            model_name='orderitem',
            name='delivered_at',
            field=models.DateTimeField(null=True, blank=True),
        ),
    ]
