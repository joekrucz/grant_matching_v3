# Generated manually for trl_requirements field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grants', '0013_update_ukri_grants_from_funder'),
    ]

    operations = [
        migrations.AddField(
            model_name='grant',
            name='trl_requirements',
            field=models.JSONField(blank=True, default=dict, help_text="Extracted TRL requirements for this grant (e.g., {'trl_levels': ['TRL 1', 'TRL 2'], 'trl_range': '1-3'})", null=True),
        ),
    ]
