import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tasks", "0020_task_description"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskmaster",
            name="requires_document_checker",
            field=models.BooleanField(
                default=True,
                help_text="When enabled, a document checker must mark the task complete after submission or verification.",
            ),
        ),
        migrations.AddField(
            model_name="taskmaster",
            name="requires_verifier",
            field=models.BooleanField(
                default=True,
                help_text="When enabled, a verifier must approve before the task can complete (or before document check in full workflow).",
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="requires_document_checker",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="task",
            name="requires_verifier",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="taskrecurrenceenrollment",
            name="requires_document_checker",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="taskrecurrenceenrollment",
            name="requires_verifier",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="task",
            name="document_checker",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="tasks_to_document_check",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="taskrecurrenceenrollment",
            name="document_checker",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="task_enrollments_as_document_checker",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
