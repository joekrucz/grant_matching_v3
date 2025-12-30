"""
URL configuration for companies app.
"""
from django.urls import path
from . import views

app_name = 'companies'

urlpatterns = [
    path('', views.companies_list, name='list'),
    path('new', views.company_create, name='create'),
    path('<int:id>/', views.company_detail, name='detail'),
    path('<int:id>/delete', views.company_delete, name='delete'),
    path('<int:id>/grants/refresh', views.company_refresh_grants, name='grants_refresh'),
    path('<int:id>/filings/refresh', views.company_refresh_filings, name='filings_refresh'),
    path('files/<int:file_id>/delete', views.company_file_delete, name='file_delete'),
    path('<int:company_id>/notes', views.company_note_create, name='note_create'),
    path('notes/<int:note_id>/delete', views.company_note_delete, name='note_delete'),
    path('<int:company_id>/funding_searches', views.funding_search_create, name='funding_search_create'),
    path('funding_searches/<int:id>/', views.funding_search_detail, name='funding_search_detail'),
    path('funding_searches/<int:id>/select_data', views.funding_search_select_data, name='funding_search_select_data'),
    path('funding_searches/<int:id>/delete', views.funding_search_delete, name='funding_search_delete'),
    path('funding_searches/<int:id>/upload', views.funding_search_upload, name='funding_search_upload'),
    path('funding_searches/<int:id>/match', views.funding_search_match, name='funding_search_match'),
    path('funding_searches/<int:id>/match_test', views.funding_search_match_test, name='funding_search_match_test'),
    path('funding_searches/<int:id>/clear_results', views.funding_search_clear_results, name='funding_search_clear_results'),
    path('funding_searches/<int:id>/cancel', views.funding_search_cancel, name='funding_search_cancel'),
    path('funding_searches/<int:id>/status', views.funding_search_status, name='funding_search_status'),
    path('search', views.company_search, name='search'),
    path('<int:id>/onboarding', views.company_onboarding, name='onboarding'),
]

