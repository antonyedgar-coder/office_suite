import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("masters", "0017_client_id_branch_prefix"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.CreateModel(
            name="TaskMaster",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("description", models.TextField(blank=True)),
                (
                    "default_priority",
                    models.CharField(
                        choices=[("low", "Low"), ("normal", "Normal"), ("urgent", "Urgent")],
                        default="normal",
                        max_length=16,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("is_recurring", models.BooleanField(default=False)),
                (
                    "frequency",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("monthly", "Monthly"),
                            ("quarterly", "Quarterly"),
                            ("half_yearly", "Half-yearly"),
                            ("annually", "Annually"),
                            ("every_3_years", "Every 3 years"),
                            ("every_5_years", "Every 5 years"),
                        ],
                        max_length=32,
                    ),
                ),
                ("recurrence_config", models.JSONField(blank=True, default=dict)),
                (
                    "task_group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="task_masters",
                        to="tasks.taskgroup",
                    ),
                ),
            ],
            options={
                "ordering": ["task_group__sort_order", "task_group__name", "name"],
                "unique_together": {("task_group", "name")},
            },
        ),
        migrations.CreateModel(
            name="TaskRecurrenceEnrollment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True)),
                ("started_at", models.DateField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "client",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="task_enrollments",
                        to="masters.client",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="task_enrollments_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "task_master",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="enrollments",
                        to="tasks.taskmaster",
                    ),
                ),
                (
                    "verifier",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="task_enrollments_as_verifier",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"unique_together": {("client", "task_master")}},
        ),
        migrations.CreateModel(
            name="Task",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=255)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("assigned", "Assigned"),
                            ("in_progress", "In progress"),
                            ("submitted", "Submitted"),
                            ("approved", "Approved"),
                            ("rework", "Rework"),
                            ("cancelled", "Cancelled"),
                        ],
                        db_index=True,
                        default="assigned",
                        max_length=20,
                    ),
                ),
                (
                    "priority",
                    models.CharField(
                        choices=[("low", "Low"), ("normal", "Normal"), ("urgent", "Urgent")],
                        default="normal",
                        max_length=16,
                    ),
                ),
                ("due_date", models.DateField()),
                ("period_key", models.CharField(db_index=True, max_length=64)),
                ("auto_created", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "client",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tasks", to="masters.client"),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tasks_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "enrollment",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="tasks",
                        to="tasks.taskrecurrenceenrollment",
                    ),
                ),
                (
                    "task_master",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tasks",
                        to="tasks.taskmaster",
                    ),
                ),
                (
                    "verifier",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="tasks_to_verify",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-due_date", "-created_at"],
                "permissions": [
                    ("assign_task", "Can assign task"),
                    ("verify_task", "Can verify task"),
                ],
                "unique_together": {("client", "task_master", "period_key")},
            },
        ),
        migrations.CreateModel(
            name="TaskNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("assigned", "Assigned"),
                            ("verify", "Verification"),
                            ("rework", "Rework"),
                            ("approved", "Approved"),
                            ("recurring_fail", "Recurring failure"),
                            ("general", "General"),
                        ],
                        default="general",
                        max_length=32,
                    ),
                ),
                ("message", models.TextField()),
                ("link", models.CharField(blank=True, max_length=512)),
                ("is_read", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "task",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to="tasks.task",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="task_notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="TaskEnrollmentAssignee",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "enrollment",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="tasks.taskrecurrenceenrollment"),
                ),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={"unique_together": {("enrollment", "user")}},
        ),
        migrations.AddField(
            model_name="taskrecurrenceenrollment",
            name="assignees",
            field=models.ManyToManyField(
                related_name="task_enrollments_as_assignee",
                through="tasks.TaskEnrollmentAssignee",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name="TaskAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("task", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assignments", to="tasks.task")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="task_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"unique_together": {("task", "user")}},
        ),
        migrations.CreateModel(
            name="TaskActivity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "activity_type",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("assigned", "Assignee change"),
                            ("status_change", "Status change"),
                            ("remark", "Remark"),
                            ("enrollment", "Enrollment"),
                        ],
                        max_length=32,
                    ),
                ),
                ("message", models.TextField(blank=True)),
                ("old_status", models.CharField(blank=True, max_length=20)),
                ("new_status", models.CharField(blank=True, max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "task",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="activities", to="tasks.task"),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["created_at"]},
        ),
    ]
