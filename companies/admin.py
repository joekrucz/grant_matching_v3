from django.contrib import admin
from .models import Company, FundingSearch, CompanyGrant, GrantMatchWorkpackage


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'company_number', 'company_type', 'status', 'user', 'created_at')
    list_filter = ('company_type', 'status', 'created_at')
    search_fields = ('name', 'company_number')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(FundingSearch)
class FundingSearchAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'user', 'trl_level', 'created_at')
    list_filter = ('trl_level', 'created_at')
    search_fields = ('name', 'company__name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(CompanyGrant)
class CompanyGrantAdmin(admin.ModelAdmin):
    list_display = ('company', 'grant', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('company__name', 'grant__title')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(GrantMatchWorkpackage)
class GrantMatchWorkpackageAdmin(admin.ModelAdmin):
    list_display = ('company', 'grant', 'user', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('company__name', 'grant__title')
    readonly_fields = ('created_at', 'updated_at')

