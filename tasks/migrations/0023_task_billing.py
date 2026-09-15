"""Add Accounts billing fields and permission."""

from django.db import migrations, models


def grant_billing_to_accounts_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    task_ct = ContentType.objects.filter(app_label="tasks", model="task").first()
    if not task_ct:
        return
    perm = Permission.objects.filter(
        content_type=task_ct,
        codename="manage_task_billing",
    ).first()
    if not perm:
        return

    for group in Group.objects.all():
        name = (group.name or "").lower()
        if name in (
            "admin",
            "administrator",
            "super admin",
            "accounts",
            "account",
            "accountant",
            "accountants",
        ) or "account" in name:
            group.permissions.add(perm)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0022_task_reopen_permission"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="bill_raised",
            field=models.BooleanField(
                default=False,
                help_text="Accounts: invoice/bill has been raised for this completed billable task.",
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="bill_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="bill_remarks",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterModelOptions(
            name="task",
            options={
                "ordering": ["-due_date", "-created_at"],
                "permissions": [
                    ("assign_task", "Can assign task"),
                    ("verify_task", "Can verify task"),
                    ("check_documents", "Can check task documents"),
                    ("reopen_task", "Can reopen completed task"),
                    ("manage_task_billing", "Can manage task billing (Accounts)"),
                ],
            },
        ),
        migrations.RunPython(grant_billing_to_accounts_groups, noop),
    ]
