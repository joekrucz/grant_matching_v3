# Generated manually
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0006_add_unregistered_company_support'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='filing_history',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

