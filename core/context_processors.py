from core.feature_flags import task_module_enabled
from core.user_display import user_display_name


def enable_task_module(request):
    return {"enable_task_module": task_module_enabled()}


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


def task_nav_counts(request):
    if not task_module_enabled() or not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    from core.branch_access import approved_clients_for_user
    from tasks.models import Task, TaskNotification

    client_ids = approved_clients_for_user(request.user).values_list("pk", flat=True)
    base = Task.objects.filter(client_id__in=client_ids)
    return {
        "task_nav_my_count": base.filter(assignments__user=request.user)
        .exclude(status__in=[Task.STATUS_APPROVED, Task.STATUS_CANCELLED])
        .exclude(status=Task.STATUS_PENDING_ASSIGNMENT)
        .distinct()
        .count(),
        "task_nav_verify_count": base.filter(verifier=request.user)
        .filter(
            status__in=[Task.STATUS_SUBMITTED, Task.STATUS_PENDING_ASSIGNMENT],
        )
        .count(),
        "task_nav_notification_count": TaskNotification.objects.filter(
            user=request.user,
            is_read=False,
        ).count(),
    }
