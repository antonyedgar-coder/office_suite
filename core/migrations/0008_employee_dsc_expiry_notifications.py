from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_alter_employee_branch_access"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="receive_dsc_expiry_notifications",
            field=models.BooleanField(
                default=False,
                help_text="Receive DSC expiry reminders (in addition to users with DSC Management view access).",
            ),
        ),
    ]
