from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0008_remove_directormapping_active_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="passport_no",
            field=models.CharField(blank=True, max_length=24, verbose_name="Passport No"),
        ),
        migrations.AddField(
            model_name="client",
            name="aadhaar_no",
            field=models.CharField(blank=True, max_length=12, verbose_name="Aadhaar No"),
        ),
        migrations.AddIndex(
            model_name="client",
            index=models.Index(fields=["passport_no"], name="masters_cli_passport_idx"),
        ),
    ]
