"""Lookups for configurable Client Type master (Settings)."""

from __future__ import annotations

from django.db.utils import OperationalError, ProgrammingError

from .models import (
    CLIENT_TYPE_NEW_CLIENT,
    CLIENT_TYPE_ONE_OFF,
    CLIENT_TYPES,
    PAN_OPTIONAL_CLIENT_TYPES,
    ClientType,
)


def _client_type_table_ready() -> bool:
    """False before migration 0029 has created masters_clienttype."""
    from django.db import connection

    try:
        return "masters_clienttype" in connection.introspection.table_names()
    except Exception:
        return False


def _static_type_choices() -> list[tuple[str, str]]:
    return list(CLIENT_TYPES)


def lookup_client_type(name: str) -> ClientType | None:
    key = (name or "").strip()
    if not key or not _client_type_table_ready():
        return None
    try:
        return ClientType.objects.filter(name=key).first()
    except (OperationalError, ProgrammingError):
        return None


def is_pan_mandatory_for_type(type_name: str) -> bool:
    row = lookup_client_type(type_name)
    if row is not None:
        return row.pan_mandatory
    return (type_name or "").strip() not in PAN_OPTIONAL_CLIENT_TYPES and (type_name or "").strip() != "Branch"


def allow_task_submit_without_pan(type_name: str) -> bool:
    row = lookup_client_type(type_name)
    if row is not None:
        return row.allow_task_submit_without_pan
    if (type_name or "").strip() == CLIENT_TYPE_NEW_CLIENT:
        return False
    if (type_name or "").strip() in {CLIENT_TYPE_ONE_OFF, "Foreign Citizen", "Branch"}:
        return True
    return True


def client_type_choices_for_form(*, instance: object | None = None) -> list[tuple[str, str]]:
    """Active types for Client Master dropdown; include current type on edit if inactive."""
    if not _client_type_table_ready():
        return _static_type_choices()
    try:
        qs = ClientType.objects.filter(is_active=True).order_by("sort_order", "name")
        names = list(qs.values_list("name", flat=True))
    except (OperationalError, ProgrammingError):
        return _static_type_choices()
    if instance and getattr(instance, "pk", None):
        current = (getattr(instance, "client_type", None) or "").strip()
        if current and current not in names:
            names.append(current)
            names.sort(key=str.casefold)
    return [(n, n) for n in names] if names else _static_type_choices()


def client_type_choices_for_reports() -> list[tuple[str, str]]:
    """All configured types (active and inactive) for report filters."""
    if not _client_type_table_ready():
        return _static_type_choices()
    try:
        names = list(
            ClientType.objects.order_by("sort_order", "name").values_list("name", flat=True)
        )
    except (OperationalError, ProgrammingError):
        return _static_type_choices()
    return [(n, n) for n in names] if names else _static_type_choices()
