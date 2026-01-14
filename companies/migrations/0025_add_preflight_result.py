from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0024_add_checklist_assessment_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="fundingsearch",
            name="preflight_result",
            field=models.JSONField(
                default=dict,
                blank=True,
                help_text=(
                    "Pre-flight quality assessment for this funding search "
                    "(coverage, clarity, completeness, etc.)"
                ),
            ),
        ),
    ]

