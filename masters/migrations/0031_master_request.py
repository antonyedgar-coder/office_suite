import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0001_initial"),
        ("masters", "0030_alter_clienttype_pan_mandatory"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MasterRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "request_type",
                    models.CharField(
                        choices=[
                            ("client_group", "Client group"),
                            ("task_master", "Task master"),
                            ("task_group", "Task group"),
                            ("new_task", "New task"),
                            ("portal_name", "Portal name"),
                            ("client_type", "Client type"),
                            ("new_client", "New client"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("remarks", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("submitted", "Submitted"),
                            ("completed", "Completed"),
                            ("cancelled", "Cancelled"),
                        ],
                        db_index=True,
                        default="submitted",
                        max_length=16,
                    ),
                ),
                ("object_id", models.CharField(blank=True, db_index=True, max_length=64)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "assigned_to",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="master_requests_assigned",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "client",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="master_requests",
                        to="masters.client",
                    ),
                ),
                (
                    "completed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="master_requests_completed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "content_type",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="contenttypes.contenttype",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="master_requests_submitted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "master request",
                "verbose_name_plural": "master requests",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="MasterRequestNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("submitted_assignee", "Assigned to you"),
                            ("submitted_requester", "Your submission"),
                            ("completed", "Completed"),
                        ],
                        max_length=32,
                    ),
                ),
                ("message", models.TextField()),
                ("is_read", models.BooleanField(db_index=True, default=False)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "master_request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to="masters.masterrequest",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="master_request_notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="masterrequest",
            index=models.Index(fields=["assigned_to", "status", "request_type"], name="masters_mas_assigne_8f4e2a_idx"),
        ),
        migrations.AddIndex(
            model_name="masterrequest",
            index=models.Index(fields=["requested_by", "status"], name="masters_mas_request_91c3b1_idx"),
        ),
        migrations.AddIndex(
            model_name="masterrequestnotification",
            index=models.Index(fields=["user", "is_read", "created_at"], name="masters_mas_user_id_2a8f01_idx"),
        ),
    ]
