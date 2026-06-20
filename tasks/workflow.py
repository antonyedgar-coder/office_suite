"""Task workflow rules — verifier / document checker optional per task snapshot."""

from __future__ import annotations

from django.core.exceptions import ValidationError

from .models import Task

WORKFLOW_SIMPLE = "simple"
WORKFLOW_VERIFY_ONLY = "verify_only"
WORKFLOW_DOC_ONLY = "doc_only"
WORKFLOW_FULL = "full"

WORKFLOW_LABELS = {
    WORKFLOW_SIMPLE: "Simple (assignee completes on submit)",
    WORKFLOW_VERIFY_ONLY: "Verify only (verifier completes)",
    WORKFLOW_DOC_ONLY: "Document check only (document checker completes)",
    WORKFLOW_FULL: "Full (verify then document check)",
}


def workflow_kind(*, requires_verifier: bool, requires_document_checker: bool) -> str:
    if requires_verifier and requires_document_checker:
        return WORKFLOW_FULL
    if requires_verifier:
        return WORKFLOW_VERIFY_ONLY
    if requires_document_checker:
        return WORKFLOW_DOC_ONLY
    return WORKFLOW_SIMPLE


def task_workflow_kind(task: Task) -> str:
    return workflow_kind(
        requires_verifier=bool(task.requires_verifier),
        requires_document_checker=bool(task.requires_document_checker),
    )


def workflow_label(task: Task) -> str:
    return WORKFLOW_LABELS.get(task_workflow_kind(task), "Full")


def submit_completes_task(task: Task) -> bool:
    return task_workflow_kind(task) == WORKFLOW_SIMPLE


def verify_completes_task(task: Task) -> bool:
    return task_workflow_kind(task) == WORKFLOW_VERIFY_ONLY


def needs_document_check(task: Task) -> bool:
    return bool(task.requires_document_checker)


def allows_verifier_rework(task: Task) -> bool:
    return bool(task.requires_verifier)


def allows_document_rework(task: Task) -> bool:
    return task_workflow_kind(task) == WORKFLOW_FULL


def document_check_statuses(task: Task) -> frozenset[str]:
    kind = task_workflow_kind(task)
    if kind == WORKFLOW_FULL:
        return frozenset({Task.STATUS_VERIFIED})
    if kind == WORKFLOW_DOC_ONLY:
        return frozenset({Task.STATUS_SUBMITTED})
    return frozenset()


def allowed_transitions(task: Task) -> dict[str, set[str]]:
    kind = task_workflow_kind(task)
    common = {
        Task.STATUS_PENDING_ASSIGNMENT: {Task.STATUS_ASSIGNED, Task.STATUS_CANCELLED},
        Task.STATUS_COMPLETE: set(),
        Task.STATUS_CANCELLED: set(),
        Task.STATUS_DRAFT: {Task.STATUS_SUBMITTED, Task.STATUS_CANCELLED},
        Task.STATUS_IN_PROGRESS: {Task.STATUS_SUBMITTED, Task.STATUS_CANCELLED},
    }

    if kind == WORKFLOW_SIMPLE:
        open_to_complete = {Task.STATUS_ASSIGNED, Task.STATUS_REWORK}
        return {
            **common,
            Task.STATUS_ASSIGNED: {Task.STATUS_COMPLETE, Task.STATUS_CANCELLED},
            Task.STATUS_REWORK: {Task.STATUS_COMPLETE, Task.STATUS_CANCELLED},
        }

    if kind == WORKFLOW_VERIFY_ONLY:
        return {
            **common,
            Task.STATUS_ASSIGNED: {Task.STATUS_SUBMITTED, Task.STATUS_CANCELLED},
            Task.STATUS_REWORK: {Task.STATUS_SUBMITTED, Task.STATUS_CANCELLED},
            Task.STATUS_SUBMITTED: {Task.STATUS_COMPLETE, Task.STATUS_REWORK, Task.STATUS_CANCELLED},
        }

    if kind == WORKFLOW_DOC_ONLY:
        return {
            **common,
            Task.STATUS_ASSIGNED: {Task.STATUS_SUBMITTED, Task.STATUS_CANCELLED},
            Task.STATUS_REWORK: {Task.STATUS_SUBMITTED, Task.STATUS_CANCELLED},
            Task.STATUS_SUBMITTED: {Task.STATUS_COMPLETE, Task.STATUS_CANCELLED},
        }

    # Full workflow
    return {
        **common,
        Task.STATUS_ASSIGNED: {Task.STATUS_SUBMITTED, Task.STATUS_CANCELLED},
        Task.STATUS_REWORK: {Task.STATUS_SUBMITTED, Task.STATUS_CANCELLED},
        Task.STATUS_SUBMITTED: {Task.STATUS_VERIFIED, Task.STATUS_REWORK, Task.STATUS_CANCELLED},
        Task.STATUS_VERIFIED: {Task.STATUS_COMPLETE, Task.STATUS_DOCUMENT_REWORK, Task.STATUS_CANCELLED},
        Task.STATUS_DOCUMENT_REWORK: {Task.STATUS_VERIFIED, Task.STATUS_CANCELLED},
    }


def can_transition(task: Task, new_status: str) -> bool:
    return new_status in allowed_transitions(task).get(task.status, set())


def validate_transition(task: Task, new_status: str) -> None:
    if new_status == task.status:
        return
    if not can_transition(task, new_status):
        raise ValidationError(
            f"Cannot change task status from {task.get_status_display()} to "
            f"{dict(Task.STATUS_CHOICES).get(new_status, new_status)}."
        )


def validate_team_for_workflow(
    *,
    requires_verifier: bool,
    requires_document_checker: bool,
    assignee_users,
    verifier_users,
    document_checker,
) -> None:
    if not assignee_users:
        raise ValidationError("At least one assigned user is required.")
    if requires_verifier and not verifier_users:
        raise ValidationError("At least one verifier is required for this task type.")
    if requires_document_checker and not document_checker:
        raise ValidationError("Document checker is required for this task type.")
    if not requires_verifier and verifier_users:
        raise ValidationError("Verifiers are not used for this task type.")
    if not requires_document_checker and document_checker:
        raise ValidationError("Document checker is not used for this task type.")

    assignee_ids = {u.pk for u in assignee_users}
    if len(assignee_ids) != len(assignee_users):
        raise ValidationError("Each assigned user must be a different person.")
    for v in verifier_users:
        if v.pk in assignee_ids:
            raise ValidationError("A verifier cannot also be an assigned user.")
    if document_checker and document_checker.pk in assignee_ids:
        raise ValidationError("Document checker cannot be one of the assigned users.")
