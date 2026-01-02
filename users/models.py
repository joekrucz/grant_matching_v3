"""
User model with email confirmation and password reset functionality.
"""
import secrets
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """Custom user manager where email is the unique identifier."""
    
    def create_user(self, email, password=None, **extra_fields):
        """Create and save a user with the given email and password."""
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        """Create and save a superuser with the given email and password."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('admin', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('email_confirmed_at', timezone.now())
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom user model with email as username."""
    
    email = models.EmailField(unique=True, db_index=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    admin = models.BooleanField(default=False)
    theme = models.CharField(max_length=50, blank=True, null=True)
    custom_theme = models.JSONField(default=dict, blank=True)  # Stores custom theme color values
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(blank=True, null=True)
    
    # Email confirmation fields
    email_confirmed_at = models.DateTimeField(blank=True, null=True)
    confirmation_token = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    unconfirmed_email = models.EmailField(blank=True, null=True)
    
    # Password reset fields
    reset_password_token = models.CharField(max_length=255, blank=True, null=True, db_index=True)
    reset_password_sent_at = models.DateTimeField(blank=True, null=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
    
    class Meta:
        db_table = 'users'
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['confirmation_token']),
            models.Index(fields=['reset_password_token']),
        ]
    
    def __str__(self):
        return self.email
    
    def generate_confirmation_token(self):
        """Generate a unique confirmation token."""
        self.confirmation_token = secrets.token_urlsafe(32)
        self.save(update_fields=['confirmation_token'])
        return self.confirmation_token
    
    def generate_reset_token(self):
        """Generate a unique password reset token."""
        self.reset_password_token = secrets.token_urlsafe(32)
        self.reset_password_sent_at = timezone.now()
        self.save(update_fields=['reset_password_token', 'reset_password_sent_at'])
        return self.reset_password_token
    
    def confirm_email(self):
        """Confirm the user's email address."""
        if self.unconfirmed_email:
            self.email = self.unconfirmed_email
            self.unconfirmed_email = None
        self.email_confirmed_at = timezone.now()
        self.confirmation_token = None
        self.save(update_fields=['email', 'unconfirmed_email', 'email_confirmed_at', 'confirmation_token'])
    
    @property
    def is_email_confirmed(self):
        """Check if email is confirmed."""
        return self.email_confirmed_at is not None

