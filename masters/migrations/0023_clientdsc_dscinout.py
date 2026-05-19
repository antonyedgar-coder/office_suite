import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0022_portalname_and_credential_fk"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ClientDSC",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("issue_date", models.DateField()),
                ("expiry_date", models.DateField()),
                ("dsc_password", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "client",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dsc_records",
                        to="masters.client",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="client_dsc_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="client_dsc_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "client DSC",
                "verbose_name_plural": "client DSC records",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="DSCInOut",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("in_date", models.DateField()),
                ("out_date", models.DateField(blank=True, null=True)),
                ("remarks", models.TextField(blank=True, default="")),
                (
                    "dsc",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="in_out",
                        to="masters.clientdsc",
                    ),
                ),
            ],
            options={
                "verbose_name": "DSC in-out",
                "verbose_name_plural": "DSC in-out records",
                "ordering": ["-in_date", "-pk"],
            },
        ),
        migrations.AddIndex(
            model_name="clientdsc",
            index=models.Index(fields=["expiry_date"], name="masters_cli_expiry__dsc01_idx"),
        ),
        migrations.AddIndex(
            model_name="clientdsc",
            index=models.Index(fields=["client", "expiry_date"], name="masters_cli_client__dsc02_idx"),
        ),
    ]
