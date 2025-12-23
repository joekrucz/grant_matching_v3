from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('companies', '0009_company_grants_received_360'),
    ]

    operations = [
        migrations.CreateModel(
            name='CompanyFile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to='company_files/%Y/%m/')),
                ('original_name', models.CharField(blank=True, max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='files', to='companies.company')),
                ('uploaded_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='company_files', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'company_files',
                'ordering': ['-created_at'],
            },
        ),
    ]

