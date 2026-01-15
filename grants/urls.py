"""
URL configuration for grants app.
"""
from django.urls import path
from . import views

app_name = 'grants'

urlpatterns = [
    path('', views.index, name='index'),
    path('grants', views.grants_list, name='list'),
    path('grants/<slug:slug>/', views.grant_detail, name='detail'),
    path('grants/<slug:slug>/similar', views.similar_grants, name='similar_grants'),
    path('grants/<slug:slug>/delete', views.delete_grant, name='delete'),
    path('grants/<slug:slug>/generate-analysis', views.generate_grant_analysis, name='generate_grant_analysis'),
    path('grants/<slug:slug>/generate-trl', views.generate_trl_requirements, name='generate_trl_requirements'),
    path('grants/trl_requirements', views.trl_requirements, name='trl_requirements'),
    path('grants/eligibility_checklist', views.eligibility_checklist, name='eligibility_checklist'),
    path('grants/competitiveness_checklist', views.competitiveness_checklist, name='competitiveness_checklist'),
    path('grants/exclusions_checklist', views.exclusions_checklist, name='exclusions_checklist'),
    path('terms', views.terms_and_conditions, name='terms'),
    path('cookies', views.cookie_policy, name='cookie_policy'),
    path('cookies/preferences', views.cookie_preferences, name='cookie_preferences'),
    path('privacy', views.privacy_policy, name='privacy'),
    path('support', views.support, name='support'),
    path('about', views.about, name='about'),
    path('search', views.global_search, name='search'),
]

