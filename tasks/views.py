from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.branch_access import approved_clients_for_user
from core.decorators import require_perm

from .forms import TaskCreateForm, TaskGroupForm, TaskMasterForm, TaskRemarkForm, TaskVerifyForm
from .models import Task, TaskActivity, TaskGroup, TaskMaster, TaskNotification
from .export import task_list_csv_response
from .listing import (
    filter_context,
    filters_query_string,
    get_filtered_tasks,
    parse_task_list_filters,
    prepare_task_list_rows,
    tasks_queryset_for_user,
)
from .checklist import master_checklist_labels, toggle_task_checklist_item
from .user_labels import user_person_name
from .services import (
    approve_task,
    create_task_from_master,
    rework_task,
    start_enrollment_if_recurring,
    cancel_task,
    delete_task,
    submit_task,
)


def tasks_for_user(user):
    return tasks_queryset_for_user(user)


def task_detail_queryset(user):
    return tasks_for_user(user)


@require_perm("tasks.view_taskgroup")
def task_group_list(request):
    q = (request.GET.get("q") or "").strip()
    qs = TaskGroup.objects.all()
    if q:
        qs = qs.filter(name__icontains=q)
    return render(request, "tasks/task_group_list.html", {"groups": qs, "q": q})


@require_perm("tasks.add_taskgroup")
def task_group_create(request):
    if request.method == "POST":
        form = TaskGroupForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Task group created.")
            return redirect("task_group_list")
    else:
        form = TaskGroupForm()
    return render(request, "tasks/task_group_form.html", {"form": form, "mode": "create"})


@require_perm("tasks.change_taskgroup")
def task_group_edit(request, pk: int):
    group = get_object_or_404(TaskGroup, pk=pk)
    if request.method == "POST":
        form = TaskGroupForm(request.POST, instance=group)
        if form.is_valid():
            form.save()
            messages.success(request, "Task group updated.")
            return redirect("task_group_list")
    else:
        form = TaskGroupForm(instance=group)
    return render(request, "tasks/task_group_form.html", {"form": form, "mode": "edit", "group": group})


@require_perm("tasks.view_taskmaster")
def task_master_list(request):
    q = (request.GET.get("q") or "").strip()
    group_id = request.GET.get("group")
    qs = TaskMaster.objects.select_related("task_group").order_by("task_group__sort_order", "name")
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    if group_id:
        qs = qs.filter(task_group_id=group_id)
    return render(
        request,
        "tasks/task_master_list.html",
        {
            "masters": qs,
            "q": q,
            "groups": TaskGroup.objects.filter(is_active=True),
            "group_id": group_id,
        },
    )


@require_perm("tasks.add_taskmaster")
def task_master_create(request):
    if request.method == "POST":
        form = TaskMasterForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Task master created.")
            return redirect("task_master_list")
    else:
        form = TaskMasterForm()
    return render(
        request,
        "tasks/task_master_form.html",
        {"form": form, "mode": "create", "recurrence_config": {}, "checklist_labels": []},
    )


@require_perm("tasks.change_taskmaster")
def task_master_edit(request, pk: int):
    master = get_object_or_404(TaskMaster, pk=pk)
    if request.method == "POST":
        form = TaskMasterForm(request.POST, instance=master)
        if form.is_valid():
            form.save()
            messages.success(request, "Task master updated.")
            return redirect("task_master_list")
    else:
        form = TaskMasterForm(instance=master)
    return render(
        request,
        "tasks/task_master_form.html",
        {
            "form": form,
            "mode": "edit",
            "master": master,
            "recurrence_config": master.recurrence_config or {},
            "checklist_labels": master_checklist_labels(master),
        },
    )


def _task_list_context(request, *, list_title, show_new_task, csv_url_name, base_qs=None):
    filters = parse_task_list_filters(request)
    tasks = get_filtered_tasks(request.user, filters, base_qs=base_qs)
    ctx = filter_context(request.user, filters)
    qs = filters_query_string(filters)
    ctx.update(
        {
            "task_rows": prepare_task_list_rows(tasks),
            "list_title": list_title,
            "show_new_task": show_new_task,
            "csv_export_url": reverse(csv_url_name) + (f"?{qs}" if qs else ""),
        }
    )
    return ctx


@require_perm("tasks.view_task")
def task_list(request):
    return render(
        request,
        "tasks/task_list.html",
        _task_list_context(
            request,
            list_title="All tasks",
            show_new_task=True,
            csv_url_name="task_list_csv",
        ),
    )


@require_perm("tasks.view_task")
def task_report(request):
    return render(
        request,
        "tasks/task_report.html",
        _task_list_context(
            request,
            list_title="Task report",
            show_new_task=False,
            csv_url_name="task_report_csv",
        ),
    )


@require_perm("tasks.view_task")
def task_list_csv(request):
    filters = parse_task_list_filters(request)
    return task_list_csv_response(request, request.user, filters, filename="all-tasks.csv")


@require_perm("tasks.view_task")
def task_report_csv(request):
    filters = parse_task_list_filters(request)
    return task_list_csv_response(request, request.user, filters, filename="task-report.csv")


@require_perm("tasks.add_task")
def task_create(request):
    if request.method == "POST":
        form = TaskCreateForm(request.POST, user=request.user)
        if form.is_valid():
            master = form.cleaned_data["task_master"]
            client = form.cleaned_data["client"]
            assignees = list(form.cleaned_data["assignees"])
            verifier = form.cleaned_data["verifier"]
            due_date = form.cleaned_data["due_date"]
            enrollment = start_enrollment_if_recurring(
                master=master,
                client=client,
                assignee_users=assignees,
                verifier=verifier,
                created_by=request.user,
            )
            task = create_task_from_master(
                master=master,
                client=client,
                assignee_users=assignees,
                verifier=verifier,
                created_by=request.user,
                period_key=form.cleaned_data["period_key"],
                period_type=form.cleaned_data.get("period_type") or "",
                enrollment=enrollment,
                due_date=due_date,
                is_billable=form.cleaned_data.get("is_billable"),
                fees_amount=form.cleaned_data.get("fees_amount"),
            )
            if form.cleaned_data.get("priority"):
                task.priority = form.cleaned_data["priority"]
                task.save(update_fields=["priority"])
            messages.success(request, f"Task created: {task.title}")
            return redirect("task_detail", pk=task.pk)
    else:
        form = TaskCreateForm(user=request.user)
    from .user_labels import staff_users_queryset, user_display_label

    staff_users = [
        {"id": u.pk, "label": user_display_label(u)}
        for u in staff_users_queryset()
    ]
    clients = []
    for c in form.fields["client"].queryset:
        pan = (c.pan or "").strip().upper()
        label = f"{c.client_name} — {pan}" if pan else c.client_name
        clients.append({"id": c.pk, "label": label, "search": f"{c.client_name} {pan} {c.pk}".lower()})
    masters_billing = {
        str(m.pk): {
            "is_billable": m.default_is_billable,
            "fees_amount": str(m.default_fees_amount) if m.default_fees_amount is not None else "",
            "default_verifier_id": m.default_verifier_id,
        }
        for m in TaskMaster.objects.filter(is_active=True, archived_at__isnull=True).only(
            "pk", "default_is_billable", "default_fees_amount", "default_verifier_id"
        )
    }
    return render(
        request,
        "tasks/task_create.html",
        {
            "form": form,
            "staff_users_json": staff_users,
            "clients_json": clients,
            "masters_billing_json": masters_billing,
        },
    )


@login_required
def task_detail(request, pk: int):
    task = get_object_or_404(task_detail_queryset(request.user), pk=pk)
    if not (
        request.user.is_superuser
        or request.user.has_perm("tasks.view_task")
        or task.assignments.filter(user=request.user).exists()
        or task.verifier_id == request.user.pk
        or task.created_by_id == request.user.pk
    ):
        raise PermissionDenied

    remark_form = TaskRemarkForm()
    is_assignee = task.assignments.filter(user=request.user).exists()
    is_verifier = task.verifier_id == request.user.pk
    can_submit = is_assignee and task.status in (Task.STATUS_ASSIGNED, Task.STATUS_REWORK)
    can_verify = is_verifier and task.status == Task.STATUS_SUBMITTED
    can_toggle_checklist = is_assignee and task.status in (Task.STATUS_ASSIGNED, Task.STATUS_REWORK)
    can_manage_task = (
        is_assignee
        or task.created_by_id == request.user.pk
        or task.verifier_id == request.user.pk
        or request.user.has_perm("tasks.change_task")
    )
    can_cancel = can_manage_task and task.status in (
        Task.STATUS_ASSIGNED,
        Task.STATUS_REWORK,
        Task.STATUS_SUBMITTED,
    )
    can_delete = request.user.has_perm("tasks.delete_task") and task.status in (
        Task.STATUS_ASSIGNED,
        Task.STATUS_CANCELLED,
    )
    checklist_items = list(task.checklist_items.all())

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "checklist_toggle" and can_toggle_checklist:
            item_id = request.POST.get("item_id")
            if item_id and str(item_id).isdigit():
                done = request.POST.get("done") == "1"
                toggle_task_checklist_item(
                    task=task,
                    item_id=int(item_id),
                    user=request.user,
                    done=done,
                )
            return redirect("task_detail", pk=pk)
        if action == "cancel" and can_cancel:
            cancel_task(task, request.user)
            messages.success(request, "Task cancelled. Recurring schedule stopped for this client and task type.")
            return redirect("task_detail", pk=pk)
        if action == "delete" and can_delete:
            delete_task(task, request.user)
            messages.success(request, "Task deleted.")
            return redirect("task_list")
        if action == "submit" and can_submit:
            submit_task(task, request.user)
            messages.success(request, "Task submitted for verification.")
            return redirect("task_detail", pk=pk)
        if action == "remark":
            remark_form = TaskRemarkForm(request.POST)
            if remark_form.is_valid():
                TaskActivity.objects.create(
                    task=task,
                    user=request.user,
                    activity_type=TaskActivity.TYPE_REMARK,
                    message=remark_form.cleaned_data["message"],
                )
                messages.success(request, "Remark added.")
                return redirect("task_detail", pk=pk)

    activities = task.activities.select_related("user", "user__employee_profile").all()
    assignees = task.assignments.select_related("user", "user__employee_profile").all()
    activity_rows = [
        {
            "activity": act,
            "user_label": user_person_name(act.user) if act.user_id else "",
        }
        for act in activities
    ]
    return render(
        request,
        "tasks/task_detail.html",
        {
            "task": task,
            "activity_rows": activity_rows,
            "assignees": assignees,
            "verifier_label": user_person_name(task.verifier),
            "remark_form": remark_form,
            "can_submit": can_submit,
            "can_verify": can_verify,
            "checklist_items": checklist_items,
            "can_toggle_checklist": can_toggle_checklist,
            "can_cancel": can_cancel,
            "can_delete": can_delete,
        },
    )


@login_required
def task_my_list(request):
    base = tasks_for_user(request.user).filter(assignments__user=request.user)
    filters = parse_task_list_filters(request)
    if not filters.status:
        base = base.exclude(status__in=[Task.STATUS_APPROVED, Task.STATUS_CANCELLED])
    return render(
        request,
        "tasks/task_my_list.html",
        _task_list_context(
            request,
            list_title="My tasks",
            show_new_task=False,
            csv_url_name="task_my_list_csv",
            base_qs=base,
        ),
    )


@login_required
def task_my_list_csv(request):
    base = tasks_for_user(request.user).filter(assignments__user=request.user)
    filters = parse_task_list_filters(request)
    if not filters.status:
        base = base.exclude(status__in=[Task.STATUS_APPROVED, Task.STATUS_CANCELLED])
    return task_list_csv_response(
        request,
        request.user,
        filters,
        base_qs=base,
        filename="my-tasks.csv",
    )


@require_perm("tasks.verify_task")
def task_verify_queue(request):
    base = tasks_for_user(request.user).filter(
        status=Task.STATUS_SUBMITTED,
        verifier=request.user,
    )
    return render(
        request,
        "tasks/task_verify_queue.html",
        _task_list_context(
            request,
            list_title="Verification queue",
            show_new_task=False,
            csv_url_name="task_list_csv",
            base_qs=base,
        ),
    )


@require_perm("tasks.verify_task")
@require_POST
def task_verify_approve(request, pk: int):
    task = get_object_or_404(
        tasks_for_user(request.user).filter(status=Task.STATUS_SUBMITTED, verifier=request.user),
        pk=pk,
    )
    form = TaskVerifyForm(request.POST)
    message = form.cleaned_data["message"] if form.is_valid() else ""
    approve_task(task, request.user, message=message)
    messages.success(request, "Task approved.")
    return redirect("task_verify_queue")


@require_perm("tasks.verify_task")
@require_POST
def task_verify_rework(request, pk: int):
    task = get_object_or_404(
        tasks_for_user(request.user).filter(status=Task.STATUS_SUBMITTED, verifier=request.user),
        pk=pk,
    )
    form = TaskVerifyForm(request.POST)
    message = form.cleaned_data["message"] if form.is_valid() else ""
    rework_task(task, request.user, message=message)
    messages.success(request, "Task sent for rework.")
    return redirect("task_verify_queue")


@require_perm("tasks.view_task")
def task_dashboard(request):
    base = tasks_for_user(request.user)
    counts = {
        "total_open": base.exclude(
            status__in=[Task.STATUS_APPROVED, Task.STATUS_CANCELLED]
        ).count(),
        "submitted": base.filter(status=Task.STATUS_SUBMITTED).count(),
        "my_open": base.filter(assignments__user=request.user)
        .exclude(status__in=[Task.STATUS_APPROVED, Task.STATUS_CANCELLED])
        .distinct()
        .count(),
        "verify_queue": base.filter(status=Task.STATUS_SUBMITTED, verifier=request.user).count(),
    }
    return render(request, "tasks/task_dashboard.html", {"counts": counts})


@login_required
def notification_list(request):
    qs = TaskNotification.objects.filter(user=request.user).select_related("task")[:200]
    return render(request, "tasks/notification_list.html", {"notifications": qs})


@login_required
@require_POST
def notification_mark_read(request, pk: int):
    n = get_object_or_404(TaskNotification, pk=pk, user=request.user)
    n.is_read = True
    n.read_at = timezone.now()
    n.save(update_fields=["is_read", "read_at"])
    if n.link:
        return redirect(n.link)
    return redirect("notification_list")
