from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0008_rename_companies_is_regi_123456_idx_companies_is_regi_4274b8_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='company',
            name='grants_received_360',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

