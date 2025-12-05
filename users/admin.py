from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'name', 'admin', 'is_active', 'email_confirmed_at', 'date_joined', 'last_login')
    list_filter = ('admin', 'is_active', 'email_confirmed_at', 'date_joined')
    search_fields = ('email', 'name')
    ordering = ('-date_joined',)
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('name', 'theme')}),
        ('Permissions', {'fields': ('admin', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Email Confirmation', {'fields': ('email_confirmed_at', 'confirmation_token', 'unconfirmed_email')}),
        ('Password Reset', {'fields': ('reset_password_token', 'reset_password_sent_at')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'name', 'admin'),
        }),
    )

