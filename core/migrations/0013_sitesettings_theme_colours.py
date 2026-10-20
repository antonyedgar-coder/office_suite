from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_sitesettings_gstin_address"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="theme_primary",
            field=models.CharField(
                blank=True,
                default="#0369a1",
                help_text="Buttons, links, and active menu colour.",
                max_length=7,
            ),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="theme_sidebar",
            field=models.CharField(
                blank=True,
                default="#f1f5f9",
                help_text="Left menu background colour.",
                max_length=7,
            ),
        ),
    ]
