# Generated manually for Django 5.0.1

import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('admin_panel', '0002_rename_admin_ai_in_endpoin_idx_admin_ai_in_endpoin_146724_idx'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Conversation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(blank=True, max_length=255, null=True)),
                ('initial_page_type', models.CharField(blank=True, max_length=50, null=True)),
                ('initial_grant_id', models.IntegerField(blank=True, null=True)),
                ('initial_company_id', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True, db_index=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='ai_conversations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'admin_ai_conversations',
                'ordering': ['-updated_at'],
            },
        ),
        migrations.CreateModel(
            name='ConversationMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('user', 'User'), ('assistant', 'Assistant')], db_index=True, max_length=20)),
                ('content', models.TextField()),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='admin_panel.conversation')),
            ],
            options={
                'db_table': 'admin_ai_conversation_messages',
                'ordering': ['created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='conversation',
            index=models.Index(fields=['user', '-updated_at'], name='admin_ai_co_user_id_idx'),
        ),
        migrations.AddIndex(
            model_name='conversationmessage',
            index=models.Index(fields=['conversation', 'created_at'], name='admin_ai_co_convers_idx'),
        ),
    ]

