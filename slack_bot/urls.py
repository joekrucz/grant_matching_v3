"""
URL configuration for slack_bot app.
"""
from django.urls import path
from . import views

app_name = 'slack_bot'

urlpatterns = [
    path('slack/events', views.slack_events, name='slack_events'),
    path('slack/commands', views.slack_commands, name='slack_commands'),
]

