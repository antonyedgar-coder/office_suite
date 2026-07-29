"""Task list filters, annotations, and row preparation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.branch_access import approved_clients_for_user

from .date_presets import DATE_PRESET_CHOICES, PRESET_ALL_TIME, PRESET_CUSTOM, resolve_date_preset
from .models import Task, TaskMaster
from .period_display import PeriodColumns, format_next_period, format_period_display
from .user_labels import build_short_codes_for_users, staff_users_queryset, user_display_label, user_person_name

User = get_user_model()


_VALID_STATUSES = frozenset(code for code, _label in Task.STATUS_CHOICES)


@dataclass
class TaskListFilters:
    statuses: tuple[str, ...] = ()
    client_ids: tuple[str, ...] = ()
    master_ids: tuple[str, ...] = ()
    assignee_ids: tuple[str, ...] = ()
    verifier_id: str = ""
    document_checker_id: str = ""
    created_preset: str = "all_time"
    created_from: str = ""
    created_to: str = ""
    due_preset: str = "all_time"
    due_from: str = ""
    due_to: str = ""
    approved_preset: str = "all_time"
    approved_from: str = ""
    approved_to: str = ""

    @property
    def status(self) -> str:
        """Comma-joined status codes for form hidden fields / query strings."""
        return ",".join(self.statuses)

    @property
    def client_id(self) -> str:
        """Comma-joined IDs for form hidden fields / templates."""
        return ",".join(self.client_ids)

    @property
    def master_id(self) -> str:
        return ",".join(self.master_ids)

    @property
    def assignee_id(self) -> str:
        return ",".join(self.assignee_ids)


def _parse_preset_block(request, prefix: str) -> tuple[str, str, str]:
    preset = (request.GET.get(f"{prefix}_preset") or "all_time").strip()
    raw_from = (request.GET.get(f"{prefix}_from") or "").strip()
    raw_to = (request.GET.get(f"{prefix}_to") or "").strip()
    if preset != PRESET_CUSTOM:
        d_from, d_to = resolve_date_preset(preset, raw_from, raw_to)
        return preset, d_from.isoformat() if d_from else "", d_to.isoformat() if d_to else ""
    return preset, raw_from, raw_to


def _parse_multi_ids(request, param: str) -> tuple[str, ...]:
    """Accept repeated GET keys and/or comma-separated values."""
    values: list[str] = []
    seen: set[str] = set()
    for raw in request.GET.getlist(param):
        for part in str(raw or "").replace(" ", "").split(","):
            part = part.strip()
            if part and part not in seen:
                seen.add(part)
                values.append(part)
    return tuple(values)


def parse_task_list_filters(request) -> TaskListFilters:
    c_preset, c_from, c_to = _parse_preset_block(request, "created")
    d_preset, d_from, d_to = _parse_preset_block(request, "due")
    a_preset, a_from, a_to = _parse_preset_block(request, "approved")
    g = request.GET
    statuses = tuple(s for s in _parse_multi_ids(request, "status") if s in _VALID_STATUSES)
    return TaskListFilters(
        statuses=statuses,
        client_ids=_parse_multi_ids(request, "client"),
        master_ids=_parse_multi_ids(request, "master"),
        assignee_ids=_parse_multi_ids(request, "assignee"),
        verifier_id=(g.get("verifier") or "").strip(),
        document_checker_id=(g.get("document_checker") or "").strip(),
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
    ).prefetch_related("verifiers", "verifiers__employee_profile").select_related(
        "client",
        "task_master",
        "task_master__task_group",
        "document_checker",
        "document_checker__employee_profile",
        "created_by",
        "created_by__employee_profile",
        "submitted_by",
        "submitted_by__employee_profile",
        "approved_by",
        "approved_by__employee_profile",
        "enrollment",
    )


def tasks_queryset_personal_for_user(user):
    """Tasks the user is assigned to, verifies, or created (branch-scoped)."""
    return tasks_queryset_for_user(user).filter(
        Q(assignments__user=user) | Q(verifiers=user) | Q(created_by=user)
    ).distinct()


def apply_task_list_filters(qs, filters: TaskListFilters):
    if filters.statuses:
        qs = qs.filter(status__in=filters.statuses)
    if filters.client_ids:
        qs = qs.filter(client_id__in=filters.client_ids)
    if filters.master_ids:
        qs = qs.filter(task_master_id__in=filters.master_ids)
    if filters.assignee_ids:
        qs = qs.filter(assignments__user_id__in=filters.assignee_ids)
    if filters.verifier_id:
        qs = qs.filter(verifiers__id=filters.verifier_id)
    if filters.document_checker_id:
        qs = qs.filter(document_checker_id=filters.document_checker_id)

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
        period = format_period_display(
            task.period_key,
            period_type=task.period_type or "",
            master=task.task_master,
        )
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
    masters = list(TaskMaster.selectable_for_new_tasks())
    clients = list(approved_clients_for_user(user).order_by("client_name"))
    return {
        "filters": filters,
        "status_choices": Task.STATUS_CHOICES,
        "date_preset_choices": DATE_PRESET_CHOICES,
        "clients": clients,
        "masters": masters,
        "status_filter_options": [
            {
                "id": code,
                "label": label,
                "search": f"{label} {code}".lower(),
            }
            for code, label in Task.STATUS_CHOICES
        ],
        "client_filter_options": [
            {
                "id": c.client_id,
                "label": f"{c.client_name} — {c.pan.upper()}" if c.pan else c.client_name,
                "search": f"{c.client_name} {c.pan or ''} {c.client_id}".lower(),
            }
            for c in clients
        ],
        "master_filter_options": [
            {
                "id": m.pk,
                "label": f"{m.task_group.name} — {m.name}",
                "search": f"{m.task_group.name} {m.name}".lower(),
            }
            for m in masters
        ],
        "staff_users": staff_users_queryset(),
        "staff_user_options": [
            {
                "id": u.pk,
                "label": user_display_label(u),
                "search": f"{user_display_label(u)} {u.email}".lower(),
            }
            for u in staff_users_queryset()
        ],
    }


def get_filtered_tasks(user, filters: TaskListFilters, *, base_qs=None, limit: int = 500):
    qs = base_qs if base_qs is not None else tasks_queryset_for_user(user)
    qs = apply_task_list_filters(qs, filters)
    return qs.order_by("-created_at", "-due_date")[:limit]


def task_list_url(
    route_name: str,
    *,
    status: str = "",
    assignee_id: str = "",
    verifier_id: str = "",
    open_tasks: bool = False,
) -> str:
    """Build a task list URL with standard date presets applied."""
    from urllib.parse import urlencode

    from django.urls import reverse

    params: dict[str, str] = {
        "created_preset": PRESET_ALL_TIME,
        "due_preset": PRESET_ALL_TIME,
        "approved_preset": PRESET_ALL_TIME,
    }
    if status:
        params["status"] = status
    if assignee_id:
        params["assignee"] = assignee_id
    if verifier_id:
        params["verifier"] = verifier_id
    if open_tasks:
        params["open"] = "1"
    q = urlencode(params)
    return f"{reverse(route_name)}?{q}" if q else reverse(route_name)


def filters_query_string(filters: TaskListFilters) -> str:
    from urllib.parse import urlencode

    params = {}
    if filters.statuses:
        params["status"] = ",".join(filters.statuses)
    if filters.client_ids:
        params["client"] = ",".join(filters.client_ids)
    if filters.master_ids:
        params["master"] = ",".join(filters.master_ids)
    if filters.assignee_ids:
        params["assignee"] = ",".join(filters.assignee_ids)
    if filters.verifier_id:
        params["verifier"] = filters.verifier_id
    if filters.document_checker_id:
        params["document_checker"] = filters.document_checker_id
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
