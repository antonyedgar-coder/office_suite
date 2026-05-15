import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DirectorMapping",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("appointed_date", models.DateField()),
                ("cessation_date", models.DateField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "company",
                    models.ForeignKey(
                        help_text="Select the company (limited list by client type).",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="director_appointments",
                        to="masters.client",
                    ),
                ),
                (
                    "director",
                    models.ForeignKey(
                        help_text="Select the director record from Client Master (Individual with DIN).",
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="director_roles",
                        to="masters.client",
                    ),
                ),
            ],
            options={"ordering": ["-appointed_date", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="directormapping",
            constraint=models.UniqueConstraint(
                fields=("director", "company", "appointed_date"),
                name="uniq_director_company_appointed",
            ),
        ),
    ]

