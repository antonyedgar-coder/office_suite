"""Business rules tied to Client Master client type."""

from __future__ import annotations

from django.core.exceptions import ValidationError

from masters.models import CLIENT_TYPE_NEW_CLIENT

from .models import Task


def is_new_client_type(client) -> bool:
    ct = (getattr(client, "client_type", None) or "").strip()
    return ct == CLIENT_TYPE_NEW_CLIENT


def may_submit_for_client_type(task: Task) -> bool:
    """Assignees cannot submit for verification when client type is New Client."""
    if task.status == Task.STATUS_DOCUMENT_REWORK:
        return True
    return not is_new_client_type(task.client)


def validate_submit_for_client_type(task: Task) -> None:
    if may_submit_for_client_type(task):
        return
    raise ValidationError(f'Clients with type "{CLIENT_TYPE_NEW_CLIENT}" cannot submit tasks for verification.')


def none_client_submit_block_message() -> str:
    return f'Clients with type "{CLIENT_TYPE_NEW_CLIENT}" cannot submit tasks for verification.'
