"""
Test factories for users app.
"""
import factory
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    """Factory for creating test users."""
    
    class Meta:
        model = User
    
    email = factory.Sequence(lambda n: f'user{n}@example.com')
    name = factory.Faker('name')
    is_active = True
    admin = False
    email_confirmed_at = timezone.now()


class AdminUserFactory(UserFactory):
    """Factory for creating admin users."""
    admin = True
    is_staff = True
    is_superuser = True




