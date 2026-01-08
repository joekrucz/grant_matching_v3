"""
Pytest configuration and shared fixtures.
"""
import pytest
from django.test import RequestFactory
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def rf():
    """Request factory for testing views."""
    return RequestFactory()


@pytest.fixture
def user(db):
    """Create a test user."""
    from users.tests.factories import UserFactory
    return UserFactory()


@pytest.fixture
def admin_user(db):
    """Create an admin user."""
    from users.tests.factories import AdminUserFactory
    return AdminUserFactory()


@pytest.fixture
def client_with_user(client, user):
    """Client with logged-in user."""
    client.force_login(user)
    return client


@pytest.fixture
def client_with_admin(client, admin_user):
    """Client with logged-in admin user."""
    client.force_login(admin_user)
    return client




