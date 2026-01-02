# Generated manually for EligibilityQuestionnaire model

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('grants', '0005_add_competitiveness_checklist'),
    ]

    operations = [
        migrations.CreateModel(
            name='EligibilityQuestionnaire',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, max_length=255, null=True)),
                ('selected_items', models.JSONField(default=list)),
                ('all_items', models.JSONField(default=list)),
                ('total_grants', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='eligibility_questionnaires', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'eligibility_questionnaires',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['user', 'created_at'], name='eligibility_user_created_idx'),
                ],
            },
        ),
    ]

