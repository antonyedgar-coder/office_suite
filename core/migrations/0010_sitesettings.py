from django.db import migrations, models

import core.models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_created_by_and_access_group_meta"),
    ]

    operations = [
        migrations.CreateModel(
            name="SiteSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "company_name",
                    models.CharField(
                        blank=True,
                        help_text="Shown above CA Office Suite in the sidebar and on the login page.",
                        max_length=120,
                    ),
                ),
                (
                    "logo",
                    models.FileField(
                        blank=True,
                        help_text="PNG, JPG, WEBP, GIF, or SVG. Recommended height about 40px.",
                        null=True,
                        upload_to=core.models.site_settings_upload_to,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Site settings",
                "verbose_name_plural": "Site settings",
            },
        ),
    ]
