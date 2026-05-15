import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0001_initial"),
        ("core", "0002_user_force_password_change_employee"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="user_type",
            field=models.CharField(
                choices=[("employee", "Employee"), ("client", "Client")],
                db_index=True,
                default="employee",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="employee",
            name="linked_client",
            field=models.ForeignKey(
                blank=True,
                help_text="For Client-type users: Client Master record this login is tied to.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="portal_users",
                to="masters.client",
            ),
        ),
        migrations.AlterField(
            model_name="employee",
            name="date_of_joining",
            field=models.DateField(
                blank=True,
                help_text="Required for employees; optional for client portal users (filled from Client Master when blank).",
                null=True,
            ),
        ),
    ]
