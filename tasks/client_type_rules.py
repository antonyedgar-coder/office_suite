"""Business rules tied to Client Master client type."""

from __future__ import annotations

from django.core.exceptions import ValidationError

from masters.client_type_service import allow_task_submit_without_pan
from masters.models import CLIENT_TYPE_NEW_CLIENT

from .models import Task


def is_new_client_type(client) -> bool:
    ct = (getattr(client, "client_type", None) or "").strip()
    return ct == CLIENT_TYPE_NEW_CLIENT


def may_submit_for_client_type(task: Task) -> bool:
    """Task submit when PAN is blank follows Client Type master; New Client always blocked."""
    if task.status == Task.STATUS_DOCUMENT_REWORK:
        return True
    client = task.client
    if is_new_client_type(client):
        return False
    pan = (getattr(client, "pan", None) or "").strip()
    if not pan:
        return allow_task_submit_without_pan(client.client_type)
    return True


def validate_submit_for_client_type(task: Task) -> None:
    if may_submit_for_client_type(task):
        return
    ct = (getattr(task.client, "client_type", None) or "").strip()
    if is_new_client_type(task.client):
        raise ValidationError(f'Clients with type "{ct}" cannot submit tasks for verification.')
    raise ValidationError(
        f'Clients with type "{ct}" cannot submit tasks for verification when PAN is not provided.'
    )


def none_client_submit_block_message() -> str:
    return (
        "This client type does not allow task submission for verification "
        "(see Settings → Client types)."
    )
