from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0019_rename_masters_cli_client__a1b2c3_idx_masters_cli_client__420ef2_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="remarks",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="directormapping",
            name="remarks",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
