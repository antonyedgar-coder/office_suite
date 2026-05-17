"""Task master checklist templates and per-task checklist copies."""

from __future__ import annotations

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


def toggle_task_checklist_item(*, task: Task, item_id: int, user, done: bool) -> TaskChecklistItem:
    item = TaskChecklistItem.objects.get(pk=item_id, task=task)
    item.is_done = done
    if done:
        item.completed_at = timezone.now()
        item.completed_by = user
    else:
        item.completed_at = None
        item.completed_by = None
    item.save(update_fields=["is_done", "completed_at", "completed_by"])
    TaskActivity.objects.create(
        task=task,
        user=user,
        activity_type=TaskActivity.TYPE_CHECKLIST,
        message=f"{'Completed' if done else 'Reopened'} checklist: {item.label}",
        metadata={"checklist_item_id": item.pk, "done": done},
    )
    return item
