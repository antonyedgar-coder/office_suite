"""Multiple verifiers per task."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from .user_labels import user_person_name

User = get_user_model()


def user_is_task_verifier(user, task) -> bool:
    if user.is_superuser:
        return True
    return task.verifiers.filter(pk=user.pk).exists()


def format_task_verifier_names(task) -> str:
    names = [user_person_name(u) for u in task.verifiers.all()]
    return ", ".join(names) if names else "—"


def notify_task_verifiers(task, *, message: str, kind: str, link: str, exclude_user_ids=None):
    from .notifications import notify_user

    exclude = set(exclude_user_ids or [])
    for verifier in task.verifiers.all():
        if verifier.pk in exclude:
            continue
        notify_user(
            verifier,
            message,
            kind=kind,
            link=link,
            task=task,
        )
