"""Task list filters, annotations, and row preparation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.branch_access import approved_clients_for_user

from .date_presets import DATE_PRESET_CHOICES, PRESET_CUSTOM, resolve_date_preset
from .models import Task, TaskMaster
from .period_display import PeriodColumns, format_next_period, format_period_key
from .user_labels import build_short_codes_for_users, staff_users_queryset, user_person_name

User = get_user_model()


@dataclass
class TaskListFilters:
    status: str = ""
    client_id: str = ""
    master_id: str = ""
    assignee_id: str = ""
    verifier_id: str = ""
    created_preset: str = "all_time"
    created_from: str = ""
    created_to: str = ""
    due_preset: str = "all_time"
    due_from: str = ""
    due_to: str = ""
    approved_preset: str = "all_time"
    approved_from: str = ""
    approved_to: str = ""


def _parse_preset_block(request, prefix: str) -> tuple[str, str, str]:
    preset = (request.GET.get(f"{prefix}_preset") or "all_time").strip()
    raw_from = (request.GET.get(f"{prefix}_from") or "").strip()
    raw_to = (request.GET.get(f"{prefix}_to") or "").strip()
    if preset != PRESET_CUSTOM:
        d_from, d_to = resolve_date_preset(preset, raw_from, raw_to)
        return preset, d_from.isoformat() if d_from else "", d_to.isoformat() if d_to else ""
    return preset, raw_from, raw_to


def parse_task_list_filters(request) -> TaskListFilters:
    c_preset, c_from, c_to = _parse_preset_block(request, "created")
    d_preset, d_from, d_to = _parse_preset_block(request, "due")
    a_preset, a_from, a_to = _parse_preset_block(request, "approved")
    g = request.GET
    return TaskListFilters(
        status=(g.get("status") or "").strip(),
        client_id=(g.get("client") or "").strip(),
        master_id=(g.get("master") or "").strip(),
        assignee_id=(g.get("assignee") or "").strip(),
        verifier_id=(g.get("verifier") or "").strip(),
        created_preset=c_preset,
        created_from=c_from,
        created_to=c_to,
        due_preset=d_preset,
        due_from=d_from,
        due_to=d_to,
        approved_preset=a_preset,
        approved_from=a_from,
        approved_to=a_to,
    )


def tasks_queryset_for_user(user):
    return Task.objects.filter(
        client_id__in=approved_clients_for_user(user).values_list("pk", flat=True)
    ).select_related(
        "client",
        "task_master",
        "task_master__task_group",
        "verifier",
        "verifier__employee_profile",
        "created_by",
        "created_by__employee_profile",
        "submitted_by",
        "submitted_by__employee_profile",
        "approved_by",
        "approved_by__employee_profile",
        "enrollment",
    )


def apply_task_list_filters(qs, filters: TaskListFilters):
    if filters.status:
        qs = qs.filter(status=filters.status)
    if filters.client_id:
        qs = qs.filter(client_id=filters.client_id)
    if filters.master_id:
        qs = qs.filter(task_master_id=filters.master_id)
    if filters.assignee_id:
        qs = qs.filter(assignments__user_id=filters.assignee_id)
    if filters.verifier_id:
        qs = qs.filter(verifier_id=filters.verifier_id)

    c_from = parse_date(filters.created_from)
    c_to = parse_date(filters.created_to)
    if c_from:
        qs = qs.filter(created_at__date__gte=c_from)
    if c_to:
        qs = qs.filter(created_at__date__lte=c_to)

    d_from = parse_date(filters.due_from)
    d_to = parse_date(filters.due_to)
    if d_from:
        qs = qs.filter(due_date__gte=d_from)
    if d_to:
        qs = qs.filter(due_date__lte=d_to)

    a_from = parse_date(filters.approved_from)
    a_to = parse_date(filters.approved_to)
    if a_from:
        qs = qs.filter(approved_at__date__gte=a_from)
    if a_to:
        qs = qs.filter(approved_at__date__lte=a_to)
    return qs.distinct()


@dataclass
class TaskListRow:
    task: Task
    period: PeriodColumns
    created_date: str
    submitted_date: str
    submitted_by: str
    submitted_by_name: str
    verified_date: str
    verified_by: str
    verified_by_name: str
    assignee_names: str


def _fmt_date(dt) -> str:
    if not dt:
        return ""
    if isinstance(dt, datetime):
        local = timezone.localtime(dt) if timezone.is_aware(dt) else dt
        return local.strftime("%d-%b-%Y")
    return str(dt)


def prepare_task_list_rows(tasks, *, include_assignees: bool = False) -> list[TaskListRow]:
    task_list = list(tasks)
    user_ids = set()
    for t in task_list:
        if t.submitted_by_id:
            user_ids.add(t.submitted_by_id)
        if t.approved_by_id:
            user_ids.add(t.approved_by_id)

    users = User.objects.filter(pk__in=user_ids).select_related("employee_profile")
    short_codes = build_short_codes_for_users(users)
    name_by_id = {u.pk: user_person_name(u) for u in users}

    assignees_by_task: dict[int, str] = {}
    if include_assignees and task_list:
        from .models import TaskAssignment

        task_ids = [t.pk for t in task_list]
        assigns = TaskAssignment.objects.filter(task_id__in=task_ids).select_related(
            "user", "user__employee_profile"
        )
        buckets: dict[int, list[str]] = {tid: [] for tid in task_ids}
        for a in assigns:
            buckets[a.task_id].append(user_person_name(a.user))
        assignees_by_task = {tid: ", ".join(names) for tid, names in buckets.items()}

    rows = []
    for task in task_list:
        period = format_period_key(task.period_key)
        period.next_period = format_next_period(task)
        rows.append(
            TaskListRow(
                task=task,
                period=period,
                created_date=_fmt_date(task.created_at),
                submitted_date=_fmt_date(task.submitted_at),
                submitted_by=short_codes.get(task.submitted_by_id, ""),
                submitted_by_name=name_by_id.get(task.submitted_by_id, ""),
                verified_date=_fmt_date(task.approved_at),
                verified_by=short_codes.get(task.approved_by_id, ""),
                verified_by_name=name_by_id.get(task.approved_by_id, ""),
                assignee_names=assignees_by_task.get(task.pk, ""),
            )
        )
    return rows


def filter_context(user, filters: TaskListFilters) -> dict:
    return {
        "filters": filters,
        "status_choices": Task.STATUS_CHOICES,
        "date_preset_choices": DATE_PRESET_CHOICES,
        "clients": approved_clients_for_user(user).order_by("client_name"),
        "masters": TaskMaster.objects.filter(is_active=True, archived_at__isnull=True)
        .select_related("task_group")
        .order_by("task_group__sort_order", "name"),
        "staff_users": staff_users_queryset(),
    }


def get_filtered_tasks(user, filters: TaskListFilters, *, base_qs=None, limit: int = 500):
    qs = base_qs if base_qs is not None else tasks_queryset_for_user(user)
    qs = apply_task_list_filters(qs, filters)
    return qs.order_by("-created_at", "-due_date")[:limit]


def filters_query_string(filters: TaskListFilters) -> str:
    from urllib.parse import urlencode

    params = {}
    if filters.status:
        params["status"] = filters.status
    if filters.client_id:
        params["client"] = filters.client_id
    if filters.master_id:
        params["master"] = filters.master_id
    if filters.assignee_id:
        params["assignee"] = filters.assignee_id
    if filters.verifier_id:
        params["verifier"] = filters.verifier_id
    for prefix in ("created", "due", "approved"):
        preset = getattr(filters, f"{prefix}_preset")
        if preset:
            params[f"{prefix}_preset"] = preset
        if preset == PRESET_CUSTOM:
            f_from = getattr(filters, f"{prefix}_from")
            f_to = getattr(filters, f"{prefix}_to")
            if f_from:
                params[f"{prefix}_from"] = f_from
            if f_to:
                params[f"{prefix}_to"] = f_to
    return urlencode(params)
