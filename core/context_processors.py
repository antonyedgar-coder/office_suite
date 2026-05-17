from core.feature_flags import task_module_enabled


def enable_task_module(request):
    return {"enable_task_module": task_module_enabled()}


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
        .distinct()
        .count(),
        "task_nav_verify_count": base.filter(
            status=Task.STATUS_SUBMITTED,
            verifier=request.user,
        ).count(),
        "task_nav_notification_count": TaskNotification.objects.filter(
            user=request.user,
            is_read=False,
        ).count(),
    }
