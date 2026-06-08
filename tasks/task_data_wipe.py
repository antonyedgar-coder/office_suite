"""Bulk delete task runtime data vs task setup (masters/groups)."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction

from core.feature_flags import task_module_enabled


def count_task_module_data() -> dict[str, int]:
    if not task_module_enabled():
        return {
            "tasks": 0,
            "task_assignments": 0,
            "task_enrollments": 0,
            "task_masters": 0,
            "task_groups": 0,
            "task_notifications": 0,
        }
    from tasks.models import (
        Task,
        TaskAssignment,
        TaskGroup,
        TaskMaster,
        TaskNotification,
        TaskRecurrenceEnrollment,
    )

    return {
        "tasks": Task.objects.count(),
        "task_assignments": TaskAssignment.objects.count(),
        "task_enrollments": TaskRecurrenceEnrollment.objects.count(),
        "task_masters": TaskMaster.objects.count(),
        "task_groups": TaskGroup.objects.count(),
        "task_notifications": TaskNotification.objects.count(),
    }


@transaction.atomic
def delete_task_instances_only() -> dict[str, int]:
    """
    Delete all assigned task rows and recurring enrollments.

    Keeps TaskMaster, TaskGroup, and master checklists so you can bulk-upload tasks again.
    """
    if not task_module_enabled():
        return {}
    from tasks.models import (
        Task,
        TaskActivity,
        TaskAssignment,
        TaskChecklistItem,
        TaskEnrollmentAssignee,
        TaskNotification,
        TaskRecurrenceEnrollment,
    )

    out: dict[str, int] = {}
    out["task_notifications"] = TaskNotification.objects.all().delete()[0]
    out["task_activities"] = TaskActivity.objects.all().delete()[0]
    out["task_checklist_items"] = TaskChecklistItem.objects.all().delete()[0]
    out["task_assignments"] = TaskAssignment.objects.all().delete()[0]
    out["tasks"] = Task.objects.all().delete()[0]
    out["task_enrollment_assignees"] = TaskEnrollmentAssignee.objects.all().delete()[0]
    out["task_enrollments"] = TaskRecurrenceEnrollment.objects.all().delete()[0]
    return out


@transaction.atomic
def delete_task_configuration_only() -> dict[str, int]:
    """
    Delete task masters and groups (setup templates).

    All task instances must be removed first (use delete_task_instances_only).
    """
    if not task_module_enabled():
        return {}
    from tasks.models import (
        Task,
        TaskEnrollmentAssignee,
        TaskGroup,
        TaskMaster,
        TaskMasterChecklistItem,
        TaskRecurrenceEnrollment,
    )

    if Task.objects.exists():
        raise ValidationError(
            "Delete all task instances first (Tasks → Manage task data → Delete task instances only), "
            "then remove task masters and groups."
        )

    out: dict[str, int] = {}
    out["task_enrollment_assignees"] = TaskEnrollmentAssignee.objects.all().delete()[0]
    out["task_enrollments"] = TaskRecurrenceEnrollment.objects.all().delete()[0]
    out["task_master_checklist"] = TaskMasterChecklistItem.objects.all().delete()[0]
    out["task_masters"] = TaskMaster.objects.all().delete()[0]
    out["task_groups"] = TaskGroup.objects.all().delete()[0]
    return out


@transaction.atomic
def delete_all_task_module_data() -> dict[str, int]:
    """Delete instances then configuration (full task module wipe)."""
    deleted = delete_task_instances_only()
    deleted.update(delete_task_configuration_only())
    return deleted
