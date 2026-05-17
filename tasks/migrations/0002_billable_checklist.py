import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="taskmaster",
            name="default_is_billable",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="taskmaster",
            name="default_fees_amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Default fee for new task instances (each task stores its own copy).",
                max_digits=12,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="is_billable",
            field=models.BooleanField(
                default=False,
                help_text="Fee snapshot at task creation; not updated when task master default changes.",
            ),
        ),
        migrations.AddField(
            model_name="task",
            name="fees_amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Billable fee frozen on this task instance.",
                max_digits=12,
                null=True,
            ),
        ),
        migrations.CreateModel(
            name="TaskMasterChecklistItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(max_length=255)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                (
                    "task_master",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="checklist_items",
                        to="tasks.taskmaster",
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order", "pk"],
            },
        ),
        migrations.CreateModel(
            name="TaskChecklistItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(max_length=255)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("is_done", models.BooleanField(default=False)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "completed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="task_checklist_completions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "source_master_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="task_copies",
                        to="tasks.taskmasterchecklistitem",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="checklist_items",
                        to="tasks.task",
                    ),
                ),
            ],
            options={
                "ordering": ["sort_order", "pk"],
            },
        ),
    ]
