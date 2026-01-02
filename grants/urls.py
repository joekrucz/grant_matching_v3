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
    path('grants/<slug:slug>/delete', views.delete_grant, name='delete'),
    path('grants/eligibility_checklist', views.eligibility_checklist, name='eligibility_checklist'),
    path('grants/competitiveness_checklist', views.competitiveness_checklist, name='competitiveness_checklist'),
    path('grants/exclusions_checklist', views.exclusions_checklist, name='exclusions_checklist'),
    path('grants/eligibility-questionnaire', views.eligibility_questionnaire, name='eligibility_questionnaire'),
    path('grants/questionnaires', views.questionnaires_list, name='questionnaires_list'),
    path('grants/questionnaires/<int:questionnaire_id>/', views.questionnaire_detail, name='questionnaire_detail'),
]

