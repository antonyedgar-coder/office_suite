from django.db import migrations


def migrate_legacy_statuses(apps, schema_editor):
    Task = apps.get_model("tasks", "Task")
    Task.objects.filter(status__in=["draft", "in_progress"]).update(status="assigned")


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0004_rename_tasks_task_client_status_idx_tasks_task_client__1e828c_idx_and_more"),
    ]

    operations = [
        migrations.RunPython(migrate_legacy_statuses, migrations.RunPython.noop),
    ]
