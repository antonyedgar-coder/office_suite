"""Task dashboard counts (due-date buckets)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from .date_presets import PRESET_ALL_TIME, PRESET_CUSTOM
from .models import Task


@dataclass(frozen=True)
class DueBucket:
    key: str
    label: str
    count: int
    list_url: str


@dataclass(frozen=True)
class TaskDetailCard:
    key: str
    label: str
    count: int
    list_url: str


def _open_tasks_with_due(qs, *, today: date):
    return qs.exclude(status__in=Task.CLOSED_STATUSES).filter(
        due_date__isnull=False
    )


def task_due_bucket_counts(qs, *, today: date | None = None) -> dict[str, int]:
    """
    Mutually exclusive due-date buckets for open tasks (complete/cancelled excluded).

    Overdue buckets use calendar days from due date through today:
    - overdue_up_to_7: 1–7 days past due
    - overdue_up_to_30: 8–30 days past due
    - overdue_over_30: more than 30 days past due
    """
    today = today or timezone.localdate()
    open_qs = _open_tasks_with_due(qs, today=today)
    in_7 = today + timedelta(days=7)

    return {
        "due_today": open_qs.filter(due_date=today).count(),
        "due_next_7_days": open_qs.filter(due_date__gt=today, due_date__lte=in_7).count(),
        "overdue_up_to_7": open_qs.filter(
            due_date__lt=today,
            due_date__gte=today - timedelta(days=7),
        ).count(),
        "overdue_up_to_30": open_qs.filter(
            due_date__lt=today - timedelta(days=7),
            due_date__gte=today - timedelta(days=30),
        ).count(),
        "overdue_over_30": open_qs.filter(due_date__lt=today - timedelta(days=30)).count(),
    }


def _task_list_due_url(
    *,
    due_from: date | None,
    due_to: date | None,
    list_route: str = "task_list",
) -> str:
    from django.urls import reverse

    params = {
        "due_preset": PRESET_CUSTOM,
        "due_from": due_from.isoformat() if due_from else "",
        "due_to": due_to.isoformat() if due_to else "",
        "created_preset": PRESET_ALL_TIME,
        "approved_preset": PRESET_ALL_TIME,
    }
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{reverse(list_route)}?{q}"


def task_due_buckets(
    qs,
    *,
    today: date | None = None,
    list_route: str = "task_list",
) -> list[DueBucket]:
    """Counts plus links to a task list filtered by due date range."""
    today = today or timezone.localdate()
    counts = task_due_bucket_counts(qs, today=today)
    in_7 = today + timedelta(days=7)

    return [
        DueBucket(
            key="due_today",
            label="Due today",
            count=counts["due_today"],
            list_url=_task_list_due_url(due_from=today, due_to=today, list_route=list_route),
        ),
        DueBucket(
            key="due_next_7_days",
            label="Due next 7 days",
            count=counts["due_next_7_days"],
            list_url=_task_list_due_url(
                due_from=today + timedelta(days=1), due_to=in_7, list_route=list_route
            ),
        ),
        DueBucket(
            key="overdue_up_to_7",
            label="Overdue up to 7 days",
            count=counts["overdue_up_to_7"],
            list_url=_task_list_due_url(
                due_from=today - timedelta(days=7),
                due_to=today - timedelta(days=1),
                list_route=list_route,
            ),
        ),
        DueBucket(
            key="overdue_up_to_30",
            label="Overdue up to 30 days",
            count=counts["overdue_up_to_30"],
            list_url=_task_list_due_url(
                due_from=today - timedelta(days=30),
                due_to=today - timedelta(days=8),
                list_route=list_route,
            ),
        ),
        DueBucket(
            key="overdue_over_30",
            label="Overdue more than 30 days",
            count=counts["overdue_over_30"],
            list_url=_task_list_due_url(
                due_from=None,
                due_to=today - timedelta(days=31),
                list_route=list_route,
            ),
        ),
    ]


def _my_open_qs(base, user):
    return (
        base.filter(assignments__user=user)
        .exclude(status__in=Task.DONE_FOR_ASSIGNEE_STATUSES)
        .exclude(status=Task.STATUS_PENDING_ASSIGNMENT)
        .distinct()
    )


def _document_check_queue_qs(base, user):
    return base.filter(document_checker=user, status=Task.STATUS_VERIFIED)


def _verify_queue_qs(base, user):
    return base.filter(verifier=user, status__in=[Task.STATUS_SUBMITTED, Task.STATUS_PENDING_ASSIGNMENT])


def _task_detail_cards(
    user,
    *,
    office_view: bool,
    branch_base,
) -> list[TaskDetailCard]:
    from django.urls import reverse

    from .listing import task_list_url

    my_open = _my_open_qs(branch_base, user).count()
    my_submitted = (
        branch_base.filter(assignments__user=user, status=Task.STATUS_SUBMITTED).distinct().count()
    )
    verify_count = _verify_queue_qs(branch_base, user).count()
    document_check_count = _document_check_queue_qs(branch_base, user).count()
    cards: list[TaskDetailCard] = []

    if office_view:
        total_open = branch_base.exclude(
            status__in=Task.CLOSED_STATUSES
        ).count()
        submitted = branch_base.filter(status=Task.STATUS_SUBMITTED).count()
        cards.extend(
            [
                TaskDetailCard(
                    key="total_open",
                    label="Open tasks",
                    count=total_open,
                    list_url=task_list_url("task_list", open_tasks=True),
                ),
                TaskDetailCard(
                    key="submitted",
                    label="Submitted",
                    count=submitted,
                    list_url=task_list_url("task_list", status=Task.STATUS_SUBMITTED),
                ),
            ]
        )

    cards.extend(
        [
            TaskDetailCard(
                key="my_open",
                label="My open",
                count=my_open,
                list_url=task_list_url("task_my_list"),
            ),
            TaskDetailCard(
                key="my_submitted",
                label="My submitted",
                count=my_submitted,
                list_url=task_list_url("task_my_list", status=Task.STATUS_SUBMITTED),
            ),
        ]
    )
    if office_view or verify_count or user.has_perm("tasks.verify_task"):
        cards.append(
            TaskDetailCard(
                key="verify_queue",
                label="My verify queue",
                count=verify_count,
                list_url=reverse("task_verify_queue"),
            )
        )
    if office_view or document_check_count or user.has_perm("tasks.check_documents"):
        cards.append(
            TaskDetailCard(
                key="document_check_queue",
                label="My document check queue",
                count=document_check_count,
                list_url=reverse("task_document_check_queue"),
            )
        )
    return cards


def build_task_dashboard_context(user) -> dict | None:
    """Task summary for the main dashboard (None if not signed in)."""
    if not user.is_authenticated:
        return None

    from .listing import tasks_queryset_for_user

    today = timezone.localdate()
    office_view = user.is_superuser or user.has_perm("tasks.view_task")
    branch_base = tasks_queryset_for_user(user)
    due_qs = branch_base if office_view else (
        branch_base.filter(assignments__user=user)
        .exclude(status=Task.STATUS_PENDING_ASSIGNMENT)
        .distinct()
    )
    list_route = "task_list" if office_view else "task_my_list"
    detail_cards = _task_detail_cards(user, office_view=office_view, branch_base=branch_base)
    task_counts = {card.key: card.count for card in detail_cards}

    return {
        "task_dashboard_office_view": office_view,
        "task_counts": task_counts,
        "task_detail_cards": detail_cards,
        "task_due_buckets": task_due_buckets(due_qs, today=today, list_route=list_route),
        "task_summary_today": today,
    }
