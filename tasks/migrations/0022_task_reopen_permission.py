"""Add reopen_task permission and grant to Admin group."""

from django.db import migrations


def grant_reopen_to_admin_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")

    task_ct = ContentType.objects.filter(app_label="tasks", model="task").first()
    if not task_ct:
        return
    reopen_perm = Permission.objects.filter(
        content_type=task_ct,
        codename="reopen_task",
    ).first()
    if not reopen_perm:
        return

    for group in Group.objects.all():
        if (group.name or "").lower() in ("admin", "administrator", "super admin"):
            group.permissions.add(reopen_perm)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0021_task_workflow_flags"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="task",
            options={
                "ordering": ["-due_date", "-created_at"],
                "permissions": [
                    ("assign_task", "Can assign task"),
                    ("verify_task", "Can verify task"),
                    ("check_documents", "Can check task documents"),
                    ("reopen_task", "Can reopen completed task"),
                ],
            },
        ),
        migrations.RunPython(grant_reopen_to_admin_groups, noop),
    ]
