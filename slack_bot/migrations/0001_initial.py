# Generated migration for slack_bot app

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SlackWorkspace',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('team_id', models.CharField(db_index=True, max_length=50, unique=True)),
                ('team_name', models.CharField(max_length=255)),
                ('access_token', models.CharField(max_length=255)),
                ('bot_user_id', models.CharField(max_length=50)),
                ('installed_at', models.DateTimeField(auto_now_add=True)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'Slack Workspace',
                'verbose_name_plural': 'Slack Workspaces',
                'db_table': 'slack_workspaces',
            },
        ),
        migrations.CreateModel(
            name='SlackUser',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slack_user_id', models.CharField(db_index=True, max_length=50, unique=True)),
                ('slack_username', models.CharField(max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('app_user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='slack_users', to=settings.AUTH_USER_MODEL)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='users', to='slack_bot.slackworkspace')),
            ],
            options={
                'verbose_name': 'Slack User',
                'verbose_name_plural': 'Slack Users',
                'db_table': 'slack_users',
                'unique_together': {('slack_user_id', 'workspace')},
            },
        ),
    ]

