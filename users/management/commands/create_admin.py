"""
Management command to create an admin user.
Usage: python manage.py create_admin --email admin@example.com --password securepassword
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

User = get_user_model()


class Command(BaseCommand):
    help = 'Create an admin user'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            required=True,
            help='Email address for the admin user'
        )
        parser.add_argument(
            '--password',
            type=str,
            required=True,
            help='Password for the admin user'
        )
        parser.add_argument(
            '--name',
            type=str,
            default='',
            help='Full name for the admin user (optional)'
        )
        parser.add_argument(
            '--no-input',
            action='store_true',
            help='Skip confirmation prompts'
        )

    def handle(self, *args, **options):
        email = options['email']
        password = options['password']
        name = options.get('name', '')
        no_input = options.get('no_input', False)

        # Check if user already exists
        if User.objects.filter(email=email).exists():
            if not no_input:
                self.stdout.write(
                    self.style.WARNING(f'User with email {email} already exists.')
                )
                overwrite = input('Do you want to update this user to be an admin? (yes/no): ')
                if overwrite.lower() != 'yes':
                    self.stdout.write(self.style.ERROR('Operation cancelled.'))
                    return
                
                user = User.objects.get(email=email)
                user.set_password(password)
                user.is_staff = True
                user.is_superuser = True
                user.admin = True
                if name:
                    user.name = name
                user.save()
                self.stdout.write(
                    self.style.SUCCESS(f'Successfully updated user {email} to admin.')
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f'User with email {email} already exists. Use --no-input to update.')
                )
            return

        # Create new admin user
        try:
            user = User.objects.create_user(
                email=email,
                password=password,
                name=name if name else None,
                is_staff=True,
                is_superuser=True,
                admin=True,
            )
            self.stdout.write(
                self.style.SUCCESS(f'Successfully created admin user: {email}')
            )
        except ValidationError as e:
            self.stdout.write(
                self.style.ERROR(f'Error creating user: {e}')
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Unexpected error: {e}')
            )

