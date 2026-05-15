from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0006_alter_client_branch"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="directormapping",
            constraint=models.UniqueConstraint(
                fields=("director", "company"),
                condition=Q(cessation_date__isnull=True),
                name="uniq_directormapping_active_director_company",
            ),
        ),
    ]
