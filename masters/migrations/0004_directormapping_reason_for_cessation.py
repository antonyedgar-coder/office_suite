from django.db import migrations, models


def set_default_reason_for_existing_cessions(apps, schema_editor):
    DirectorMapping = apps.get_model("masters", "DirectorMapping")
    DirectorMapping.objects.filter(cessation_date__isnull=False, reason_for_cessation="").update(
        reason_for_cessation="Resigned",
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0003_merge_branches_remove_director"),
    ]

    operations = [
        migrations.AddField(
            model_name="directormapping",
            name="reason_for_cessation",
            field=models.CharField(
                blank=True,
                choices=[
                    ("Resigned", "Resigned"),
                    ("Disqualified", "Disqualified"),
                    ("Terminated", "Terminated"),
                    ("Death", "Death"),
                ],
                max_length=32,
                verbose_name="Reason for cessation",
            ),
        ),
        migrations.RunPython(set_default_reason_for_existing_cessions, noop_reverse),
    ]
