"""
API URL configuration for grants app.
"""
from django.urls import path
from . import api_views

urlpatterns = [
    path('grants', api_views.get_grants, name='api_grants'),
    path('grants/upsert', api_views.upsert_grants, name='api_grants_upsert'),
]

