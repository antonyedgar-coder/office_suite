from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from core.feature_flags import task_module_enabled


def _managed_models() -> tuple[tuple[str, str], ...]:
    """Models whose Django permissions are exposed in Group / User access UI."""
    models: list[tuple[str, str]] = [
        ("masters", "client"),
        ("masters", "clientgroup"),
        ("masters", "directormapping"),
        ("core", "employee"),
        ("reports", "reportpolicy"),
        ("mis", "feesdetail"),
        ("mis", "receipt"),
        ("mis", "expensedetail"),
        ("mis", "tenderdetail"),
        ("dirkyc", "dir3kyc"),
    ]
    if task_module_enabled():
        models.extend(
            [
                ("tasks", "taskgroup"),
                ("tasks", "taskmaster"),
                ("tasks", "task"),
            ]
        )
    return tuple(models)


def manageable_permissions():
    """Permissions assignable to groups/users for this application."""
    q = Q()
    for app_label, model in _managed_models():
        q |= Q(app_label=app_label, model=model)
    cts = ContentType.objects.filter(q)
    return (
        Permission.objects.filter(content_type__in=cts)
        .select_related("content_type")
        .order_by("content_type__app_label", "content_type__model", "codename")
    )
