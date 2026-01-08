# Generated manually for sales_questionnaire field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grants', '0006_eligibility_questionnaire'),
    ]

    operations = [
        migrations.AddField(
            model_name='eligibilityquestionnaire',
            name='sales_questionnaire',
            field=models.JSONField(blank=True, default=dict, null=True),
        ),
    ]




