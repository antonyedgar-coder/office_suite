# Merges the two parallel 0002 migrations and drops the legacy Director model.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0002_directormapping"),
        ("masters", "0002_rename_masters_cli_client__ccf7fa_idx_masters_cli_client__71df69_idx_and_more"),
    ]

    operations = [
        migrations.DeleteModel(name="Director"),
    ]
