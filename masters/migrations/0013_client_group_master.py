import django.db.models.deletion
from django.db import migrations, models


def forwards_migrate_group_text_to_fk(apps, schema_editor):
    Client = apps.get_model("masters", "Client")
    ClientGroup = apps.get_model("masters", "ClientGroup")
    for c in Client.objects.all():
        txt = (getattr(c, "legacy_group_text", None) or "").strip()
        if not txt:
            continue
        name = txt.upper()
        g, _ = ClientGroup.objects.get_or_create(name=name, defaults={"notes": "", "is_active": True})
        c.client_group_id = g.pk
        c.save(update_fields=["client_group_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0012_client_dob"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClientGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("notes", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Group",
                "verbose_name_plural": "Groups",
                "ordering": ["name"],
            },
        ),
        migrations.RenameField(
            model_name="client",
            old_name="client_group",
            new_name="legacy_group_text",
        ),
        migrations.AddField(
            model_name="client",
            name="client_group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="clients",
                to="masters.clientgroup",
                verbose_name="Group",
            ),
        ),
        migrations.RunPython(forwards_migrate_group_text_to_fk, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="client",
            name="legacy_group_text",
        ),
    ]
