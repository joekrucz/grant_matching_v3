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
    path('files/<int:file_id>/delete', views.company_file_delete, name='file_delete'),
    path('<int:company_id>/funding_searches', views.funding_search_create, name='funding_search_create'),
    path('funding_searches/<int:id>/', views.funding_search_detail, name='funding_search_detail'),
    path('funding_searches/<int:id>/delete', views.funding_search_delete, name='funding_search_delete'),
    path('funding_searches/<int:id>/upload', views.funding_search_upload, name='funding_search_upload'),
    path('funding_searches/<int:id>/match', views.funding_search_match, name='funding_search_match'),
    path('funding_searches/<int:id>/status', views.funding_search_status, name='funding_search_status'),
]

