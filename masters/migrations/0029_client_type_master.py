from django.db import migrations, models


def seed_client_types(apps, schema_editor):
    ClientType = apps.get_model("masters", "ClientType")
    Client = apps.get_model("masters", "Client")

    pan_optional = {
        "New Client",
        "One Off Client",
        "Foreign Citizen",
        "Branch",
    }
    no_submit_without_pan = {"New Client"}

    defaults = [
        ("Individual", 10),
        ("Partnership", 20),
        ("LLP", 30),
        ("Branch", 40),
        ("Private Limited", 50),
        ("Public Limited", 60),
        ("Nidhi Co", 70),
        ("FPO", 80),
        ("Trust", 90),
        ("Sec 8 Co", 100),
        ("Society", 110),
        ("Foreign Citizen", 120),
        ("New Client", 130),
        ("One Off Client", 140),
    ]
    for name, sort_order in defaults:
        ClientType.objects.update_or_create(
            name=name,
            defaults={
                "pan_mandatory": name not in pan_optional,
                "allow_task_submit_without_pan": name not in no_submit_without_pan,
                "is_active": True,
                "sort_order": sort_order,
            },
        )

    # Legacy type label on old rows
    Client.objects.filter(client_type="None").update(client_type="New Client")

    used = set(Client.objects.values_list("client_type", flat=True).distinct())
    for type_name in used:
        if type_name and not ClientType.objects.filter(name=type_name).exists():
            ClientType.objects.create(
                name=type_name,
                pan_mandatory=type_name not in pan_optional,
                allow_task_submit_without_pan=type_name not in no_submit_without_pan,
                is_active=True,
                sort_order=900,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0028_client_id_remove_branch_prefix"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClientType",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=64, unique=True)),
                ("pan_mandatory", models.BooleanField(default=True)),
                (
                    "allow_task_submit_without_pan",
                    models.BooleanField(
                        default=True,
                        help_text=(
                            "When PAN is not mandatory and left blank, assignees may submit tasks "
                            "for verification. Turn off for types like New Client."
                        ),
                        verbose_name="Allow task submit when PAN is not applicable",
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "client type",
                "verbose_name_plural": "client types",
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.AlterField(
            model_name="client",
            name="client_type",
            field=models.CharField(max_length=64),
        ),
        migrations.RunPython(seed_client_types, migrations.RunPython.noop),
    ]
