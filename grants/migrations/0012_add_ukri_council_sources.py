# Generated manually to add UKRI council sources

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grants', '0011_scraperun_scrapefinding'),
    ]

    operations = [
        migrations.AlterField(
            model_name='grant',
            name='source',
            field=models.CharField(
                choices=[
                    ('ukri', 'UKRI'),
                    ('bbsrc', 'BBSRC'),
                    ('epsrc', 'EPSRC'),
                    ('mrc', 'MRC'),
                    ('stfc', 'STFC'),
                    ('ahrc', 'AHRC'),
                    ('esrc', 'ESRC'),
                    ('nerc', 'NERC'),
                    ('nihr', 'NIHR'),
                    ('catapult', 'Catapult'),
                    ('innovate_uk', 'Innovate UK'),
                ],
                db_index=True,
                max_length=50
            ),
        ),
        migrations.AlterField(
            model_name='scrapelog',
            name='source',
            field=models.CharField(
                choices=[
                    ('ukri', 'UKRI'),
                    ('bbsrc', 'BBSRC'),
                    ('epsrc', 'EPSRC'),
                    ('mrc', 'MRC'),
                    ('stfc', 'STFC'),
                    ('ahrc', 'AHRC'),
                    ('esrc', 'ESRC'),
                    ('nerc', 'NERC'),
                    ('nihr', 'NIHR'),
                    ('catapult', 'Catapult'),
                    ('innovate_uk', 'Innovate UK'),
                ],
                db_index=True,
                max_length=50
            ),
        ),
        migrations.AlterField(
            model_name='scrapefinding',
            name='grant_source',
            field=models.CharField(
                choices=[
                    ('ukri', 'UKRI'),
                    ('bbsrc', 'BBSRC'),
                    ('epsrc', 'EPSRC'),
                    ('mrc', 'MRC'),
                    ('stfc', 'STFC'),
                    ('ahrc', 'AHRC'),
                    ('esrc', 'ESRC'),
                    ('nerc', 'NERC'),
                    ('nihr', 'NIHR'),
                    ('catapult', 'Catapult'),
                    ('innovate_uk', 'Innovate UK'),
                ],
                db_index=True,
                max_length=50
            ),
        ),
    ]
