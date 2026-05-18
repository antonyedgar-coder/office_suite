import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0017_client_id_branch_prefix"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tasks", "0007_task_pending_assignment"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClientActivityLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("client_master", "Client Master"),
                            ("director_mapping", "Director Mapping"),
                            ("task", "Task"),
                            ("mis", "MIS"),
                            ("dir3_kyc", "DIR-3 KYC"),
                        ],
                        max_length=32,
                    ),
                ),
                ("activity", models.TextField()),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "client",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="activity_logs",
                        to="masters.client",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="client_activity_logs",
                        to="tasks.task",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="clientactivitylog",
            index=models.Index(
                fields=["client", "created_at"],
                name="masters_cli_client__a1b2c3_idx",
            ),
        ),
    ]
