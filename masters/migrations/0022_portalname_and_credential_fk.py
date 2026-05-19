import django.db.models.deletion
from django.db import migrations, models


def copy_portal_names(apps, schema_editor):
    PortalName = apps.get_model("masters", "PortalName")
    ClientPortalCredential = apps.get_model("masters", "ClientPortalCredential")
    for cred in ClientPortalCredential.objects.all():
        label = (getattr(cred, "portal_name", None) or "").strip() or "(Unspecified)"
        portal, _ = PortalName.objects.get_or_create(name=label)
        cred.portal_id = portal.pk
        cred.save(update_fields=["portal_id"])


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0021_clientportalcredential"),
    ]

    operations = [
        migrations.CreateModel(
            name="PortalName",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "portal name",
                "verbose_name_plural": "portal names",
                "ordering": ["name"],
            },
        ),
        migrations.AddField(
            model_name="clientportalcredential",
            name="portal",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="credentials",
                to="masters.portalname",
                verbose_name="Portal name",
            ),
        ),
        migrations.RunPython(copy_portal_names, migrations.RunPython.noop),
        migrations.RemoveIndex(
            model_name="clientportalcredential",
            name="masters_cli_portal__a8f2e1_idx",
        ),
        migrations.RemoveField(
            model_name="clientportalcredential",
            name="portal_name",
        ),
        migrations.AlterField(
            model_name="clientportalcredential",
            name="portal",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="credentials",
                to="masters.portalname",
                verbose_name="Portal name",
            ),
        ),
        migrations.AddIndex(
            model_name="clientportalcredential",
            index=models.Index(fields=["portal"], name="masters_cli_portal_fk_idx"),
        ),
    ]
