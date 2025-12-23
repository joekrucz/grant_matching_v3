from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('companies', '0010_companyfile'),
    ]

    operations = [
        migrations.CreateModel(
            name='CompanyNote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(blank=True, max_length=255, null=True)),
                ('body', models.TextField()),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='company_notes', to='companies.company')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='company_notes', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'company_notes',
                'ordering': ['-created_at'],
            },
        ),
    ]


