"""Delete local / test data in dependency-safe order."""

from __future__ import annotations

from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.db import transaction

from core.feature_flags import task_module_enabled

User = get_user_model()


@dataclass
class WipeOptions:
    mis: bool = False
    director_mapping: bool = False
    dir3kyc: bool = False
    clients: bool = False
    client_groups: bool = False
    tasks: bool = False
    activity_log: bool = False
    delete_users: bool = False
    users_keep_ids: set[int] = field(default_factory=set)


def count_local_data() -> dict[str, int]:
    from dirkyc.models import Dir3Kyc
    from masters.models import Client, ClientGroup, DirectorMapping
    from mis.models import ExpenseDetail, FeesDetail, Receipt

    counts = {
        "clients": Client.objects.count(),
        "client_groups": ClientGroup.objects.count(),
        "fees": FeesDetail.objects.count(),
        "receipts": Receipt.objects.count(),
        "expenses": ExpenseDetail.objects.count(),
        "director_mappings": DirectorMapping.objects.count(),
        "dir3kyc": Dir3Kyc.objects.count(),
        "users": User.objects.count(),
        "employees": 0,
    }
    try:
        from core.models import Employee

        counts["employees"] = Employee.objects.count()
    except Exception:
        pass
    try:
        from core.models import ActivityLog

        counts["activity_log"] = ActivityLog.objects.count()
    except Exception:
        counts["activity_log"] = 0

    if task_module_enabled():
        from tasks.models import (
            Task,
            TaskGroup,
            TaskMaster,
            TaskNotification,
            TaskRecurrenceEnrollment,
        )

        counts.update(
            {
                "tasks": Task.objects.count(),
                "task_masters": TaskMaster.objects.count(),
                "task_groups": TaskGroup.objects.count(),
                "task_notifications": TaskNotification.objects.count(),
                "task_enrollments": TaskRecurrenceEnrollment.objects.count(),
            }
        )
    else:
        counts.update(
            {
                "tasks": 0,
                "task_masters": 0,
                "task_groups": 0,
                "task_notifications": 0,
                "task_enrollments": 0,
            }
        )
    return counts


def _delete_tasks() -> dict[str, int]:
    if not task_module_enabled():
        return {}
    from tasks.models import (
        Task,
        TaskActivity,
        TaskAssignment,
        TaskChecklistItem,
        TaskEnrollmentAssignee,
        TaskGroup,
        TaskMaster,
        TaskMasterChecklistItem,
        TaskNotification,
        TaskRecurrenceEnrollment,
    )

    out: dict[str, int] = {}
    out["task_notifications"] = TaskNotification.objects.all().delete()[0]
    out["task_activities"] = TaskActivity.objects.all().delete()[0]
    out["task_checklist_items"] = TaskChecklistItem.objects.all().delete()[0]
    out["task_assignments"] = TaskAssignment.objects.all().delete()[0]
    out["tasks"] = Task.objects.all().delete()[0]
    out["task_enrollment_assignees"] = TaskEnrollmentAssignee.objects.all().delete()[0]
    out["task_enrollments"] = TaskRecurrenceEnrollment.objects.all().delete()[0]
    out["task_master_checklist"] = TaskMasterChecklistItem.objects.all().delete()[0]
    out["task_masters"] = TaskMaster.objects.all().delete()[0]
    out["task_groups"] = TaskGroup.objects.all().delete()[0]
    return out


@transaction.atomic
def wipe_local_data(options: WipeOptions) -> dict[str, int]:
    """
    Delete selected datasets. When clients=True, dependent MIS/KYC/mapping/tasks
    are forced on so PROTECT FKs do not block deletes.
    """
    if options.clients:
        options.mis = True
        options.director_mapping = True
        options.dir3kyc = True
        options.tasks = True

    deleted: dict[str, int] = {}

    if options.tasks:
        deleted.update(_delete_tasks())

    if options.mis:
        from mis.models import ExpenseDetail, FeesDetail, Receipt

        deleted["fees"] = FeesDetail.objects.all().delete()[0]
        deleted["receipts"] = Receipt.objects.all().delete()[0]
        deleted["expenses"] = ExpenseDetail.objects.all().delete()[0]

    if options.director_mapping:
        from masters.models import DirectorMapping

        deleted["director_mappings"] = DirectorMapping.objects.all().delete()[0]

    if options.dir3kyc:
        from dirkyc.models import Dir3Kyc

        deleted["dir3kyc"] = Dir3Kyc.objects.all().delete()[0]

    if options.clients:
        from masters.models import Client, ClientSequence

        deleted["client_sequences"] = ClientSequence.objects.all().delete()[0]
        deleted["clients"] = Client.objects.all().delete()[0]

    if options.client_groups:
        from masters.models import ClientGroup, GroupSequence

        deleted["group_sequences"] = GroupSequence.objects.all().delete()[0]
        deleted["client_groups"] = ClientGroup.objects.all().delete()[0]

    if options.activity_log:
        from core.models import ActivityLog

        deleted["activity_log"] = ActivityLog.objects.all().delete()[0]

    if options.delete_users:
        from core.models import Employee

        qs = User.objects.all()
        if options.users_keep_ids:
            qs = qs.exclude(pk__in=options.users_keep_ids)
        user_ids = list(qs.values_list("pk", flat=True))
        deleted["employees"] = Employee.objects.filter(user_id__in=user_ids).delete()[0]
        deleted["users"] = qs.delete()[0]

    return deleted


def wipe_all_local_data(*, keep_user_ids: set[int]) -> dict[str, int]:
    """Convenience: wipe tasks, clients, groups, MIS, KYC, mappings, activity log, other users."""
    return wipe_local_data(
        WipeOptions(
            mis=True,
            director_mapping=True,
            dir3kyc=True,
            clients=True,
            client_groups=True,
            tasks=True,
            activity_log=True,
            delete_users=True,
            users_keep_ids=keep_user_ids,
        )
    )
