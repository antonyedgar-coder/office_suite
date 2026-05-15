from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def _add_approve_client_permission(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct = ContentType.objects.get(app_label="masters", model="client")
    Permission.objects.get_or_create(
        content_type=ct,
        codename="approve_client",
        defaults={"name": "Can approve client master records"},
    )


def _noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("masters", "0009_client_passport_aadhaar_foreign_citizen"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="approval_status",
            field=models.CharField(
                choices=[("approved", "Approved"), ("pending", "Pending approval")],
                db_index=True,
                default="approved",
                max_length=16,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="client",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="client",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="clients_approved",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="client",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="clients_created",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(_add_approve_client_permission, _noop),
    ]
