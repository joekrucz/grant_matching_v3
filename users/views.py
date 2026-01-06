"""
User authentication views.
"""
import secrets
import time
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django_ratelimit.decorators import ratelimit
from .models import User
from .forms import SignUpForm, SignInForm, PasswordResetRequestForm, PasswordResetForm


@ratelimit(key='ip', rate='5/m', method='POST', block=True)
@never_cache
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


@ratelimit(key='ip', rate='5/m', method='POST', block=True)
@never_cache
def sign_in(request):
    """User login view."""
    if request.user.is_authenticated:
        return redirect('/')
    
    if request.method == 'POST':
        form = SignInForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            
            # SECURITY: Add random delay to prevent timing attacks
            import random
            time.sleep(0.1 + random.uniform(0, 0.1))  # Random delay between 0.1-0.2 seconds
            
            try:
                user = User.objects.get(email=email)
                if user.check_password(password):
                    login(request, user)
                    user.last_login = timezone.now()
                    user.save(update_fields=['last_login'])
                    
                    # SECURITY: Validate next parameter to prevent open redirect attacks
                    from django.utils.http import url_has_allowed_host_and_scheme
                    next_url = request.GET.get('next', '/')
                    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                        return redirect(next_url)
                    return redirect('/')
                else:
                    # SECURITY: Same error message to prevent user enumeration
                    messages.error(request, 'Invalid email or password.')
            except User.DoesNotExist:
                # SECURITY: Same error message to prevent user enumeration
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


@ratelimit(key='ip', rate='3/m', method='POST', block=True)
@never_cache
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
        
        # SECURITY: Use explicit allowlist to prevent mass assignment
        allowed_fields = []
        
        # Validate and update name (max 255 chars)
        name = request.POST.get('name', '').strip()
        if name is not None:  # Allow empty name
            if len(name) > 255:
                messages.error(request, 'Name must be 255 characters or less.')
                return redirect('users:profile')
            user.name = name
            allowed_fields.append('name')
        
        # Validate and update theme
        theme = request.POST.get('theme', '').strip()
        # SECURITY: Validate theme against allowed values
        allowed_themes = ['light', 'dark', 'cupcake', 'bumblebee', 'emerald', 'corporate', 'synthwave', 'retro', 'cyberpunk', 'valentine', 'halloween', 'garden', 'forest', 'aqua', 'lofi', 'pastel', 'fantasy', 'wireframe', 'black', 'luxury', 'dracula', 'cmyk', 'autumn', 'business', 'acid', 'lemonade', 'night', 'coffee', 'winter', 'custom', None, '']
        if theme and theme not in allowed_themes:
            messages.error(request, 'Invalid theme selected.')
            return redirect('users:profile')
        user.theme = theme if theme else None
        allowed_fields.append('theme')
        
        # Handle custom theme colors
        import json
        import re
        custom_theme_data = {}
        if request.POST.get('use_custom_theme') == 'true':
            # Collect custom theme color values
            # Use underscores in JSON keys, convert to hyphens for CSS
            color_fields = ['primary', 'secondary', 'accent', 'neutral', 'base_100', 'base_200', 'base_300', 'base_content', 'info', 'success', 'warning', 'error']
            for field in color_fields:
                color_value = request.POST.get(f'custom_theme_{field}', '').strip()
                if color_value:
                    # SECURITY: Validate hex color format (#RRGGBB or #RRGGBBAA)
                    if not re.match(r'^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$', color_value):
                        messages.error(request, f'Invalid color format for {field}. Use hex format (#RRGGBB).')
                        return redirect('users:profile')
                    # SECURITY: Limit color value length
                    if len(color_value) > 9:  # Max #RRGGBBAA
                        messages.error(request, f'Color value too long for {field}.')
                        return redirect('users:profile')
                    custom_theme_data[field] = color_value
            user.custom_theme = custom_theme_data
            # Set theme to 'custom' if custom colors are provided
            if custom_theme_data:
                user.theme = 'custom'
                allowed_fields.append('theme')
        else:
            # Clear custom theme if not using it
            user.custom_theme = {}
        allowed_fields.append('custom_theme')
        
        # Handle password change if provided
        current_password = request.POST.get('current_password', '').strip()
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()
        
        if new_password:  # User wants to change password
            # SECURITY: Validate password length
            if len(new_password) < 8:
                messages.error(request, 'Password must be at least 8 characters long.')
                return redirect('users:profile')
            if len(new_password) > 128:
                messages.error(request, 'Password must be 128 characters or less.')
                return redirect('users:profile')
            
            if not current_password:
                messages.error(request, 'Please enter your current password to change it.')
                return redirect('users:profile')
            
            if not user.check_password(current_password):
                messages.error(request, 'Current password is incorrect.')
                return redirect('users:profile')
            
            if new_password != confirm_password:
                messages.error(request, 'New passwords do not match.')
                return redirect('users:profile')
            
            user.set_password(new_password)
            allowed_fields.append('password')  # Note: password is hashed, so this is safe
            messages.success(request, 'Password updated successfully.')
        
        # SECURITY: Only save explicitly allowed fields
        if allowed_fields:
            user.save(update_fields=allowed_fields)
        else:
            messages.info(request, 'No changes to save.')
        
        return redirect('users:profile')
    
    return render(request, 'users/profile.html')

