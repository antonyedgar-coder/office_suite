from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .checklist import copy_checklist_to_task
from .client_type_rules import validate_submit_for_client_type
from .models import (
    Task,
    TaskActivity,
    TaskAssignment,
    TaskEnrollmentAssignee,
    TaskMaster,
    TaskNotification,
    TaskRecurrenceEnrollment,
)
from .client_labels import format_client_name_pan, format_task_client_suffix
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
    meta = metadata or {}
    act = TaskActivity.objects.create(
        task=task,
        user=user,
        activity_type=activity_type,
        message=message,
        old_status=old_status or "",
        new_status=new_status or "",
        metadata=meta,
    )
    try:
        from masters.client_activity import log_task_client_activity

        log_task_client_activity(
            task=task,
            user=user,
            activity_type=activity_type,
            message=message,
            old_status=old_status or "",
            new_status=new_status or "",
            metadata=meta,
        )
    except ImportError:
        pass
    return act


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
        names = _assignee_names(assignee_ids)
        if not old_ids:
            assign_msg = f"Task assigned to {names}."
        else:
            assign_msg = f"Users updated to {names}."
        _log_activity(
            task,
            actor,
            TaskActivity.TYPE_ASSIGNED,
            message=assign_msg,
            metadata={"old_assignee_ids": sorted(old_ids), "new_assignee_ids": sorted(assignee_ids)},
        )


def resolve_task_billing(*, master: TaskMaster, is_billable=None, fees_amount=None):
    billable = False if is_billable is None else bool(is_billable)
    fees = fees_amount
    if fees is None and billable:
        fees = master.default_fees_amount
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
    elif new_status == Task.STATUS_VERIFIED:
        task.approved_at = now
        task.approved_by = user
        update_fields.extend(["approved_at", "approved_by"])
    elif new_status == Task.STATUS_COMPLETE:
        task.completed_at = now
        task.completed_by = user
        update_fields.extend(["completed_at", "completed_by"])
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
    document_checker,
    created_by,
    period_key: str | None = None,
    period_type: str = "",
    enrollment: TaskRecurrenceEnrollment | None = None,
    auto_created: bool = False,
    due_date=None,
    is_billable=None,
    fees_amount=None,
) -> Task:
    if not master.is_active or master.archived_at is not None:
        raise ValidationError(
            "This task master is inactive and cannot be used to create new tasks."
        )
    started = enrollment.started_at if enrollment else timezone.localdate()
    pk = period_key or first_period_key(master, started)
    if due_date is None:
        _, due_date = compute_create_due_dates(master, pk, started)

    billable, fees = resolve_task_billing(
        master=master,
        is_billable=is_billable,
        fees_amount=fees_amount,
    )

    needs_assignment_approval = not auto_created
    initial_status = (
        Task.STATUS_PENDING_ASSIGNMENT if needs_assignment_approval else Task.STATUS_ASSIGNED
    )

    task = Task.objects.create(
        client=client,
        task_master=master,
        enrollment=enrollment,
        title=master.name,
        status=initial_status,
        priority=master.default_priority,
        due_date=due_date,
        verifier=verifier,
        document_checker=document_checker,
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
        message=(
            f"Task created; users: {names} (awaiting verifier approval)."
            if needs_assignment_approval
            else f"Task created; users: {names}."
        )
        + (" (auto)" if auto_created else ""),
        new_status=task.status,
        metadata={
            "assignee_ids": ids,
            "verifier_id": verifier.pk,
            "document_checker_id": document_checker.pk,
        },
    )
    if needs_assignment_approval:
        notify_user(
            verifier,
            f"Approve task assignment: {task.display_title} — {format_client_name_pan(client)}",
            kind=TaskNotification.KIND_ASSIGNMENT_APPROVAL,
            link=f"/tasks/{task.pk}/",
            task=task,
        )
    else:
        for u in assignee_users:
            notify_user(
                u,
                f"You were assigned: {task.display_title} — {format_client_name_pan(client)}",
                kind=TaskNotification.KIND_ASSIGNED,
                link=f"/tasks/{task.pk}/",
                task=task,
            )
    return task


@transaction.atomic
def approve_task_assignment(task: Task, user, message: str = "") -> Task:
    if task.verifier_id != user.pk and not user.is_superuser:
        raise ValidationError("Only the designated verifier can approve this assignment.")
    if task.status != Task.STATUS_PENDING_ASSIGNMENT:
        raise ValidationError("This task is not awaiting assignment approval.")

    transition_task_status(task, Task.STATUS_ASSIGNED, user=user, message=message or "Assignment approved.")
    client_label = format_task_client_suffix(task)
    for assignment in task.assignments.select_related("user"):
        notify_user(
            assignment.user,
            f"You were assigned: {task.display_title} — {client_label}",
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
    document_checker,
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
            "document_checker": document_checker,
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
    enrollment.document_checker = document_checker
    enrollment.save(update_fields=["verifier", "document_checker", "updated_at"])
    return enrollment


def assignees_active(assignee_users) -> bool:
    return all(getattr(u, "is_active", True) for u in assignee_users)


@transaction.atomic
def submit_task(task: Task, user) -> Task:
    if not hasattr(task, "client") or not hasattr(task, "task_master"):
        task = Task.objects.select_related("client", "task_master", "document_checker").get(pk=task.pk)
    if task.status == Task.STATUS_DOCUMENT_REWORK:
        return resubmit_for_document_check(task, user)
    validate_submit_for_client_type(task)
    transition_task_status(task, Task.STATUS_SUBMITTED, user=user)
    notify_user(
        task.verifier,
        f"Task submitted for verification: {task.display_title} — {format_task_client_suffix(task)}",
        kind=TaskNotification.KIND_VERIFY,
        link=f"/tasks/{task.pk}/",
        task=task,
    )
    return task


@transaction.atomic
def resubmit_for_document_check(task: Task, user, message: str = "") -> Task:
    if task.status != Task.STATUS_DOCUMENT_REWORK:
        raise ValidationError("This task is not awaiting document correction.")
    transition_task_status(
        task,
        Task.STATUS_VERIFIED,
        user=user,
        message=message or "Resubmitted for document check.",
    )
    now = timezone.now()
    task.submitted_at = now
    task.submitted_by = user
    task.save(update_fields=["submitted_at", "submitted_by", "updated_at"])
    notify_user(
        task.document_checker,
        f"Document check (resubmitted): {task.display_title} — {format_task_client_suffix(task)}",
        kind=TaskNotification.KIND_DOCUMENT_CHECK,
        link=f"/tasks/{task.pk}/",
        task=task,
    )
    return task


@transaction.atomic
def send_back_for_document_correction(task: Task, user, message: str = "") -> Task:
    if task.document_checker_id != user.pk and not user.is_superuser:
        raise ValidationError("Only the designated document checker can send this task back.")
    if task.status != Task.STATUS_VERIFIED:
        raise ValidationError("Only verified tasks can be sent back for document correction.")
    transition_task_status(
        task,
        Task.STATUS_DOCUMENT_REWORK,
        user=user,
        message=message or "Sent back for document correction.",
    )
    for a in task.assignments.select_related("user"):
        notify_user(
            a.user,
            f"Documents need correction: {task.display_title} — {format_task_client_suffix(task)}",
            kind=TaskNotification.KIND_REWORK,
            link=f"/tasks/{task.pk}/",
            task=task,
        )
    return task


@transaction.atomic
def verify_task(task: Task, user, message: str = "") -> Task:
    if task.verifier_id != user.pk and not user.is_superuser:
        raise ValidationError("Only the designated verifier can verify this task.")
    if not hasattr(task, "client") or not hasattr(task, "task_master"):
        task = Task.objects.select_related("client", "task_master", "document_checker").get(pk=task.pk)
    if (getattr(task.client, "client_type", None) or "").strip() == "New Client":
        raise ValidationError('New Client tasks cannot be verified.')
    transition_task_status(task, Task.STATUS_VERIFIED, user=user, message=message or "Task verified.")
    notify_user(
        task.document_checker,
        f"Document check required: {task.display_title} — {format_task_client_suffix(task)}",
        kind=TaskNotification.KIND_DOCUMENT_CHECK,
        link=f"/tasks/{task.pk}/",
        task=task,
    )
    for a in task.assignments.select_related("user"):
        notify_user(
            a.user,
            f"Task verified: {task.display_title} — {format_task_client_suffix(task)}",
            kind=TaskNotification.KIND_APPROVED,
            link=f"/tasks/{task.pk}/",
            task=task,
        )
    if task.created_by_id:
        notify_user(
            task.created_by,
            f"Task verified: {task.display_title} — {format_task_client_suffix(task)}",
            kind=TaskNotification.KIND_APPROVED,
            link=f"/tasks/{task.pk}/",
            task=task,
        )
    return task


@transaction.atomic
def complete_task(task: Task, user, message: str = "") -> Task:
    if task.document_checker_id != user.pk and not user.is_superuser:
        raise ValidationError("Only the designated document checker can mark this task complete.")
    if task.status != Task.STATUS_VERIFIED:
        raise ValidationError("Task must be verified before document checking can be completed.")
    if not hasattr(task, "client") or not hasattr(task, "task_master"):
        task = Task.objects.select_related("client", "task_master", "document_checker").get(pk=task.pk)
    if (getattr(task.client, "client_type", None) or "").strip() == "New Client":
        raise ValidationError("New Client tasks cannot be marked complete.")
    transition_task_status(task, Task.STATUS_COMPLETE, user=user, message=message or "Document check complete.")
    for a in task.assignments.select_related("user"):
        notify_user(
            a.user,
            f"Task complete: {task.display_title} — {format_task_client_suffix(task)}",
            kind=TaskNotification.KIND_APPROVED,
            link=f"/tasks/{task.pk}/",
            task=task,
        )
    if task.created_by_id:
        notify_user(
            task.created_by,
            f"Task complete: {task.display_title} — {format_task_client_suffix(task)}",
            kind=TaskNotification.KIND_APPROVED,
            link=f"/tasks/{task.pk}/",
            task=task,
        )
    if task.verifier_id and task.verifier_id != user.pk:
        notify_user(
            task.verifier,
            f"Task complete: {task.display_title} — {format_task_client_suffix(task)}",
            kind=TaskNotification.KIND_APPROVED,
            link=f"/tasks/{task.pk}/",
            task=task,
        )
    return task


def approve_task(task: Task, user, message: str = "") -> Task:
    """Backward-compatible alias for verify_task."""
    return verify_task(task, user, message=message)


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
    if task.status not in (
        Task.STATUS_CANCELLED,
        Task.STATUS_ASSIGNED,
        Task.STATUS_PENDING_ASSIGNMENT,
    ):
        raise ValidationError("Only pending or cancelled tasks can be deleted.")
    task.delete()


@transaction.atomic
def rework_task(task: Task, user, message: str = "") -> Task:
    transition_task_status(task, Task.STATUS_REWORK, user=user, message=message)
    for a in task.assignments.select_related("user"):
        notify_user(
            a.user,
            f"Task sent for rework: {task.display_title} — {format_task_client_suffix(task)}",
            kind=TaskNotification.KIND_REWORK,
            link=f"/tasks/{task.pk}/",
            task=task,
        )
    return task


EDITABLE_TEAM_STATUSES = frozenset(
    {
        Task.STATUS_PENDING_ASSIGNMENT,
        Task.STATUS_ASSIGNED,
        Task.STATUS_SUBMITTED,
        Task.STATUS_VERIFIED,
        Task.STATUS_REWORK,
        Task.STATUS_DOCUMENT_REWORK,
    }
)


def task_team_is_editable(task: Task) -> bool:
    return task.status in EDITABLE_TEAM_STATUSES


@transaction.atomic
def update_task_team(
    task: Task,
    *,
    assignee_users,
    verifier,
    document_checker,
    due_date,
    priority,
    actor,
) -> Task:
    if not task_team_is_editable(task):
        raise ValidationError("This task cannot be edited in its current status.")

    old_verifier_id = task.verifier_id
    old_doc_id = task.document_checker_id
    old_assignee_ids = set(task.assignments.values_list("user_id", flat=True))
    new_assignee_ids = {u.pk for u in assignee_users}

    task.verifier = verifier
    task.document_checker = document_checker
    task.due_date = due_date
    task.priority = priority
    task.save(update_fields=["verifier", "document_checker", "due_date", "priority", "updated_at"])

    changes: list[str] = []
    if old_verifier_id != verifier.pk:
        changes.append(f"Verifier set to {user_person_name(verifier)}.")
    if old_doc_id != document_checker.pk:
        changes.append(f"Document checker set to {user_person_name(document_checker)}.")
    if changes:
        _log_activity(task, actor, TaskActivity.TYPE_REMARK, message=" ".join(changes))

    new_ids = [u.pk for u in assignee_users]
    _set_assignees(task, new_ids, actor=actor)

    if task.enrollment_id:
        enrollment = task.enrollment
        enrollment.verifier = verifier
        enrollment.document_checker = document_checker
        enrollment.save(update_fields=["verifier", "document_checker", "updated_at"])
        TaskEnrollmentAssignee.objects.filter(enrollment=enrollment).delete()
        for u in assignee_users:
            TaskEnrollmentAssignee.objects.create(enrollment=enrollment, user=u)
        sibling_qs = Task.objects.filter(
            enrollment=enrollment,
            status__in=(
                Task.STATUS_ASSIGNED,
                Task.STATUS_REWORK,
                Task.STATUS_DOCUMENT_REWORK,
            ),
        ).exclude(pk=task.pk)
        for sibling in sibling_qs:
            _set_assignees(sibling, new_ids, actor=actor)

    added_assignees = new_assignee_ids - old_assignee_ids
    if added_assignees and task.status != Task.STATUS_PENDING_ASSIGNMENT:
        for uid in added_assignees:
            u = User.objects.get(pk=uid)
            notify_user(
                u,
                f"You were assigned: {task.display_title} — {format_task_client_suffix(task)}",
                kind=TaskNotification.KIND_ASSIGNED,
                link=f"/tasks/{task.pk}/",
                task=task,
            )

    if old_verifier_id != verifier.pk:
        if task.status == Task.STATUS_PENDING_ASSIGNMENT:
            notify_user(
                verifier,
                f"Approve task assignment: {task.display_title} — {format_task_client_suffix(task)}",
                kind=TaskNotification.KIND_ASSIGNMENT_APPROVAL,
                link=f"/tasks/{task.pk}/",
                task=task,
            )
        elif task.status == Task.STATUS_SUBMITTED:
            notify_user(
                verifier,
                f"Task submitted for verification: {task.display_title} — {format_task_client_suffix(task)}",
                kind=TaskNotification.KIND_VERIFY,
                link=f"/tasks/{task.pk}/",
                task=task,
            )

    if old_doc_id != document_checker.pk and task.status == Task.STATUS_VERIFIED:
        notify_user(
            document_checker,
            f"Document check required: {task.display_title} — {format_task_client_suffix(task)}",
            kind=TaskNotification.KIND_DOCUMENT_CHECK,
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
        status__in=[Task.STATUS_ASSIGNED, Task.STATUS_REWORK, Task.STATUS_DOCUMENT_REWORK],
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
    if not master.is_active or master.archived_at is not None:
        return None
    if not master.is_recurring or not enrollment.is_active:
        return None
    if enrollment_is_paused(enrollment, today):
        return None

    assignees = list(enrollment.assignees.all())
    if not assignees or not assignees_active(assignees):
        msg = (
            f"Recurring task skipped (inactive assignee): {master.name} — "
            f"{format_client_name_pan(enrollment.client)}"
        )
        notify_admins(msg, link="/tasks/")
        return None

    ok, period_key = should_create_today(
        master, today, enrollment.started_at, client=enrollment.client
    )
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
        document_checker=enrollment.document_checker,
        created_by=enrollment.created_by,
        period_key=period_key,
        enrollment=enrollment,
        auto_created=True,
        due_date=due_date,
    )
