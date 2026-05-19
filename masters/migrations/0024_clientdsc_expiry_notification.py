import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0023_clientdsc_dscinout"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="clientdsc",
            name="expiry_notification",
            field=models.BooleanField(
                default=False,
                help_text="If yes, send expiry reminders (30 days before expiry, every 7 days) until stopped.",
            ),
        ),
        migrations.AddField(
            model_name="clientdsc",
            name="last_expiry_notification_sent_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Last time an expiry reminder was sent for this DSC record.",
                null=True,
            ),
        ),
        migrations.CreateModel(
            name="DSCNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message", models.TextField()),
                ("link", models.CharField(blank=True, max_length=512)),
                ("is_read", models.BooleanField(db_index=True, default=False)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "dsc",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to="masters.clientdsc",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dsc_notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["user", "is_read", "created_at"], name="masters_dsc_user_rea_8a1f2c_idx"),
                ],
            },
        ),
    ]
