"""
URL configuration for admin_panel app.
"""
from django.urls import path
from . import views

app_name = 'admin_panel'

urlpatterns = [
    path('dashboard', views.dashboard, name='dashboard'),
    path('run_scrapers', views.run_scrapers, name='run_scrapers'),
    path('wipe_grants', views.wipe_grants, name='wipe_grants'),
    path('scrape_logs', views.scrape_logs, name='scrape_logs'),
    path('scraper_status', views.scraper_status, name='scraper_status'),
    path('users', views.users_list, name='users_list'),
    path('users/<int:id>/', views.user_detail, name='user_detail'),
    path('users/<int:id>/delete', views.user_delete, name='user_delete'),
    path('refresh_companies', views.refresh_companies, name='refresh_companies'),
    path('companies_refresh_status', views.companies_refresh_status, name='companies_refresh_status'),
]

