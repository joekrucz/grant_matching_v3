# Generated manually to fix DataError: value too long for type character varying(20)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0018_add_let_system_decide_trl'),
    ]

    operations = [
        migrations.AlterField(
            model_name='company',
            name='company_number',
            field=models.CharField(blank=True, db_index=True, max_length=50, null=True, unique=True),
        ),
    ]



