"""
Tests for user views (authentication, profile).
"""
import pytest
from django.urls import reverse
from django.contrib.auth import get_user_model
from users.tests.factories import UserFactory

User = get_user_model()


@pytest.mark.django_db
class TestSignUp:
    """Test user sign up functionality."""
    
    def test_sign_up_get(self, client):
        """Test sign up page loads."""
        response = client.get(reverse('users:sign_up'))
        assert response.status_code == 200
    
    def test_sign_up_post_valid(self, client):
        """Test successful user sign up."""
        response = client.post(reverse('users:sign_up'), {
            'email': 'newuser@example.com',
            'name': 'New User',
            'password1': 'SecurePass123!',
            'password2': 'SecurePass123!',
        })
        # Should redirect after successful signup
        assert response.status_code == 302
        assert User.objects.filter(email='newuser@example.com').exists()
    
    def test_sign_up_post_invalid_password(self, client):
        """Test sign up with mismatched passwords."""
        response = client.post(reverse('users:sign_up'), {
            'email': 'newuser@example.com',
            'name': 'New User',
            'password1': 'SecurePass123!',
            'password2': 'DifferentPass123!',
        })
        assert response.status_code == 200  # Stays on page with errors
        assert not User.objects.filter(email='newuser@example.com').exists()


@pytest.mark.django_db
class TestSignIn:
    """Test user sign in functionality."""
    
    def test_sign_in_get(self, client):
        """Test sign in page loads."""
        response = client.get(reverse('users:sign_in'))
        assert response.status_code == 200
    
    def test_sign_in_post_valid(self, client):
        """Test successful sign in."""
        user = UserFactory(email='test@example.com')
        user.set_password('testpass123')
        user.save()
        
        response = client.post(reverse('users:sign_in'), {
            'email': 'test@example.com',
            'password': 'testpass123',
        })
        assert response.status_code == 302  # Redirect after login
    
    def test_sign_in_post_invalid(self, client):
        """Test sign in with wrong password."""
        user = UserFactory(email='test@example.com')
        user.set_password('testpass123')
        user.save()
        
        response = client.post(reverse('users:sign_in'), {
            'email': 'test@example.com',
            'password': 'wrongpassword',
        })
        assert response.status_code == 200  # Stays on page with error
    
    def test_sign_in_requires_authentication(self, client):
        """Test sign in page is accessible without authentication."""
        response = client.get(reverse('users:sign_in'))
        assert response.status_code == 200


@pytest.mark.django_db
class TestSignOut:
    """Test user sign out functionality."""
    
    def test_sign_out(self, client, user):
        """Test user can sign out."""
        client.force_login(user)
        response = client.get(reverse('users:sign_out'))
        assert response.status_code == 302  # Redirect after logout


@pytest.mark.django_db
class TestProfile:
    """Test user profile view."""
    
    def test_profile_requires_login(self, client):
        """Test profile page requires authentication."""
        response = client.get(reverse('users:profile'))
        assert response.status_code == 302  # Redirect to login
    
    def test_profile_accessible_when_logged_in(self, client, user):
        """Test profile page accessible when logged in."""
        client.force_login(user)
        response = client.get(reverse('users:profile'))
        assert response.status_code == 200
    
    def test_profile_update_name(self, client, user):
        """Test updating profile name."""
        client.force_login(user)
        response = client.post(reverse('users:profile'), {
            'name': 'Updated Name',
        })
        assert response.status_code == 302  # Redirect after update
        
        user.refresh_from_db()
        assert user.name == 'Updated Name'




