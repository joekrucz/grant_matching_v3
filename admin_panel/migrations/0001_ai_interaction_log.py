# Generated manually for Django 5.0.1

import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('grants', '0001_initial'),
        ('companies', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AiInteractionLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('endpoint', models.CharField(db_index=True, max_length=100)),
                ('model_name', models.CharField(blank=True, max_length=100, null=True)),
                ('request_payload', models.JSONField(blank=True, default=dict)),
                ('response_payload', models.JSONField(blank=True, default=dict)),
                ('error', models.TextField(blank=True, null=True)),
                ('latency_ms', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('company', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ai_interactions', to='companies.company')),
                ('grant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ai_interactions', to='grants.grant')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ai_interactions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'admin_ai_interaction_logs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='aiinteractionlog',
            index=models.Index(fields=['endpoint', 'created_at'], name='admin_ai_in_endpoin_idx'),
        ),
    ]

