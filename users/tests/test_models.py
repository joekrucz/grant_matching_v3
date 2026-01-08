"""
Tests for User model.
"""
import pytest
from django.utils import timezone
from django.contrib.auth import get_user_model
from users.tests.factories import UserFactory

User = get_user_model()


@pytest.mark.django_db
class TestUser:
    """Test User model methods and properties."""
    
    def test_user_str(self):
        """Test user string representation."""
        user = UserFactory(email='test@example.com')
        assert str(user) == 'test@example.com'
    
    def test_generate_confirmation_token(self):
        """Test confirmation token generation."""
        user = UserFactory()
        token = user.generate_confirmation_token()
        
        assert token is not None
        assert len(token) > 0
        assert user.confirmation_token == token
    
    def test_generate_reset_token(self):
        """Test password reset token generation."""
        user = UserFactory()
        token = user.generate_reset_token()
        
        assert token is not None
        assert len(token) > 0
        assert user.reset_password_token == token
        assert user.reset_password_sent_at is not None
    
    def test_confirm_email(self):
        """Test email confirmation."""
        user = UserFactory(email='old@example.com', unconfirmed_email='new@example.com')
        user.confirm_email()
        
        assert user.email == 'new@example.com'
        assert user.unconfirmed_email is None
        assert user.email_confirmed_at is not None
        assert user.confirmation_token is None
    
    def test_is_email_confirmed_property(self):
        """Test is_email_confirmed property."""
        user = UserFactory(email_confirmed_at=None)
        assert user.is_email_confirmed is False
        
        user.email_confirmed_at = timezone.now()
        user.save()
        assert user.is_email_confirmed is True






