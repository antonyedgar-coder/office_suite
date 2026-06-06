"""Change login email (User.email / username) while keeping the same user record and FK links."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from .models import ActivityLog, Employee

User = get_user_model()


def normalize_login_email(raw: str) -> str:
    return User.objects.normalize_email((raw or "").strip().lower())


def apply_user_login_email_change(
    user,
    new_email: str,
    *,
    employee: Employee | None = None,
) -> bool:
    """
    Update login email on the existing user.

    Tasks, MIS rows, and other records linked by user id stay with this account.
    Activity log rows for this user get their denormalized email updated for search.
    """
    normalized = normalize_login_email(new_email)
    if not normalized or user.email.lower() == normalized.lower():
        return False

    if (
        employee
        and employee.user_type == Employee.USER_TYPE_CLIENT
        and employee.linked_client_id
    ):
        client = employee.linked_client
        client.email = normalized
        client.save(update_fields=["email", "updated_at"])

    user.email = normalized
    user.username = normalized
    ActivityLog.objects.filter(user=user).update(user_email=normalized[:254])
    return True
