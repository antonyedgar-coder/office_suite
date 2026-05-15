"""
Remove partial unique on (director, company) where cessation is null.

SQLite can treat this as a plain unique on (director_id, company_id), which blocks
legitimate reappointments after an earlier cessation. The rule is enforced in
DirectorMapping.clean() and bulk-import validation instead.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0007_directormapping_at_most_one_active"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="directormapping",
            name="uniq_directormapping_active_director_company",
        ),
    ]
