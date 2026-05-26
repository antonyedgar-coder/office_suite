"""Sidebar nav badge counts (context processors and polling API)."""

from __future__ import annotations

from core.feature_flags import task_module_enabled


def build_nav_badge_counts(request) -> dict:
    """Return JSON-serializable badge counts for the current user."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    out: dict[str, int] = {}

    from masters.master_request_service import (
        user_can_view_master_requests,
        user_sees_assigned_queue,
    )
    from masters.models import MasterRequest, MasterRequestNotification

    if user_can_view_master_requests(user):
        badge = MasterRequestNotification.objects.filter(user=user, is_read=False).count()
        if user_sees_assigned_queue(user):
            badge += MasterRequest.objects.filter(
                assigned_to=user,
                status=MasterRequest.STATUS_SUBMITTED,
            ).count()
        if badge:
            out["master_requests"] = badge

    emp = getattr(user, "employee_profile", None)
    may_see_dsc = (
        user.is_superuser
        or user.has_perm("masters.view_clientdsc")
        or (emp and emp.receive_dsc_expiry_notifications)
    )
    if may_see_dsc:
        from masters.models import DSCNotification

        count = DSCNotification.objects.filter(user=user, is_read=False).count()
        if count:
            out["dsc_notifications"] = count

    if task_module_enabled():
        from django.db.models import Q

        from core.branch_access import approved_clients_for_user
        from masters.models import CLIENT_TYPE_NEW_CLIENT
        from tasks.models import Task, TaskNotification

        client_ids = approved_clients_for_user(user).values_list("pk", flat=True)
        base = Task.objects.filter(client_id__in=client_ids)

        my_count = (
            base.filter(assignments__user=user)
            .exclude(status__in=Task.DONE_FOR_ASSIGNEE_STATUSES)
            .exclude(status=Task.STATUS_PENDING_ASSIGNMENT)
            .distinct()
            .count()
        )
        if my_count:
            out["task_my"] = my_count

        verify_count = (
            base.filter(verifiers=user)
            .filter(
                Q(status__in=[Task.STATUS_SUBMITTED, Task.STATUS_PENDING_ASSIGNMENT])
                | Q(
                    client__client_type=CLIENT_TYPE_NEW_CLIENT,
                    status__in=[Task.STATUS_ASSIGNED, Task.STATUS_REWORK],
                )
            )
            .count()
        )
        if verify_count:
            out["task_verify"] = verify_count

        doc_check_count = base.filter(
            document_checker=user,
            status=Task.STATUS_VERIFIED,
        ).count()
        if doc_check_count:
            out["task_document_check"] = doc_check_count

        notify_count = TaskNotification.objects.filter(user=user, is_read=False).count()
        if notify_count:
            out["task_notifications"] = notify_count

    return out
