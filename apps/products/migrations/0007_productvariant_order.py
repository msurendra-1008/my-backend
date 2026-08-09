from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app_products', '0006_category_brand_product_refactor'),
    ]

    operations = [
        migrations.AddField(
            model_name='productvariant',
            name='order',
            field=models.PositiveIntegerField(default=0, help_text='Display order (drag to reorder)'),
        ),
        migrations.AlterModelOptions(
            name='productvariant',
            options={'ordering': ['order', 'name']},
        ),
    ]
