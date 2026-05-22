"""Helpers for recording who created settings / master records."""

from __future__ import annotations

from django.conf import settings
from django.db import models


def created_by_field(**extra):
    """Reusable FK — use related_name='+' to avoid reverse clutter on User."""
    defaults = {
        "to": settings.AUTH_USER_MODEL,
        "on_delete": models.SET_NULL,
        "null": True,
        "blank": True,
        "editable": False,
        "related_name": "+",
    }
    defaults.update(extra)
    return models.ForeignKey(**defaults)


def stamp_created_by(instance, user) -> None:
    """Set created_by on a new record before save (no-op if field missing or user anonymous)."""
    if not getattr(user, "is_authenticated", False):
        return
    if hasattr(instance, "created_by_id") and instance.created_by_id is None:
        instance.created_by = user


def save_form_with_creator(form, user):
    """Save a ModelForm and stamp created_by on first save."""
    obj = form.save(commit=False)
    stamp_created_by(obj, user)
    obj.save()
    return obj


CREATED_BY_SELECT = ("created_by", "created_by__employee_profile")


def creator_display(user) -> str:
    if user is None:
        return "—"
    from .user_display import user_display_name

    label = user_display_name(user)
    return label or user.get_username() or "—"
