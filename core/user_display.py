from __future__ import annotations

from django.contrib.auth import get_user_model

User = get_user_model()


def user_display_name(user: User | None) -> str:
    """Employee display name only (never login email)."""
    if user is None:
        return ""
    emp = getattr(user, "employee_profile", None)
    if emp and (emp.full_name or "").strip():
        return emp.full_name.strip()
    return (user.get_full_name() or "").strip()
