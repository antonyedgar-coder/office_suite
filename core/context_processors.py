from core.feature_flags import documents_module_enabled, task_module_enabled
from core.settings_hub import user_may_open_settings
from core.user_display import user_display_name


def enable_task_module(request):
    return {"enable_task_module": task_module_enabled()}


def enable_documents_module(request):
    return {"enable_documents_module": documents_module_enabled()}


def master_request_nav_counts(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    from masters.master_request_service import (
        user_can_view_master_requests,
        user_sees_assigned_queue,
    )
    from masters.models import MasterRequest, MasterRequestNotification

    out = {"show_master_requests_nav": user_can_view_master_requests(request.user)}
    badge = MasterRequestNotification.objects.filter(
        user=request.user,
        is_read=False,
    ).count()
    if user_sees_assigned_queue(request.user):
        badge += MasterRequest.objects.filter(
            assigned_to=request.user,
            status=MasterRequest.STATUS_SUBMITTED,
        ).count()
    if badge:
        out["master_request_nav_pending_count"] = badge
    return out


def settings_hub_access(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    return {"show_settings_hub": user_may_open_settings(request.user)}


def topbar_user(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    name = user_display_name(request.user)
    meta_parts = []
    emp = getattr(request.user, "employee_profile", None)
    if emp:
        if emp.branch_access:
            meta_parts.append(emp.get_branch_access_display())
        if emp.user_type:
            meta_parts.append(emp.get_user_type_display())
    return {
        "topbar_user_name": name or "User",
        "topbar_user_meta": " · ".join(meta_parts) if meta_parts else "",
        "topbar_user_email": request.user.email,
    }


def dsc_nav_counts(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    emp = getattr(request.user, "employee_profile", None)
    may_see = (
        request.user.is_superuser
        or request.user.has_perm("masters.view_clientdsc")
        or (emp and emp.receive_dsc_expiry_notifications)
    )
    if not may_see:
        return {}
    from masters.models import DSCNotification

    return {
        "may_view_dsc_alerts": True,
        "dsc_nav_notification_count": DSCNotification.objects.filter(
            user=request.user,
            is_read=False,
        ).count(),
    }


def task_nav_counts(request):
    if not task_module_enabled() or not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    from django.db.models import Q

    from core.branch_access import approved_clients_for_user
    from masters.models import CLIENT_TYPE_NEW_CLIENT
    from tasks.models import Task, TaskNotification

    client_ids = approved_clients_for_user(request.user).values_list("pk", flat=True)
    base = Task.objects.filter(client_id__in=client_ids)
    return {
        "task_nav_my_count": base.filter(assignments__user=request.user)
        .exclude(status__in=Task.DONE_FOR_ASSIGNEE_STATUSES)
        .exclude(status=Task.STATUS_PENDING_ASSIGNMENT)
        .distinct()
        .count(),
        "task_nav_verify_count": base.filter(verifier=request.user)
        .filter(
            Q(status__in=[Task.STATUS_SUBMITTED, Task.STATUS_PENDING_ASSIGNMENT])
            | Q(
                client__client_type=CLIENT_TYPE_NEW_CLIENT,
                status__in=[Task.STATUS_ASSIGNED, Task.STATUS_REWORK],
            )
        )
        .count(),
        "task_nav_document_check_count": base.filter(
            document_checker=request.user,
            status=Task.STATUS_VERIFIED,
        ).count(),
        "task_nav_notification_count": TaskNotification.objects.filter(
            user=request.user,
            is_read=False,
        ).count(),
    }
