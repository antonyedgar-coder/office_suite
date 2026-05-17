"""Task status transition rules."""

from __future__ import annotations

from django.core.exceptions import ValidationError

from .models import Task

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Task.STATUS_ASSIGNED: {Task.STATUS_SUBMITTED, Task.STATUS_CANCELLED},
    Task.STATUS_SUBMITTED: {Task.STATUS_APPROVED, Task.STATUS_REWORK, Task.STATUS_CANCELLED},
    Task.STATUS_REWORK: {Task.STATUS_SUBMITTED, Task.STATUS_CANCELLED},
    Task.STATUS_APPROVED: set(),
    Task.STATUS_CANCELLED: set(),
    # Legacy statuses (migrated to pending in DB)
    Task.STATUS_DRAFT: {Task.STATUS_SUBMITTED, Task.STATUS_CANCELLED},
    Task.STATUS_IN_PROGRESS: {Task.STATUS_SUBMITTED, Task.STATUS_CANCELLED},
}


def can_transition(task: Task, new_status: str) -> bool:
    return new_status in ALLOWED_TRANSITIONS.get(task.status, set())


def validate_transition(task: Task, new_status: str) -> None:
    if new_status == task.status:
        return
    if not can_transition(task, new_status):
        raise ValidationError(
            f"Cannot change task status from {task.get_status_display()} to "
            f"{dict(Task.STATUS_CHOICES).get(new_status, new_status)}."
        )
