import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="force_password_change",
            field=models.BooleanField(
                default=False,
                help_text="If true, user must change password before using the app (first login after invite).",
            ),
        ),
        migrations.CreateModel(
            name="Employee",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("full_name", models.CharField(max_length=200)),
                ("contact_no", models.CharField(blank=True, max_length=20)),
                ("address", models.CharField(blank=True, max_length=500)),
                ("date_of_joining", models.DateField()),
                (
                    "contact_person",
                    models.CharField(
                        blank=True,
                        help_text="Emergency / alternate contact name",
                        max_length=200,
                    ),
                ),
                ("aadhar_no", models.CharField(blank=True, max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="employee_profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["full_name"],
            },
        ),
    ]
