# Generated migration for SlackBotLog model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('slack_bot', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SlackBotLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message_type', models.CharField(choices=[('dm', 'Direct Message'), ('mention', 'App Mention'), ('command', 'Slash Command')], db_index=True, max_length=20)),
                ('slack_user_id', models.CharField(db_index=True, max_length=50)),
                ('slack_username', models.CharField(blank=True, max_length=100)),
                ('channel', models.CharField(db_index=True, max_length=50)),
                ('message_text', models.TextField()),
                ('company_number', models.CharField(blank=True, db_index=True, max_length=20, null=True)),
                ('status', models.CharField(choices=[('received', 'Received'), ('processed', 'Processed'), ('error', 'Error')], db_index=True, default='received', max_length=20)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('response_sent', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'verbose_name': 'Slack Bot Log',
                'verbose_name_plural': 'Slack Bot Logs',
                'db_table': 'slack_bot_logs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='slackbotlog',
            index=models.Index(fields=['-created_at'], name='slack_bot_l_created_idx'),
        ),
        migrations.AddIndex(
            model_name='slackbotlog',
            index=models.Index(fields=['status', '-created_at'], name='slack_bot_l_status_created_idx'),
        ),
        migrations.AddIndex(
            model_name='slackbotlog',
            index=models.Index(fields=['message_type', '-created_at'], name='slack_bot_l_message_type_created_idx'),
        ),
    ]

