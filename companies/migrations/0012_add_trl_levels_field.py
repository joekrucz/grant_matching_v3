from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0011_companynote'),
    ]

    operations = [
        migrations.AddField(
            model_name='fundingsearch',
            name='trl_levels',
            field=models.JSONField(blank=True, default=list),
        ),
    ]

