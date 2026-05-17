from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .checklist import copy_checklist_to_task
from .models import (
    Task,
    TaskActivity,
    TaskAssignment,
    TaskEnrollmentAssignee,
    TaskMaster,
    TaskNotification,
    TaskRecurrenceEnrollment,
)
from .notifications import notify_admin_group, notify_user
from .recurrence import compute_create_due_dates, first_period_key, should_create_today
from .transitions import validate_transition
from .user_labels import user_person_name

User = get_user_model()


def _log_activity(
    task,
    user,
    activity_type,
    message="",
    old_status="",
    new_status="",
    metadata=None,
):
    return TaskActivity.objects.create(
        task=task,
        user=user,
        activity_type=activity_type,
        message=message,
        old_status=old_status or "",
        new_status=new_status or "",
        metadata=metadata or {},
    )


def _assignee_names(user_ids: list[int]) -> str:
    if not user_ids:
        return "—"
    users = User.objects.filter(pk__in=user_ids).select_related("employee_profile")
    return ", ".join(user_person_name(u) for u in users)


def _set_assignees(task: Task, assignee_ids: list[int], *, actor=None):
    old_ids = list(task.assignments.values_list("user_id", flat=True))
    old_set = set(old_ids)
    new_set = set(assignee_ids)
    if old_set == new_set:
        return

    TaskAssignment.objects.filter(task=task).delete()
    now = timezone.now()
    for uid in assignee_ids:
        TaskAssignment.objects.create(
            task=task,
            user_id=uid,
            assigned_at=now,
            assigned_by=actor,
        )

    if actor:
        _log_activity(
            task,
            actor,
            TaskActivity.TYPE_ASSIGNED,
            message=f"Users updated to {_assignee_names(assignee_ids)}.",
            metadata={"old_assignee_ids": sorted(old_ids), "new_assignee_ids": sorted(assignee_ids)},
        )


def resolve_task_billing(*, master: TaskMaster, is_billable=None, fees_amount=None):
    billable = master.default_is_billable if is_billable is None else bool(is_billable)
    fees = master.default_fees_amount if fees_amount is None else fees_amount
    if not billable:
        fees = None
    return billable, fees


@transaction.atomic
def transition_task_status(task: Task, new_status: str, *, user, message: str = "") -> Task:
    validate_transition(task, new_status)
    old = task.status
    if old == new_status:
        return task

    now = timezone.now()
    task.status = new_status
    update_fields = ["status", "updated_at"]

    if new_status == Task.STATUS_SUBMITTED:
        if not task.started_at:
            task.started_at = now
            update_fields.append("started_at")
        task.submitted_at = now
        task.submitted_by = user
        update_fields.extend(["submitted_at", "submitted_by"])
    elif new_status == Task.STATUS_APPROVED:
        task.approved_at = now
        task.approved_by = user
        update_fields.extend(["approved_at", "approved_by"])
    elif new_status == Task.STATUS_CANCELLED:
        task.cancelled_at = now
        task.cancelled_by = user
        update_fields.extend(["cancelled_at", "cancelled_by"])

    task.save(update_fields=update_fields)
    _log_activity(
        task,
        user,
        TaskActivity.TYPE_STATUS,
        message=message,
        old_status=old,
        new_status=new_status,
    )
    return task


@transaction.atomic
def create_task_from_master(
    *,
    master: TaskMaster,
    client,
    assignee_users,
    verifier,
    created_by,
    period_key: str | None = None,
    period_type: str = "",
    enrollment: TaskRecurrenceEnrollment | None = None,
    auto_created: bool = False,
    due_date=None,
    is_billable=None,
    fees_amount=None,
) -> Task:
    started = enrollment.started_at if enrollment else timezone.localdate()
    pk = period_key or first_period_key(master, started)
    if due_date is None:
        _, due_date = compute_create_due_dates(master, pk, started)

    billable, fees = resolve_task_billing(
        master=master,
        is_billable=is_billable,
        fees_amount=fees_amount,
    )

    task = Task.objects.create(
        client=client,
        task_master=master,
        enrollment=enrollment,
        title=master.name,
        status=Task.STATUS_ASSIGNED,
        priority=master.default_priority,
        due_date=due_date,
        verifier=verifier,
        created_by=created_by,
        period_key=pk,
        period_type=period_type or "",
        auto_created=auto_created,
        is_billable=billable,
        fees_amount=fees,
        currency=master.default_currency or TaskMaster.CURRENCY_INR,
    )
    copy_checklist_to_task(task, master)
    ids = [u.pk for u in assignee_users]
    _set_assignees(task, ids, actor=created_by)
    names = _assignee_names(ids)
    _log_activity(
        task,
        created_by,
        TaskActivity.TYPE_CREATED,
        message=f"Task created; users: {names}."
        + (" (auto)" if auto_created else ""),
        new_status=task.status,
        metadata={"assignee_ids": ids, "verifier_id": verifier.pk},
    )
    for u in assignee_users:
        notify_user(
            u,
            f"You were assigned: {task.display_title} — {client.client_id}",
            kind=TaskNotification.KIND_ASSIGNED,
            link=f"/tasks/{task.pk}/",
            task=task,
        )
    return task


@transaction.atomic
def start_enrollment_if_recurring(
    *,
    master: TaskMaster,
    client,
    assignee_users,
    verifier,
    created_by,
    started_at=None,
) -> TaskRecurrenceEnrollment | None:
    if not master.is_recurring:
        return None
    started = started_at or timezone.localdate()
    enrollment, created = TaskRecurrenceEnrollment.objects.get_or_create(
        client=client,
        task_master=master,
        defaults={
            "verifier": verifier,
            "started_at": started,
            "created_by": created_by,
            "is_active": True,
        },
    )
    if not created and not enrollment.is_active:
        enrollment.is_active = True
        enrollment.save(update_fields=["is_active", "updated_at"])
    TaskEnrollmentAssignee.objects.filter(enrollment=enrollment).delete()
    for u in assignee_users:
        TaskEnrollmentAssignee.objects.create(enrollment=enrollment, user=u)
    enrollment.verifier = verifier
    enrollment.save(update_fields=["verifier", "updated_at"])
    return enrollment


def assignees_active(assignee_users) -> bool:
    return all(getattr(u, "is_active", True) for u in assignee_users)


@transaction.atomic
def submit_task(task: Task, user) -> Task:
    transition_task_status(task, Task.STATUS_SUBMITTED, user=user)
    notify_user(
        task.verifier,
        f"Task submitted for verification: {task.display_title} — {task.client_id}",
        kind=TaskNotification.KIND_VERIFY,
        link=f"/tasks/{task.pk}/",
        task=task,
    )
    return task


@transaction.atomic
def approve_task(task: Task, user, message: str = "") -> Task:
    transition_task_status(task, Task.STATUS_APPROVED, user=user, message=message)
    for a in task.assignments.select_related("user"):
        notify_user(
            a.user,
            f"Task approved: {task.display_title} — {task.client_id}",
            kind=TaskNotification.KIND_APPROVED,
            link=f"/tasks/{task.pk}/",
            task=task,
        )
    if task.created_by_id:
        notify_user(
            task.created_by,
            f"Task approved: {task.display_title} — {task.client_id}",
            kind=TaskNotification.KIND_APPROVED,
            link=f"/tasks/{task.pk}/",
            task=task,
        )
    return task


@transaction.atomic
def cancel_task(task: Task, user, message: str = "") -> Task:
    """Cancel task and stop recurring enrollment so no further auto-tasks are created."""
    transition_task_status(
        task,
        Task.STATUS_CANCELLED,
        user=user,
        message=message or "Task cancelled.",
    )
    if task.enrollment_id:
        enrollment = task.enrollment
        enrollment.is_active = False
        enrollment.is_paused = True
        enrollment.save(update_fields=["is_active", "is_paused", "updated_at"])
        _log_activity(
            task,
            user,
            TaskActivity.TYPE_ENROLLMENT,
            message="Recurring schedule stopped because this task was cancelled. "
            "Create a new task to start recurrence again.",
        )
    return task


@transaction.atomic
def delete_task(task: Task, user) -> None:
    """Hard-delete a pending or cancelled task."""
    if task.status not in (Task.STATUS_CANCELLED, Task.STATUS_ASSIGNED):
        raise ValidationError("Only pending or cancelled tasks can be deleted.")
    task.delete()


@transaction.atomic
def rework_task(task: Task, user, message: str = "") -> Task:
    transition_task_status(task, Task.STATUS_REWORK, user=user, message=message)
    for a in task.assignments.select_related("user"):
        notify_user(
            a.user,
            f"Task sent for rework: {task.display_title} — {task.client_id}",
            kind=TaskNotification.KIND_REWORK,
            link=f"/tasks/{task.pk}/",
            task=task,
        )
    return task


@transaction.atomic
def change_enrollment_assignees(enrollment: TaskRecurrenceEnrollment, assignee_users, *, actor) -> None:
    TaskEnrollmentAssignee.objects.filter(enrollment=enrollment).delete()
    for u in assignee_users:
        TaskEnrollmentAssignee.objects.create(enrollment=enrollment, user=u)
    open_tasks = Task.objects.filter(
        enrollment=enrollment,
        status__in=[Task.STATUS_ASSIGNED, Task.STATUS_REWORK],
    )
    for t in open_tasks:
        _set_assignees(t, [u.pk for u in assignee_users], actor=actor)


def notify_admins(message: str, *, link: str = "", task: Task | None = None):
    notify_admin_group(message, link=link, task=task)


def enrollment_is_paused(enrollment: TaskRecurrenceEnrollment, today=None) -> bool:
    today = today or timezone.localdate()
    if enrollment.is_paused:
        if enrollment.paused_until and today > enrollment.paused_until:
            return False
        return True
    return False


def try_create_recurring_for_enrollment(enrollment: TaskRecurrenceEnrollment, today=None) -> Task | None:
    today = today or timezone.localdate()
    master = enrollment.task_master
    if not master.is_recurring or not enrollment.is_active:
        return None
    if enrollment_is_paused(enrollment, today):
        return None

    assignees = list(enrollment.assignees.all())
    if not assignees or not assignees_active(assignees):
        msg = (
            f"Recurring task skipped (inactive assignee): {master.name} — "
            f"{enrollment.client_id}"
        )
        notify_admins(msg, link="/tasks/")
        return None

    ok, period_key = should_create_today(master, today, enrollment.started_at)
    if not ok:
        return None

    if Task.objects.filter(
        client=enrollment.client,
        task_master=master,
        period_key=period_key,
    ).exists():
        return None

    _, due_date = compute_create_due_dates(master, period_key, enrollment.started_at)
    return create_task_from_master(
        master=master,
        client=enrollment.client,
        assignee_users=assignees,
        verifier=enrollment.verifier,
        created_by=enrollment.created_by,
        period_key=period_key,
        enrollment=enrollment,
        auto_created=True,
        due_date=due_date,
    )
