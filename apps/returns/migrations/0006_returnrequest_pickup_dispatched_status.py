from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('returns', '0005_alter_returnrequest_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='returnrequest',
            name='status',
            field=models.CharField(
                choices=[
                    ('raised', 'Raised'),
                    ('under_review', 'Under Review'),
                    ('approved', 'Approved'),
                    ('exchange_dispatched', 'Exchange Dispatched'),
                    ('pickup_dispatched', 'Pickup Dispatched'),
                    ('rejected', 'Rejected'),
                    ('rejected_final', 'Rejected Final'),
                    ('completed', 'Completed'),
                ],
                default='raised',
                max_length=20,
            ),
        ),
    ]
