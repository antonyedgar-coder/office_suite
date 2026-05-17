from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .recurrence_config import validate_recurrence_config


class TaskGroup(models.Model):
    name = models.CharField(max_length=120, unique=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class TaskMaster(models.Model):
    CURRENCY_INR = "INR"

    PRIORITY_LOW = "low"
    PRIORITY_NORMAL = "normal"
    PRIORITY_URGENT = "urgent"
    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_NORMAL, "Normal"),
        (PRIORITY_URGENT, "Urgent"),
    ]

    FREQ_MONTHLY = "monthly"
    FREQ_QUARTERLY = "quarterly"
    FREQ_HALF_YEARLY = "half_yearly"
    FREQ_ANNUALLY = "annually"
    FREQ_EVERY_3_YEARS = "every_3_years"
    FREQ_EVERY_5_YEARS = "every_5_years"
    FREQUENCY_CHOICES = [
        (FREQ_MONTHLY, "Monthly"),
        (FREQ_QUARTERLY, "Quarterly"),
        (FREQ_HALF_YEARLY, "Half-yearly"),
        (FREQ_ANNUALLY, "Annually"),
        (FREQ_EVERY_3_YEARS, "Every 3 years"),
        (FREQ_EVERY_5_YEARS, "Every 5 years"),
    ]

    task_group = models.ForeignKey(TaskGroup, on_delete=models.PROTECT, related_name="task_masters")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    default_priority = models.CharField(
        max_length=16,
        choices=PRIORITY_CHOICES,
        default=PRIORITY_NORMAL,
    )
    is_active = models.BooleanField(default=True)
    is_recurring = models.BooleanField(default=False)
    frequency = models.CharField(max_length=32, choices=FREQUENCY_CHOICES, blank=True)
    recurrence_config = models.JSONField(default=dict, blank=True)
    default_is_billable = models.BooleanField(default=False)
    default_fees_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Default fee for new task instances (each task stores its own copy).",
    )
    default_currency = models.CharField(max_length=8, default=CURRENCY_INR)
    default_verifier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_masters_default_verifier",
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["task_group__sort_order", "task_group__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["task_group", "name"], name="tasks_taskmaster_group_name_uniq"),
        ]
        indexes = [
            models.Index(fields=["is_active", "task_group"]),
        ]

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def __str__(self) -> str:
        return f"{self.task_group.name} — {self.name}"

    def save(self, *args, **kwargs):
        if self.is_recurring:
            self.full_clean()
        else:
            self.frequency = ""
            self.recurrence_config = {}
        super().save(*args, **kwargs)

    def clean(self):
        if self.is_recurring:
            if not self.frequency:
                raise ValidationError({"frequency": "Frequency is required for recurring tasks."})
            validate_recurrence_config(self.frequency, self.recurrence_config or {})
        else:
            self.frequency = ""
            self.recurrence_config = {}


class TaskMasterChecklistItem(models.Model):
    task_master = models.ForeignKey(TaskMaster, on_delete=models.CASCADE, related_name="checklist_items")
    label = models.CharField(max_length=255)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "pk"]

    def __str__(self) -> str:
        return self.label


class TaskRecurrenceEnrollment(models.Model):
    client = models.ForeignKey("masters.Client", on_delete=models.CASCADE, related_name="task_enrollments")
    task_master = models.ForeignKey(TaskMaster, on_delete=models.PROTECT, related_name="enrollments")
    verifier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="task_enrollments_as_verifier",
    )
    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="TaskEnrollmentAssignee",
        related_name="task_enrollments_as_assignee",
    )
    is_active = models.BooleanField(default=True)
    is_paused = models.BooleanField(default=False)
    paused_until = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    started_at = models.DateField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="task_enrollments_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["client", "task_master"],
                name="tasks_enrollment_client_master_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.client_id} · {self.task_master.name}"


class TaskEnrollmentAssignee(models.Model):
    enrollment = models.ForeignKey(TaskRecurrenceEnrollment, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["enrollment", "user"],
                name="tasks_enrollment_assignee_uniq",
            ),
        ]


class Task(models.Model):
    # Legacy values kept for old rows / migrations; not offered in STATUS_CHOICES.
    STATUS_DRAFT = "draft"
    STATUS_IN_PROGRESS = "in_progress"

    STATUS_ASSIGNED = "assigned"
    STATUS_SUBMITTED = "submitted"
    STATUS_APPROVED = "approved"
    STATUS_REWORK = "rework"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_ASSIGNED, "Pending"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REWORK, "Rework"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    client = models.ForeignKey("masters.Client", on_delete=models.PROTECT, related_name="tasks")
    task_master = models.ForeignKey(TaskMaster, on_delete=models.PROTECT, related_name="tasks")
    enrollment = models.ForeignKey(
        TaskRecurrenceEnrollment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ASSIGNED, db_index=True)
    priority = models.CharField(max_length=16, choices=TaskMaster.PRIORITY_CHOICES, default=TaskMaster.PRIORITY_NORMAL)
    due_date = models.DateField()
    verifier = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="tasks_to_verify",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="tasks_created",
    )
    period_key = models.CharField(max_length=64, db_index=True)
    period_type = models.CharField(max_length=32, blank=True, db_index=True)
    auto_created = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks_submitted",
    )
    approved_at = models.DateTimeField(null=True, blank=True, db_index=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks_approved",
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks_cancelled",
    )
    is_billable = models.BooleanField(
        default=False,
        help_text="Fee snapshot at task creation; not updated when task master default changes.",
    )
    fees_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Billable fee frozen on this task instance.",
    )
    currency = models.CharField(max_length=8, default=TaskMaster.CURRENCY_INR)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-due_date", "-created_at"]
        permissions = [
            ("assign_task", "Can assign task"),
            ("verify_task", "Can verify task"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["client", "task_master", "period_key"],
                name="tasks_task_client_master_period_uniq",
            ),
            models.CheckConstraint(
                check=Q(is_billable=False) | Q(fees_amount__isnull=False),
                name="tasks_task_billable_requires_fees",
            ),
        ]
        indexes = [
            models.Index(fields=["client", "status"]),
            models.Index(fields=["verifier", "status"]),
            models.Index(fields=["due_date", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.display_title} — {self.client_id} ({self.period_key})"

    @property
    def display_title(self) -> str:
        return (self.title or "").strip() or self.task_master.name

    @classmethod
    def status_label(cls, code: str) -> str:
        if code in (cls.STATUS_ASSIGNED, cls.STATUS_IN_PROGRESS, cls.STATUS_DRAFT):
            return "Pending"
        return dict(cls.STATUS_CHOICES).get(code, code or "")

    def clean(self):
        if self.is_billable and self.fees_amount is None:
            raise ValidationError({"fees_amount": "Fees amount is required for billable tasks."})


class TaskAssignment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="assignments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_assignments")
    assigned_at = models.DateTimeField(default=timezone.now)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_assignments_made",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["task", "user"], name="tasks_assignment_task_user_uniq"),
        ]
        indexes = [
            models.Index(fields=["user", "assigned_at"]),
        ]


class TaskChecklistItem(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="checklist_items")
    source_master_item = models.ForeignKey(
        TaskMasterChecklistItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_copies",
    )
    label = models.CharField(max_length=255)
    sort_order = models.PositiveIntegerField(default=0)
    is_done = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_checklist_completions",
    )

    class Meta:
        ordering = ["sort_order", "pk"]

    def __str__(self) -> str:
        return self.label


class TaskActivity(models.Model):
    TYPE_CREATED = "created"
    TYPE_ASSIGNED = "assigned"
    TYPE_STATUS = "status_change"
    TYPE_REMARK = "remark"
    TYPE_ENROLLMENT = "enrollment"
    TYPE_CHECKLIST = "checklist"
    ACTIVITY_TYPES = [
        (TYPE_CREATED, "Created"),
        (TYPE_ASSIGNED, "Users change"),
        (TYPE_STATUS, "Status change"),
        (TYPE_REMARK, "Remark"),
        (TYPE_ENROLLMENT, "Enrollment"),
        (TYPE_CHECKLIST, "Checklist"),
    ]

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="activities")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    activity_type = models.CharField(max_length=32, choices=ACTIVITY_TYPES)
    message = models.TextField(blank=True)
    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["task", "created_at"]),
        ]


class TaskNotification(models.Model):
    KIND_ASSIGNED = "assigned"
    KIND_VERIFY = "verify"
    KIND_REWORK = "rework"
    KIND_APPROVED = "approved"
    KIND_RECURRING_FAIL = "recurring_fail"
    KIND_GENERAL = "general"
    KIND_CHOICES = [
        (KIND_ASSIGNED, "Assigned"),
        (KIND_VERIFY, "Verification"),
        (KIND_REWORK, "Rework"),
        (KIND_APPROVED, "Approved"),
        (KIND_RECURRING_FAIL, "Recurring failure"),
        (KIND_GENERAL, "General"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_notifications")
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, default=KIND_GENERAL)
    message = models.TextField()
    link = models.CharField(max_length=512, blank=True)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
    client = models.ForeignKey(
        "masters.Client",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="task_notifications",
    )
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read", "created_at"]),
            models.Index(fields=["client", "created_at"]),
        ]
