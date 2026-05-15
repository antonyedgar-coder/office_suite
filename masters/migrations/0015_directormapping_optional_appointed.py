from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0014_group_id_sequence_and_bulk"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="directormapping",
            name="uniq_director_company_appointed",
        ),
        migrations.AlterField(
            model_name="directormapping",
            name="appointed_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="directormapping",
            constraint=models.UniqueConstraint(
                condition=Q(appointed_date__isnull=False),
                fields=("director", "company", "appointed_date"),
                name="uniq_director_company_appointed_date_set",
            ),
        ),
    ]
