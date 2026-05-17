import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def backfill_workflow_timestamps(apps, schema_editor):
    Task = apps.get_model("tasks", "Task")
    TaskActivity = apps.get_model("tasks", "TaskActivity")

    for task in Task.objects.iterator():
        updates = {}
        submitted = (
            TaskActivity.objects.filter(task_id=task.pk, new_status="submitted")
            .order_by("-created_at")
            .first()
        )
        if submitted and not task.submitted_at:
            updates["submitted_at"] = submitted.created_at
            updates["submitted_by_id"] = submitted.user_id
        approved = (
            TaskActivity.objects.filter(task_id=task.pk, new_status="approved")
            .order_by("-created_at")
            .first()
        )
        if approved and not task.approved_at:
            updates["approved_at"] = approved.created_at
            updates["approved_by_id"] = approved.user_id
        if updates:
            Task.objects.filter(pk=task.pk).update(**updates)


def backfill_notification_clients(apps, schema_editor):
    TaskNotification = apps.get_model("tasks", "TaskNotification")
    Task = apps.get_model("tasks", "Task")
    for n in TaskNotification.objects.filter(task_id__isnull=False, client_id__isnull=True).iterator():
        client_id = Task.objects.filter(pk=n.task_id).values_list("client_id", flat=True).first()
        if client_id:
            TaskNotification.objects.filter(pk=n.pk).update(client_id=client_id)


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0017_client_id_branch_prefix"),
        ("tasks", "0002_billable_checklist"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="taskmaster",
            name="default_currency",
            field=models.CharField(default="INR", max_length=8),
        ),
        migrations.AddField(
            model_name="taskmaster",
            name="default_verifier",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="task_masters_default_verifier",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="taskmaster",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecurrenceenrollment",
            name="is_paused",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="taskrecurrenceenrollment",
            name="paused_until",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taskrecurrenceenrollment",
            name="notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="task",
            name="period_type",
            field=models.CharField(blank=True, db_index=True, max_length=32),
        ),
        migrations.AddField(
            model_name="task",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="submitted_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="submitted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tasks_submitted",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="approved_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tasks_approved",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="task",
            name="cancelled_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="tasks_cancelled",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="currency",
            field=models.CharField(default="INR", max_length=8),
        ),
        migrations.AddField(
            model_name="taskassignment",
            name="assigned_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="taskassignment",
            name="assigned_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="task_assignments_made",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="taskactivity",
            name="metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="tasknotification",
            name="client",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="task_notifications",
                to="masters.client",
            ),
        ),
        migrations.AddField(
            model_name="tasknotification",
            name="read_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterUniqueTogether(
            name="taskmaster",
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name="taskrecurrenceenrollment",
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name="taskenrollmentassignee",
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name="task",
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name="taskassignment",
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name="taskmaster",
            constraint=models.UniqueConstraint(
                fields=("task_group", "name"),
                name="tasks_taskmaster_group_name_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="taskmaster",
            index=models.Index(fields=["is_active", "task_group"], name="tasks_taskma_is_acti_idx"),
        ),
        migrations.AddConstraint(
            model_name="taskrecurrenceenrollment",
            constraint=models.UniqueConstraint(
                fields=("client", "task_master"),
                name="tasks_enrollment_client_master_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="taskenrollmentassignee",
            constraint=models.UniqueConstraint(
                fields=("enrollment", "user"),
                name="tasks_enrollment_assignee_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="task",
            constraint=models.UniqueConstraint(
                fields=("client", "task_master", "period_key"),
                name="tasks_task_client_master_period_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="task",
            constraint=models.CheckConstraint(
                check=models.Q(is_billable=False) | models.Q(fees_amount__isnull=False),
                name="tasks_task_billable_requires_fees",
            ),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(fields=["client", "status"], name="tasks_task_client_status_idx"),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(fields=["verifier", "status"], name="tasks_task_verifier_status_idx"),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(fields=["due_date", "status"], name="tasks_task_due_status_idx"),
        ),
        migrations.AddConstraint(
            model_name="taskassignment",
            constraint=models.UniqueConstraint(
                fields=("task", "user"),
                name="tasks_assignment_task_user_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="taskassignment",
            index=models.Index(fields=["user", "assigned_at"], name="tasks_assign_user_at_idx"),
        ),
        migrations.AddIndex(
            model_name="taskactivity",
            index=models.Index(fields=["task", "created_at"], name="tasks_activity_task_at_idx"),
        ),
        migrations.AddIndex(
            model_name="tasknotification",
            index=models.Index(fields=["user", "is_read", "created_at"], name="tasks_notif_user_read_idx"),
        ),
        migrations.AddIndex(
            model_name="tasknotification",
            index=models.Index(fields=["client", "created_at"], name="tasks_notif_client_at_idx"),
        ),
        migrations.RunPython(backfill_workflow_timestamps, migrations.RunPython.noop),
        migrations.RunPython(backfill_notification_clients, migrations.RunPython.noop),
    ]
