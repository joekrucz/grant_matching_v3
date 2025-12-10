# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grants', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='scrapelog',
            name='grants_found',
            field=models.IntegerField(default=0),
        ),
    ]

