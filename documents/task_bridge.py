"""Map task periods to document periods and document lock rules."""

from __future__ import annotations

import calendar
import re
from datetime import date

from django.core.exceptions import ValidationError

from dirkyc.fy import fy_label_for_date

from documents.folder_constants import EARLY_TASK_UPLOAD_FOLDER_SLUGS

from tasks.models import Task
from tasks.one_time_period import is_one_time_period_key, one_time_period_from_due_date
from tasks.period_keys import fy_choice_label

# Task statuses where linked documents may be changed (after assignment approval).
_TASK_DOC_EDITABLE_STATUSES = frozenset(
    {
        Task.STATUS_ASSIGNED,
        Task.STATUS_SUBMITTED,
        Task.STATUS_VERIFIED,
        Task.STATUS_REWORK,
        Task.STATUS_DOCUMENT_REWORK,
    }
)

# Before assignees approve, only Supporting / KYC folder uploads are allowed.
_TASK_DOC_PENDING_ASSIGNMENT = frozenset({Task.STATUS_PENDING_ASSIGNMENT})


def document_period_from_task(task: Task) -> tuple[str, str]:
    """
    Convert task.period_key / period_type to document (period_key, period_label).
    """
    pk = (task.period_key or "").strip()
    pt = (task.period_type or "").strip()

    if is_one_time_period_key(pk):
        return one_time_period_from_due_date(task.due_date or date.today(), period_key=pk)

    if pt == "one_time" and task.due_date:
        return one_time_period_from_due_date(task.due_date, period_key=pk)

    if not pk or pk in ("one-time", "once") or pt in ("one_time", ""):
        return "once", "—"

    m = re.match(r"^(\d{4})-(\d{2})$", pk)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        fy = fy_label_for_date(date(y, mo, 1))
        return f"FY{fy}-{pk}", calendar.month_name[mo]

    m = re.match(r"^(\d{4})-Q([1-4])$", pk)
    if m:
        fy = fy_choice_label(int(m.group(1)))
        q = f"Q{m.group(2)}"
        return f"FY{fy}-{q}", q

    m = re.match(r"^(\d{4})-H([12])$", pk)
    if m:
        fy = fy_choice_label(int(m.group(1)))
        h = f"H{m.group(2)}"
        return f"FY{fy}-{h}", h

    if pk.startswith("FY"):
        fy = pk[2:]
        return f"FY{fy}", "Yearly"

    m = re.match(r"^(\d{4})-(\d{4})$", pk)
    if m:
        fy_start = int(m.group(1))
        fy = fy_choice_label(fy_start)
        return f"FY{fy}", f"FY {fy}"

    raise ValidationError(
        f"Cannot map task period “{pk}” to a document period. Configure the task period or upload from Documents."
    )


def _folder_slug_for_document(doc) -> str:
    folder = getattr(doc, "folder", None)
    if folder is None and getattr(doc, "folder_id", None):
        from documents.models import ClientDocumentFolder

        folder = ClientDocumentFolder.objects.select_related("template").filter(pk=doc.folder_id).first()
    template = getattr(folder, "template", None) if folder else None
    return (getattr(template, "slug", None) or "").strip()


def task_allows_document_upload(task: Task | None, *, folder_slug: str = "") -> bool:
    """Whether a new upload/replace is allowed for this task and folder."""
    if task is None:
        return True
    if task.status in (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED):
        return False
    slug = (folder_slug or "").strip()
    if task.status in _TASK_DOC_PENDING_ASSIGNMENT:
        return slug in EARLY_TASK_UPLOAD_FOLDER_SLUGS
    return task.status in _TASK_DOC_EDITABLE_STATUSES


def task_allows_document_changes(task: Task | None) -> bool:
    if task is None:
        return True
    return task.status in (_TASK_DOC_EDITABLE_STATUSES | _TASK_DOC_PENDING_ASSIGNMENT)


def user_can_change_task_linked_document(user, doc, *, task: Task | None = None) -> bool:
    """Whether upload/replace/delete/rename is allowed for this document row."""
    if not getattr(doc, "task_id", None):
        return True
    if task is None:
        task = getattr(doc, "task", None)
    if task is None:
        task = Task.objects.filter(pk=doc.task_id).first()
    if task is None:
        return True
    if task.status in (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED):
        if user.is_superuser:
            return True
        return user.has_perm("documents.override_task_document_lock")
    folder_slug = _folder_slug_for_document(doc)
    if task_allows_document_upload(task, folder_slug=folder_slug):
        return True
    if user.is_superuser:
        return True
    return user.has_perm("documents.override_task_document_lock")


def task_documents_locked(task: Task | None) -> bool:
    """Whether the task detail panel should show the locked banner."""
    if task is None:
        return False
    return task.status in (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED)


def document_is_locked(doc, *, task: Task | None = None) -> bool:
    if not getattr(doc, "task_id", None):
        return False
    task = task or getattr(doc, "task", None)
    if task is None:
        return False
    return task.status in (Task.STATUS_COMPLETE, Task.STATUS_CANCELLED)
