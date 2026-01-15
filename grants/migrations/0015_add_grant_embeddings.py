# Generated migration for adding embedding fields to Grant model

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('grants', '0014_add_trl_requirements'),
    ]

    operations = [
        migrations.AddField(
            model_name='grant',
            name='embedding',
            field=models.JSONField(blank=True, default=list, help_text='Vector embedding for semantic search', null=True),
        ),
        migrations.AddField(
            model_name='grant',
            name='embedding_updated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
