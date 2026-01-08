# Generated manually to add support for multiple file uploads

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('companies', '0019_increase_company_number_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='FundingSearchFile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='funding_searches/%Y/%m/')),
                ('original_name', models.CharField(blank=True, max_length=255, null=True)),
                ('file_type', models.CharField(blank=True, max_length=50, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('funding_search', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='uploaded_files', to='companies.fundingsearch')),
                ('uploaded_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='funding_search_files', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'funding_search_files',
                'ordering': ['-created_at'],
            },
        ),
    ]



