# Generated manually for exclusions_checklist field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grants', '0007_add_sales_questionnaire'),
    ]

    operations = [
        migrations.AddField(
            model_name='grant',
            name='exclusions_checklist',
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
    ]




