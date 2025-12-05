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
]

