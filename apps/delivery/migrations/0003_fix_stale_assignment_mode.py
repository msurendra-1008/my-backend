from django.db import migrations

VALID_MODES = {'manual', 'suggested', 'automatic'}

def fix_assignment_mode(apps, schema_editor):
    DeliverySettings = apps.get_model('delivery', 'DeliverySettings')
    for obj in DeliverySettings.objects.all():
        if obj.assignment_mode not in VALID_MODES:
            obj.assignment_mode = 'manual'
            obj.save(update_fields=['assignment_mode'])


class Migration(migrations.Migration):

    dependencies = [
        ('delivery', '0002_deliverysettings_default_proof_type_and_more'),
    ]

    operations = [
        migrations.RunPython(fix_assignment_mode, migrations.RunPython.noop),
    ]
