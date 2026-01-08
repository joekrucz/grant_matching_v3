"""
URL configuration for admin_panel app.
"""
from django.urls import path
from . import views

app_name = 'admin_panel'

urlpatterns = [
    path('dashboard', views.dashboard, name='dashboard'),
    path('run_scrapers', views.run_scrapers, name='run_scrapers'),
    path('run_scraper/ukri', views.run_ukri_scraper, name='run_ukri_scraper'),
    path('run_scraper/nihr', views.run_nihr_scraper, name='run_nihr_scraper'),
    path('run_scraper/catapult', views.run_catapult_scraper, name='run_catapult_scraper'),
    path('run_scraper/innovate', views.run_innovate_uk_scraper, name='run_innovate_uk_scraper'),
    path('wipe_grants', views.wipe_grants, name='wipe_grants'),
    path('wipe_grants/<str:source>', views.wipe_grants_by_source, name='wipe_grants_by_source'),
    path('scrape_logs', views.scrape_logs, name='scrape_logs'),
    path('scrape_logs/<int:log_id>/cancel', views.cancel_scraper_job, name='cancel_scraper_job'),
    path('scraper_status', views.scraper_status, name='scraper_status'),
    path('users', views.users_list, name='users_list'),
    path('users/<int:id>/', views.user_detail, name='user_detail'),
    path('users/<int:id>/delete', views.user_delete, name='user_delete'),
    path('refresh_companies', views.refresh_companies, name='refresh_companies'),
    path('companies_refresh_status', views.companies_refresh_status, name='companies_refresh_status'),
    path('generate_checklists', views.generate_checklists, name='generate_checklists'),
    path('checklist_generation_status', views.checklist_generation_status, name='checklist_generation_status'),
    path('cancel_checklist_generation', views.cancel_checklist_generation, name='cancel_checklist_generation'),
    # Admin AI assistant endpoints (admin-only, JSON)
    path('ai/summarise_grant', views.ai_summarise_grant, name='ai_summarise_grant'),
    path('ai/summarise_company', views.ai_summarise_company, name='ai_summarise_company'),
    path('ai/contextual_qa', views.ai_contextual_qa, name='ai_contextual_qa'),
    path('system_settings', views.system_settings, name='system_settings'),
    path('scraper_reports', views.scraper_reports, name='scraper_reports'),
    path('scraper_reports/<int:run_id>', views.scraper_report_detail, name='scraper_report_detail'),
    path('ai/grant_company_fit', views.ai_grant_company_fit, name='ai_grant_company_fit'),
    path('ai/search_grants_for_company', views.ai_search_grants_for_company, name='ai_search_grants_for_company'),
    path('ai/search_companies', views.ai_search_companies, name='ai_search_companies'),
    path('ai/search_grants', views.ai_search_grants, name='ai_search_grants'),
    # Conversation management
    path('ai/conversations', views.ai_conversations_list, name='ai_conversations_list'),
    path('ai/conversations/create', views.ai_conversation_create, name='ai_conversation_create'),
    path('ai/conversations/<int:conversation_id>', views.ai_conversation_detail, name='ai_conversation_detail'),
    path('ai/conversations/<int:conversation_id>/update', views.ai_conversation_update, name='ai_conversation_update'),
    path('ai/conversations/<int:conversation_id>/delete', views.ai_conversation_delete, name='ai_conversation_delete'),
    path('ai/conversations/<int:conversation_id>/messages', views.ai_conversation_add_message, name='ai_conversation_add_message'),
    # Conversations page (full page view)
    path('conversations', views.ai_conversations_page, name='conversations_page'),
]

