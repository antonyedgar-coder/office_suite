from django.db import migrations, models


def rename_none_to_new_client(apps, schema_editor):
    Client = apps.get_model("masters", "Client")
    Client.objects.filter(client_type="None").update(client_type="New Client")


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0026_rename_masters_cli_expiry__dsc01_idx_masters_cli_expiry__b97558_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(rename_none_to_new_client, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="client",
            name="client_type",
            field=models.CharField(
                choices=[
                    ("Individual", "Individual"),
                    ("Partnership", "Partnership"),
                    ("LLP", "LLP"),
                    ("Branch", "Branch"),
                    ("Private Limited", "Private Limited"),
                    ("Public Limited", "Public Limited"),
                    ("Nidhi Co", "Nidhi Co"),
                    ("FPO", "FPO"),
                    ("Trust", "Trust"),
                    ("Sec 8 Co", "Sec 8 Co"),
                    ("Society", "Society"),
                    ("Foreign Citizen", "Foreign Citizen"),
                    ("New Client", "New Client"),
                    ("One Off Client", "One Off Client"),
                ],
                max_length=32,
            ),
        ),
    ]
