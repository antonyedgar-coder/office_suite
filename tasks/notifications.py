from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from .models import Task, TaskNotification

User = get_user_model()
ADMIN_GROUP_NAME = "Admin"


def admin_users():
    qs = User.objects.filter(is_active=True, is_superuser=True)
    try:
        admin_group = Group.objects.get(name=ADMIN_GROUP_NAME)
    except Group.DoesNotExist:
        return qs.distinct()
    return qs | User.objects.filter(is_active=True, groups=admin_group).distinct()


def notify_user(
    user,
    message: str,
    *,
    kind: str = TaskNotification.KIND_GENERAL,
    link: str = "",
    task: Task | None = None,
) -> TaskNotification:
    client = task.client if task else None
    return TaskNotification.objects.create(
        user=user,
        kind=kind,
        message=message,
        link=link,
        task=task,
        client=client,
    )


def notify_admin_group(
    message: str,
    *,
    kind: str = TaskNotification.KIND_RECURRING_FAIL,
    link: str = "",
    task: Task | None = None,
) -> list[TaskNotification]:
    created = []
    for u in admin_users():
        created.append(
            notify_user(u, message, kind=kind, link=link, task=task),
        )
    return created
