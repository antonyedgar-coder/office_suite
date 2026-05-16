"""Branch scoping for employees (Client Master, MIS, directors, DIR-3, reports)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from masters.models import BRANCH_CHOICES, Client

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser
    from django.db.models import QuerySet

BRANCH_ACCESS_ALL = ""
EMPLOYEE_BRANCH_ACCESS_CHOICES = [("", "All branches")] + list(BRANCH_CHOICES)


def branch_access_for_user(user: AbstractBaseUser | None) -> str | None:
    """
    None = no branch restriction (superuser or All branches).
    Otherwise 'Trivandrum' or 'Nagercoil'.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return None
    if user.is_superuser:
        return None
    emp = getattr(user, "employee_profile", None)
    if not emp:
        return None
    br = (getattr(emp, "branch_access", None) or "").strip()
    if not br:
        return None
    return br


def filter_clients_by_branch(qs: QuerySet, user: AbstractBaseUser | None) -> QuerySet:
    br = branch_access_for_user(user)
    if br:
        qs = qs.filter(branch=br)
    return qs


def approved_clients_for_user(user: AbstractBaseUser | None) -> QuerySet:
    return filter_clients_by_branch(Client.approved_objects().order_by("client_name"), user)


def client_allowed_for_user(user: AbstractBaseUser | None, client: Client) -> bool:
    br = branch_access_for_user(user)
    if not br:
        return True
    return (client.branch or "") == br


def filter_mis_qs(qs: QuerySet, user: AbstractBaseUser | None, *, client_field: str = "client") -> QuerySet:
    br = branch_access_for_user(user)
    if br:
        qs = qs.filter(**{f"{client_field}__branch": br})
    return qs


def filter_director_mapping_qs(qs: QuerySet, user: AbstractBaseUser | None) -> QuerySet:
    """Director mappings where the director belongs to the user's branch."""
    br = branch_access_for_user(user)
    if br:
        qs = qs.filter(director__branch=br)
    return qs


def report_branch_filter(user: AbstractBaseUser | None, form_branch: str) -> str:
    """Apply user branch scope over MIS report branch choice (empty = all branches)."""
    scope = branch_access_for_user(user)
    if scope:
        return scope
    return (form_branch or "").strip()
