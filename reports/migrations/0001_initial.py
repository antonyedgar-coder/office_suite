# Generated manually for ReportPolicy

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ReportPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(default="default", max_length=80)),
            ],
            options={
                "verbose_name": "Report access policy",
                "verbose_name_plural": "Report access policies",
                "default_permissions": (),
                "permissions": [
                    ("access_reports_menu", "Can access Reports menu and index"),
                    ("view_client_master_report", "Can view Client Master report"),
                    ("export_client_master_report", "Can export Client Master report CSV"),
                ],
            },
        ),
    ]
