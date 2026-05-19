# Generated manually for document checker workflow.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_approved_to_verified(apps, schema_editor):
    Task = apps.get_model("tasks", "Task")
    Task.objects.filter(status="approved").update(status="verified")


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0008_remove_taskmaster_default_billable_verifier"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="document_checker",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tasks_to_document_check",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="taskrecurrenceenrollment",
            name="document_checker",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="task_enrollments_as_document_checker",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="completed_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="completed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tasks_completed",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(migrate_approved_to_verified, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="task",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending_assignment", "Awaiting assignment approval"),
                    ("assigned", "Pending"),
                    ("submitted", "Submitted"),
                    ("verified", "Verified"),
                    ("complete", "Complete"),
                    ("rework", "Rework"),
                    ("cancelled", "Cancelled"),
                ],
                db_index=True,
                default="assigned",
                max_length=20,
            ),
        ),
        migrations.RunSQL(
            sql=(
                "UPDATE tasks_task SET document_checker_id = verifier_id "
                "WHERE document_checker_id IS NULL;"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=(
                "UPDATE tasks_taskrecurrenceenrollment SET document_checker_id = verifier_id "
                "WHERE document_checker_id IS NULL;"
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name="task",
            name="document_checker",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tasks_to_document_check",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="taskrecurrenceenrollment",
            name="document_checker",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="task_enrollments_as_document_checker",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(fields=["document_checker", "status"], name="tasks_task_docchk_status_idx"),
        ),
        migrations.AlterModelOptions(
            name="task",
            options={
                "ordering": ["-due_date", "-created_at"],
                "permissions": [
                    ("assign_task", "Can assign task"),
                    ("verify_task", "Can verify task"),
                    ("check_documents", "Can check task documents"),
                ],
            },
        ),
        migrations.AlterField(
            model_name="tasknotification",
            name="kind",
            field=models.CharField(
                choices=[
                    ("assigned", "Assigned"),
                    ("assignment_approval", "Assignment approval"),
                    ("verify", "Verification"),
                    ("rework", "Rework"),
                    ("approved", "Verified"),
                    ("document_check", "Document check"),
                    ("recurring_fail", "Recurring failure"),
                    ("general", "General"),
                ],
                default="general",
                max_length=32,
            ),
        ),
    ]
