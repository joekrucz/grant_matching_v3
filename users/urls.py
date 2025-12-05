"""
URL configuration for users app.
"""
from django.urls import path
from . import views

app_name = 'users'

urlpatterns = [
    path('sign_up', views.sign_up, name='sign_up'),
    path('sign_in', views.sign_in, name='sign_in'),
    path('sign_out', views.sign_out, name='sign_out'),
    path('confirmation/<str:token>', views.confirm_email, name='confirm_email'),
    path('confirmation/new', views.resend_confirmation, name='resend_confirmation'),
    path('password/new', views.password_reset_request, name='password_reset_request'),
    path('password/edit/<str:token>', views.password_reset, name='password_reset'),
    path('profile', views.profile, name='profile'),
]

