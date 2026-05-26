from django.conf import settings
from django.db import migrations, models


def copy_verifier_to_m2m(apps, schema_editor):
    Task = apps.get_model("tasks", "Task")
    Enrollment = apps.get_model("tasks", "TaskRecurrenceEnrollment")
    for task in Task.objects.exclude(verifier_id=None).iterator():
        task.verifiers.add(task.verifier_id)
    for enrollment in Enrollment.objects.exclude(verifier_id=None).iterator():
        enrollment.verifiers.add(enrollment.verifier_id)


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0015_taskchecklist_not_applicable"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="verifiers",
            field=models.ManyToManyField(
                related_name="tasks_to_verify",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="taskrecurrenceenrollment",
            name="verifiers",
            field=models.ManyToManyField(
                related_name="task_enrollments_as_verifier",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(copy_verifier_to_m2m, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="task",
            name="verifier",
        ),
        migrations.RemoveField(
            model_name="taskrecurrenceenrollment",
            name="verifier",
        ),
    ]
