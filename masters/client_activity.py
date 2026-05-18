from __future__ import annotations

from django.contrib.auth import get_user_model

from .models import Client, ClientActivityLog

User = get_user_model()


def user_display_name(user: User | None) -> str:
    if user is None:
        return ""
    try:
        from tasks.user_labels import user_person_name

        return user_person_name(user)
    except ImportError:
        emp = getattr(user, "employee_profile", None)
        if emp and (emp.full_name or "").strip():
            return emp.full_name.strip()
        return (user.get_full_name() or "").strip() or (user.email or "")


def log_client_activity(
    *,
    client: Client | None,
    user: User | None,
    category: str,
    activity: str,
    task=None,
    metadata: dict | None = None,
) -> ClientActivityLog | None:
    if not client:
        return None
    text = (activity or "").strip()
    if not text:
        return None
    return ClientActivityLog.objects.create(
        client=client,
        user=user,
        category=category,
        activity=text,
        task=task,
        metadata=metadata or {},
    )


def get_client_activity_timeline(client: Client, *, limit: int = 100):
    return (
        ClientActivityLog.objects.filter(client=client)
        .select_related("user", "user__employee_profile", "task", "task__task_master")
        .order_by("-created_at")[:limit]
    )


def build_client_activity_rows(logs, *, can_link_tasks: bool) -> list[dict]:
    rows: list[dict] = []
    for log in logs:
        task = log.task if log.task_id else None
        row = {
            "created_at": log.created_at,
            "category_label": log.get_category_display(),
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
    return log_client_activity(
        client=task.client,
        user=user,
        category=ClientActivityLog.CATEGORY_TASK,
        activity=text,
        task=task,
        metadata=metadata,
    )
