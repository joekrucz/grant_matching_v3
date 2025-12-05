"""
User authentication views.
"""
import secrets
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from .models import User
from .forms import SignUpForm, SignInForm, PasswordResetRequestForm, PasswordResetForm


def sign_up(request):
    """User registration view."""
    if request.user.is_authenticated:
        return redirect('/')
    
    if request.method == 'POST':
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            # Auto-confirm email on signup
            user.email_confirmed_at = timezone.now()
            user.save()
            
            messages.success(request, 'Registration successful! You can now sign in.')
            return redirect('users:sign_in')
    else:
        form = SignUpForm()
    
    return render(request, 'users/sign_up.html', {'form': form})


def sign_in(request):
    """User login view."""
    if request.user.is_authenticated:
        return redirect('/')
    
    if request.method == 'POST':
        form = SignInForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            
            try:
                user = User.objects.get(email=email)
                if user.check_password(password):
                    login(request, user)
                    user.last_login = timezone.now()
                    user.save(update_fields=['last_login'])
                    return redirect(request.GET.get('next', '/'))
                else:
                    messages.error(request, 'Invalid email or password.')
            except User.DoesNotExist:
                messages.error(request, 'Invalid email or password.')
    else:
        form = SignInForm()
    
    return render(request, 'users/sign_in.html', {'form': form})


def sign_out(request):
    """User logout view."""
    logout(request)
    messages.success(request, 'You have been signed out successfully.')
    return redirect('/')


def confirm_email(request, token):
    """Email confirmation view."""
    try:
        user = User.objects.get(confirmation_token=token)
        user.confirm_email()
        messages.success(request, 'Your email has been confirmed! You can now sign in.')
        return redirect('users:sign_in')
    except User.DoesNotExist:
        messages.error(request, 'Invalid confirmation token.')
        return redirect('users:sign_in')


def password_reset_request(request):
    """Password reset request view."""
    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            try:
                user = User.objects.get(email=email)
                token = user.generate_reset_token()
                reset_url = request.build_absolute_uri(
                    reverse('users:password_reset', kwargs={'token': token})
                )
                
                send_mail(
                    'Reset your password',
                    f'Click this link to reset your password: {reset_url}',
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=False,
                )
                
                messages.success(request, 'Password reset instructions have been sent to your email.')
                return redirect('users:sign_in')
            except User.DoesNotExist:
                # Don't reveal if email exists
                messages.success(request, 'If that email exists, password reset instructions have been sent.')
                return redirect('users:sign_in')
    else:
        form = PasswordResetRequestForm()
    
    return render(request, 'users/password_reset_request.html', {'form': form})


def password_reset(request, token):
    """Password reset view."""
    try:
        user = User.objects.get(reset_password_token=token)
        # Check if token is not expired (24 hours)
        if user.reset_password_sent_at:
            time_diff = timezone.now() - user.reset_password_sent_at
            if time_diff.total_seconds() > 86400:  # 24 hours
                messages.error(request, 'Password reset token has expired.')
                return redirect('users:password_reset_request')
    except User.DoesNotExist:
        messages.error(request, 'Invalid password reset token.')
        return redirect('users:password_reset_request')
    
    if request.method == 'POST':
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data['password'])
            user.reset_password_token = None
            user.reset_password_sent_at = None
            user.save()
            messages.success(request, 'Your password has been reset. Please sign in.')
            return redirect('users:sign_in')
    else:
        form = PasswordResetForm()
    
    return render(request, 'users/password_reset.html', {'form': form, 'token': token})


def resend_confirmation(request):
    """Resend confirmation email view."""
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email)
            if user.is_email_confirmed:
                messages.info(request, 'Your email is already confirmed.')
                return redirect('users:sign_in')
            
            token = user.generate_confirmation_token()
            confirmation_url = request.build_absolute_uri(
                reverse('users:confirm_email', kwargs={'token': token})
            )
            
            send_mail(
                'Confirm your email address',
                f'Please confirm your email by clicking this link: {confirmation_url}',
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
            
            messages.success(request, 'Confirmation email has been sent.')
        except User.DoesNotExist:
            messages.error(request, 'Email not found.')
    
    return render(request, 'users/resend_confirmation.html')


@login_required
def profile(request):
    """User profile view."""
    if request.method == 'POST':
        user = request.user
        
        # Handle profile updates
        user.name = request.POST.get('name', user.name)
        theme = request.POST.get('theme', '').strip()
        user.theme = theme if theme else None
        
        # Handle password change if provided
        current_password = request.POST.get('current_password', '').strip()
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()
        
        if new_password:  # User wants to change password
            if not current_password:
                messages.error(request, 'Please enter your current password to change it.')
                return render(request, 'users/profile.html')
            
            if not user.check_password(current_password):
                messages.error(request, 'Current password is incorrect.')
                return render(request, 'users/profile.html')
            
            if new_password != confirm_password:
                messages.error(request, 'New passwords do not match.')
                return render(request, 'users/profile.html')
            
            if len(new_password) < 8:
                messages.error(request, 'Password must be at least 8 characters long.')
                return render(request, 'users/profile.html')
            
            user.set_password(new_password)
            messages.success(request, 'Password updated successfully.')
        
        user.save()
        if not new_password:  # Only show profile update message if password wasn't changed
            messages.success(request, 'Profile updated successfully.')
        return redirect('users:profile')
    
    return render(request, 'users/profile.html')

