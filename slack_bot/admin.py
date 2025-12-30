"""
Admin configuration for slack_bot models.
"""
from django.contrib import admin
from .models import SlackWorkspace, SlackUser, SlackBotLog


@admin.register(SlackWorkspace)
class SlackWorkspaceAdmin(admin.ModelAdmin):
    list_display = ('team_name', 'team_id', 'bot_user_id', 'is_active', 'installed_at')
    list_filter = ('is_active', 'installed_at')
    search_fields = ('team_name', 'team_id')
    readonly_fields = ('installed_at',)


@admin.register(SlackUser)
class SlackUserAdmin(admin.ModelAdmin):
    list_display = ('slack_username', 'slack_user_id', 'workspace', 'app_user', 'created_at')
    list_filter = ('workspace', 'created_at')
    search_fields = ('slack_username', 'slack_user_id')
    readonly_fields = ('created_at',)


@admin.register(SlackBotLog)
class SlackBotLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'message_type', 'slack_username', 'company_number', 'status', 'response_sent')
    list_filter = ('message_type', 'status', 'response_sent', 'created_at')
    search_fields = ('slack_username', 'slack_user_id', 'company_number', 'message_text')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
    date_hierarchy = 'created_at'

