# Generated manually for Funding Questionnaire feature

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0021_add_exclude_closed_competitions'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='FundingQuestionnaire',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text="Name for this questionnaire (e.g., 'AI Startup Q1 2025')", max_length=255)),
                ('questionnaire_data', models.JSONField(blank=True, default=dict, help_text='Stores all questionnaire answers')),
                ('is_default', models.BooleanField(default=False, help_text='If True, this is the default questionnaire for new funding searches')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='funding_questionnaires', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'funding_questionnaires',
                'ordering': ['-updated_at'],
            },
        ),
        migrations.AddField(
            model_name='fundingsearch',
            name='questionnaire',
            field=models.ForeignKey(blank=True, help_text='Questionnaire used to populate this funding search', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='funding_searches', to='companies.fundingquestionnaire'),
        ),
        migrations.AddIndex(
            model_name='fundingquestionnaire',
            index=models.Index(fields=['user', '-updated_at'], name='funding_que_user_id_updated_idx'),
        ),
        migrations.AddIndex(
            model_name='fundingquestionnaire',
            index=models.Index(fields=['user', 'is_default'], name='funding_que_user_id_is_def_idx'),
        ),
    ]
