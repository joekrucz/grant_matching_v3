from django.contrib import admin
from .models import Grant, ScrapeLog


@admin.register(Grant)
class GrantAdmin(admin.ModelAdmin):
    list_display = ('title', 'source', 'status', 'deadline', 'first_seen_at', 'last_changed_at')
    list_filter = ('source', 'status', 'deadline')
    search_fields = ('title', 'summary', 'description')
    readonly_fields = ('first_seen_at', 'last_changed_at', 'hash_checksum', 'created_at', 'updated_at')
    date_hierarchy = 'deadline'


@admin.register(ScrapeLog)
class ScrapeLogAdmin(admin.ModelAdmin):
    list_display = ('source', 'status', 'started_at', 'completed_at', 'grants_found', 'grants_created', 'grants_updated', 'grants_skipped')
    list_filter = ('source', 'status', 'started_at')
    readonly_fields = ('started_at', 'completed_at', 'created_at', 'updated_at')
    date_hierarchy = 'started_at'


