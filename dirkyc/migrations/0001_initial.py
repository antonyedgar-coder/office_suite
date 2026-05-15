import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("masters", "0008_remove_directormapping_active_unique"),
    ]

    operations = [
        migrations.CreateModel(
            name="Dir3Kyc",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date_done", models.DateField(verbose_name="Date of DIR-3 KYC done")),
                ("srn", models.CharField(max_length=40, verbose_name="SRN (DIR e-KYC)")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "director",
                    models.ForeignKey(
                        help_text="Individual director with DIN from Client Master.",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dir3_kyc_records",
                        to="masters.client",
                    ),
                ),
            ],
            options={
                "verbose_name": "DIR-3 KYC record",
                "verbose_name_plural": "DIR-3 KYC records",
                "ordering": ["-date_done", "-id"],
            },
        ),
    ]
