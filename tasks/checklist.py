"""Task master checklist templates and per-task checklist copies."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Task, TaskActivity, TaskChecklistItem, TaskMaster, TaskMasterChecklistItem


def master_checklist_labels(master: TaskMaster) -> list[str]:
    return list(
        master.checklist_items.order_by("sort_order", "pk").values_list("label", flat=True)
    )


def save_master_checklist(master: TaskMaster, labels: list[str]) -> None:
    cleaned = [label.strip() for label in labels if label and label.strip()]
    master.checklist_items.all().delete()
    TaskMasterChecklistItem.objects.bulk_create(
        [
            TaskMasterChecklistItem(task_master=master, label=label, sort_order=idx)
            for idx, label in enumerate(cleaned)
        ]
    )


def copy_checklist_to_task(task: Task, master: TaskMaster) -> None:
    items = master.checklist_items.order_by("sort_order", "pk")
    TaskChecklistItem.objects.bulk_create(
        [
            TaskChecklistItem(
                task=task,
                source_master_item=item,
                label=item.label,
                sort_order=item.sort_order,
            )
            for item in items
        ]
    )


def checklist_has_items(task: Task) -> bool:
    return task.checklist_items.exists()


def checklist_ready_for_submit(task: Task) -> bool:
    """True when every checklist row is done or marked N/A (or there is no checklist)."""
    items = list(task.checklist_items.all())
    if not items:
        return True
    return all(item.is_not_applicable or item.is_done for item in items)


def checklist_pending_labels(task: Task, *, limit: int = 5) -> list[str]:
    return [
        item.label
        for item in task.checklist_items.filter(is_done=False, is_not_applicable=False).order_by(
            "sort_order", "pk"
        )[:limit]
    ]


def validate_checklist_before_submit(task: Task) -> None:
    if checklist_ready_for_submit(task):
        return
    pending = checklist_pending_labels(task)
    extra = task.checklist_items.filter(is_done=False, is_not_applicable=False).count() - len(
        pending
    )
    suffix = f" (+{extra} more)" if extra > 0 else ""
    joined = ", ".join(pending) if pending else "checklist items"
    raise ValidationError(
        f"Complete the checklist before submitting. Mark each item as done (Appl) or "
        f"Not applicable (NA). Pending: {joined}{suffix}."
    )


def set_task_checklist_item_status(
    *,
    task: Task,
    item_id: int,
    user,
    mode: str,
) -> TaskChecklistItem:
    """
    mode: 'appl' — applicable (clears N/A); 'na' — not applicable; 'toggle' — flip done (appl only).
    """
    item = TaskChecklistItem.objects.get(pk=item_id, task=task)
    mode = (mode or "").strip().lower()
    from .services import _log_activity

    if mode == "na":
        item.is_not_applicable = True
        item.is_done = False
        item.completed_at = None
        item.completed_by = None
        item.save(update_fields=["is_not_applicable", "is_done", "completed_at", "completed_by"])
        _log_activity(
            task,
            user,
            TaskActivity.TYPE_CHECKLIST,
            message=f"Marked N/A: {item.label}",
            metadata={"checklist_item_id": item.pk, "mode": "na"},
        )
        return item

    if mode == "appl":
        item.is_not_applicable = False
        item.save(update_fields=["is_not_applicable"])
        _log_activity(
            task,
            user,
            TaskActivity.TYPE_CHECKLIST,
            message=f"Marked applicable: {item.label}",
            metadata={"checklist_item_id": item.pk, "mode": "appl"},
        )
        return item

    if mode == "toggle":
        if item.is_not_applicable:
            raise ValidationError("Mark this item as Applicable (Appl) before ticking it complete.")
        item.is_done = not item.is_done
        if item.is_done:
            item.completed_at = timezone.now()
            item.completed_by = user
        else:
            item.completed_at = None
            item.completed_by = None
        item.save(update_fields=["is_done", "completed_at", "completed_by"])
        _log_activity(
            task,
            user,
            TaskActivity.TYPE_CHECKLIST,
            message=f"{'Completed' if item.is_done else 'Reopened'} checklist: {item.label}",
            metadata={"checklist_item_id": item.pk, "done": item.is_done},
        )
        return item

    raise ValidationError("Invalid checklist action.")


def toggle_task_checklist_item(*, task: Task, item_id: int, user, done: bool) -> TaskChecklistItem:
    """Set done state for an applicable checklist item."""
    item = TaskChecklistItem.objects.get(pk=item_id, task=task)
    if item.is_not_applicable:
        raise ValidationError("Mark this item as Applicable (Appl) before ticking it complete.")
    if item.is_done == done:
        return item
    item.is_done = done
    if done:
        item.completed_at = timezone.now()
        item.completed_by = user
    else:
        item.completed_at = None
        item.completed_by = None
    item.save(update_fields=["is_done", "completed_at", "completed_by"])
    from .services import _log_activity

    _log_activity(
        task,
        user,
        TaskActivity.TYPE_CHECKLIST,
        message=f"{'Completed' if done else 'Reopened'} checklist: {item.label}",
        metadata={"checklist_item_id": item.pk, "done": done},
    )
    return item
