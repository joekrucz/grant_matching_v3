"""
Script to create admin user if it doesn't exist.
Run this via Railway dashboard or add to entrypoint.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'grants_aggregator.settings')
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

email = os.environ.get('ADMIN_EMAIL', 'joseph.krucz@gmail.com')
password = os.environ.get('ADMIN_PASSWORD', 'changeme123')  # Change this via environment variable
name = os.environ.get('ADMIN_NAME', 'Joseph Kruczkowski')

if User.objects.filter(email=email).exists():
    user = User.objects.get(email=email)
    user.is_staff = True
    user.is_superuser = True
    user.admin = True
    user.is_active = True
    user.set_password(password)
    user.save()
    print(f'Updated existing user {email} to admin')
else:
    user = User.objects.create_user(
        email=email,
        password=password,
        name=name,
        is_staff=True,
        is_superuser=True,
        admin=True,
        is_active=True,
    )
    print(f'Created admin user: {email}')

print(f'Admin user ready. Email: {email}, Password: {password}')
print('⚠️  IMPORTANT: Change the password after first login!')

