from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db.models import Q
from tasks.date_presets import (
    PRESET_ALL_TIME,
    PRESET_CUSTOM,
    PRESET_LAST_FY,
    PRESET_LAST_MONTH,
    PRESET_THIS_FY,
    PRESET_THIS_MONTH,
    resolve_date_preset,
)

from core.user_display import user_display_name

from .models import Client, ClientActivityLog

CLIENT_ACTIVITY_DATE_PRESET_CHOICES = [
    (PRESET_ALL_TIME, "All time"),
    (PRESET_THIS_MONTH, "This month"),
    (PRESET_LAST_MONTH, "Last month"),
    (PRESET_THIS_FY, "This FY"),
    (PRESET_LAST_FY, "Last FY"),
    (PRESET_CUSTOM, "Custom"),
]
CLIENT_ACTIVITY_DATE_PRESET_VALUES = {c[0] for c in CLIENT_ACTIVITY_DATE_PRESET_CHOICES}
CLIENT_ACTIVITY_DEFAULT_DATE_PRESET = PRESET_ALL_TIME

User = get_user_model()


def log_client_activity(
    *,
    client: Client | None,
    user: User | None,
    category: str,
    activity: str,
    task=None,
    remarks: str = "",
    metadata: dict | None = None,
) -> ClientActivityLog | None:
    if not client:
        return None
    text = (activity or "").strip()
    if not text:
        return None
    meta = dict(metadata or {})
    remark_text = (remarks or "").strip()
    if remark_text:
        meta["remark"] = remark_text
    return ClientActivityLog.objects.create(
        client=client,
        user=user,
        category=category,
        activity=text,
        task=task,
        metadata=meta,
    )


def get_client_activity_timeline(client: Client, *, limit: int = 100):
    return (
        ClientActivityLog.objects.filter(client=client)
        .select_related("user", "user__employee_profile", "task", "task__task_master")
        .order_by("-created_at")[:limit]
    )


@dataclass
class ClientActivityLogFilters:
    date_preset: str = CLIENT_ACTIVITY_DEFAULT_DATE_PRESET
    date_from: str = ""
    date_to: str = ""
    client_q: str = ""
    category: str = ""
    task_master_id: str = ""
    activity_q: str = ""
    remarks_q: str = ""
    user_q: str = ""


def parse_client_activity_log_filters(params) -> ClientActivityLogFilters:
    preset = (params.get("date_preset") or "").strip() or CLIENT_ACTIVITY_DEFAULT_DATE_PRESET
    if preset not in CLIENT_ACTIVITY_DATE_PRESET_VALUES:
        preset = CLIENT_ACTIVITY_DEFAULT_DATE_PRESET
    return ClientActivityLogFilters(
        date_preset=preset,
        date_from=(params.get("date_from") or "").strip(),
        date_to=(params.get("date_to") or "").strip(),
        client_q=(params.get("client_q") or "").strip(),
        category=(params.get("category") or "").strip(),
        task_master_id=(params.get("task_master_id") or "").strip(),
        activity_q=(params.get("activity_q") or "").strip(),
        remarks_q=(params.get("remarks_q") or "").strip(),
        user_q=(params.get("user_q") or "").strip(),
    )


def task_master_choices_for_activity_log() -> list[dict]:
    """Task master options for client activity log filters (empty if tasks app off)."""
    from django.apps import apps

    if not apps.is_installed("tasks"):
        return []
    from tasks.models import TaskMaster

    return list(
        TaskMaster.objects.select_related("task_group")
        .order_by("task_group__sort_order", "task_group__name", "name")
        .values("pk", "name", "task_group__name")
    )


def client_activity_log_queryset_for_user(user):
    """Activity rows limited to clients the user may view (branch + approval rules)."""
    from .views import client_master_queryset_for_user

    allowed = client_master_queryset_for_user(user).values_list("client_id", flat=True)
    return (
        ClientActivityLog.objects.filter(client_id__in=allowed)
        .select_related("client", "user", "user__employee_profile", "task", "task__task_master")
        .order_by("-created_at", "-pk")
    )


def apply_client_activity_log_filters(qs, filters: ClientActivityLogFilters):
    d_from, d_to = resolve_date_preset(
        filters.date_preset,
        filters.date_from,
        filters.date_to,
    )
    if d_from:
        qs = qs.filter(created_at__date__gte=d_from)
    if d_to:
        qs = qs.filter(created_at__date__lte=d_to)

    if filters.client_q:
        q = filters.client_q.strip()
        if "—" in q:
            name_part, pan_part = [p.strip() for p in q.split("—", 1)]
            qs = qs.filter(
                Q(client__client_name__icontains=name_part)
                | Q(client__pan__icontains=pan_part)
            )
        else:
            qs = qs.filter(Q(client__client_name__icontains=q) | Q(client__pan__icontains=q))

    valid_categories = {c[0] for c in ClientActivityLog.CATEGORY_CHOICES}
    if filters.category and filters.category in valid_categories:
        qs = qs.filter(category=filters.category)

    if filters.task_master_id:
        from django.apps import apps

        if apps.is_installed("tasks"):
            try:
                tm_id = int(filters.task_master_id)
            except (TypeError, ValueError):
                tm_id = None
            if tm_id:
                qs = qs.filter(task__task_master_id=tm_id)

    if filters.activity_q:
        qs = qs.filter(activity__icontains=filters.activity_q)

    if filters.remarks_q:
        qs = qs.filter(metadata__remark__icontains=filters.remarks_q)

    if filters.user_q:
        qs = qs.filter(user__employee_profile__full_name__icontains=filters.user_q)

    return qs


def remark_text_for_log(log: ClientActivityLog) -> str:
    meta = log.metadata or {}
    stored = (meta.get("remark") or "").strip()
    if stored:
        return stored
    act = (log.activity or "").strip()
    needle = " remark: "
    if needle in act.lower():
        idx = act.lower().index(needle)
        return act[idx + len(needle) :].strip()
    return ""


def task_type_label_for_log(log: ClientActivityLog) -> str:
    """Task master name for task-category activity rows."""
    if log.category != ClientActivityLog.CATEGORY_TASK:
        return ""
    task = log.task if log.task_id else None
    if not task:
        return ""
    tm = getattr(task, "task_master", None)
    if tm and (tm.name or "").strip():
        return tm.name.strip()
    return ""


def activity_description_for_log(log: ClientActivityLog) -> str:
    """Activity narrative without duplicating remark text in the description column."""
    remark = remark_text_for_log(log)
    act = (log.activity or "").strip()
    if remark:
        needle = f" remark: {remark}"
        if act.endswith(needle):
            return act[: -len(needle)].strip()
        if act.lower().endswith(needle.lower()):
            return act[: -len(needle)].strip()
    return act


def build_client_activity_list_rows(logs, *, can_link_tasks: bool) -> list[dict]:
    rows: list[dict] = []
    for log in logs:
        base_rows = build_client_activity_rows([log], can_link_tasks=can_link_tasks)
        row = base_rows[0] if base_rows else {}
        row["client_id"] = log.client_id
        row["client_name"] = log.client.client_name if log.client_id else ""
        row["client_pan"] = ((log.client.pan or "").strip().upper() if log.client_id else "")
        row["description"] = activity_description_for_log(log)
        row["remarks"] = remark_text_for_log(log)
        row["task_type_label"] = task_type_label_for_log(log)
        task = log.task if log.task_id else None
        if task and can_link_tasks:
            title = task.display_title
            act = row["description"] or (log.activity or "")
            if title and title in act:
                idx = act.index(title)
                row["activity_before"] = act[:idx]
                row["activity_after"] = act[idx + len(title) :]
                row["task_link"] = True
        rows.append(row)
    return rows


def build_client_activity_rows(logs, *, can_link_tasks: bool) -> list[dict]:
    rows: list[dict] = []
    for log in logs:
        task = log.task if log.task_id else None
        row = {
            "created_at": log.created_at,
            "category_label": log.get_category_display(),
            "task_type_label": task_type_label_for_log(log),
            "activity": log.activity,
            "activity_before": "",
            "activity_after": "",
            "user_label": user_display_name(log.user),
            "task": task,
            "task_link": False,
        }
        if task and can_link_tasks:
            title = task.display_title
            act = log.activity or ""
            if title and title in act:
                idx = act.index(title)
                row["activity_before"] = act[:idx]
                row["activity_after"] = act[idx + len(title) :]
                row["task_link"] = True
        rows.append(row)
    return rows


def build_task_client_activity_text(
    *,
    task,
    activity_type: str,
    message: str = "",
    old_status: str = "",
    new_status: str = "",
) -> str:
    from tasks.models import Task, TaskActivity

    title = task.display_title
    msg = (message or "").strip()

    if activity_type == TaskActivity.TYPE_CREATED:
        if msg.lower().startswith("task created"):
            return msg.replace("Task created", f"Task {title} created", 1)
        if msg:
            return f"Task {title} created. {msg}"
        return f"Task {title} created."

    if activity_type == TaskActivity.TYPE_ASSIGNED:
        prefix = "Users updated to "
        if msg.startswith(prefix):
            names = msg[len(prefix) :].rstrip(".")
            return f"Task {title} reassigned to {names}."
        if msg:
            return f"Task {title}: {msg}"
        return f"Task {title} assignees updated."

    if activity_type == TaskActivity.TYPE_STATUS:
        old_l = Task.status_label(old_status) if old_status else ""
        new_l = Task.status_label(new_status) if new_status else ""
        if old_l and new_l:
            base = f"Task {title} status changed from {old_l} to {new_l}."
        elif new_l:
            base = f"Task {title} status changed to {new_l}."
        else:
            base = f"Task {title} status updated."
        if msg:
            return f"{base} {msg}".strip()
        return base

    if activity_type == TaskActivity.TYPE_REMARK:
        if msg:
            return f"Task {title} remark: {msg}"
        return f"Task {title} remark added."

    if activity_type == TaskActivity.TYPE_CHECKLIST:
        if msg:
            return f"Task {title}: {msg}"
        return f"Task {title} checklist updated."

    if activity_type == TaskActivity.TYPE_ENROLLMENT:
        if msg:
            return f"Task {title}: {msg}"
        return f"Task {title} enrollment updated."

    if msg:
        return f"Task {title}: {msg}"
    return f"Task {title} updated."


def log_task_client_activity(
    *,
    task,
    user: User | None,
    activity_type: str,
    message: str = "",
    old_status: str = "",
    new_status: str = "",
    metadata: dict | None = None,
) -> ClientActivityLog | None:
    if not task or not task.client_id:
        return None
    text = build_task_client_activity_text(
        task=task,
        activity_type=activity_type,
        message=message,
        old_status=old_status,
        new_status=new_status,
    )
    meta = dict(metadata or {})
    if activity_type == "remark" and (message or "").strip():
        meta["remark"] = (message or "").strip()
    return log_client_activity(
        client=task.client,
        user=user,
        category=ClientActivityLog.CATEGORY_TASK,
        activity=text,
        task=task,
        metadata=meta,
    )
