import csv
import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.branch_access import approved_clients_for_user
from core.feature_flags import documents_module_enabled, task_module_enabled
from core.decorators import require_perm
from core.embed_popup import allow_embed_popup_frame

from .forms import (
    TaskCreateForm,
    TaskEditForm,
    TaskGroupForm,
    TaskMasterForm,
    TaskRemarkForm,
    TaskVerifyForm,
)
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
from .checklist import (
    checklist_pending_labels,
    checklist_ready_for_submit,
    master_checklist_labels,
    set_task_checklist_item_status,
    toggle_task_checklist_item,
)
from .user_labels import user_person_name
from masters.models import CLIENT_TYPE_NEW_CLIENT, CLIENT_TYPE_ONE_OFF

from .client_type_rules import (
    may_submit_for_client_type,
    none_client_submit_block_message,
)


def _provision_task_master_documents(task_master, *, user=None) -> None:
    if not documents_module_enabled():
        return
    from documents.task_master_folders import provision_task_master_document_folder

    provision_task_master_document_folder(task_master, user=user)


def _sync_task_master_documents(task_master) -> None:
    if not documents_module_enabled():
        return
    from documents.task_master_folders import sync_task_master_folder_name

    sync_task_master_folder_name(task_master)


from .services import (
    approve_task_assignment,
    complete_task,
    create_task_from_master,
    rework_task,
    start_enrollment_if_recurring,
    cancel_task,
    delete_task,
    send_back_for_document_correction,
    submit_task,
    task_team_is_editable,
    update_task_team,
    user_can_approve_task_assignment,
    verify_task,
)


def tasks_for_user(user):
    return tasks_queryset_for_user(user)


def task_detail_queryset(user):
    return tasks_for_user(user)


@require_perm("tasks.view_taskgroup")
def task_group_list(request):
    q = (request.GET.get("q") or "").strip()
    from core.created_by import CREATED_BY_SELECT

    qs = TaskGroup.objects.select_related(*CREATED_BY_SELECT)
    if q:
        qs = qs.filter(name__icontains=q)
    return render(request, "tasks/task_group_list.html", {"groups": qs, "q": q})


@require_perm("tasks.add_taskgroup")
def task_group_create(request):
    from masters.master_request_service import (
        master_request_link_context,
        try_complete_master_request,
    )
    from masters.models import MasterRequest

    if request.method == "POST":
        form = TaskGroupForm(request.POST)
        if form.is_valid():
            from core.created_by import save_form_with_creator

            group = save_form_with_creator(form, request.user)
            mr = try_complete_master_request(
                request,
                group,
                request.POST.get("master_request_id"),
                MasterRequest.TYPE_TASK_GROUP,
            )
            if mr:
                messages.info(request, f"Linked to master request #{mr.pk}. Requester notified.")
            messages.success(request, "Task group created.")
            return redirect("task_group_list")
    else:
        form = TaskGroupForm()
    ctx = {"form": form, "mode": "create"}
    ctx.update(master_request_link_context(request, MasterRequest.TYPE_TASK_GROUP))
    return render(request, "tasks/task_group_form.html", ctx)


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


@login_required
def task_data_manage(request):
    """Superuser: delete all task instances or task masters/groups separately."""
    if not request.user.is_superuser:
        raise PermissionDenied
    if not task_module_enabled():
        raise Http404

    from tasks.task_data_wipe import (
        count_task_module_data,
        delete_task_configuration_only,
        delete_task_instances_only,
    )

    counts = count_task_module_data()

    if request.method == "POST" and request.POST.get("confirm") == "1":
        action = (request.POST.get("action") or "").strip()
        typed = (request.POST.get("confirm_text") or "").strip().upper()
        if typed != "DELETE":
            messages.error(request, 'Type DELETE in the confirmation box to proceed.')
            return redirect("task_data_manage")

        try:
            if action == "instances":
                deleted = delete_task_instances_only()
                n = deleted.get("tasks", 0)
                messages.success(
                    request,
                    f"Deleted {n} task(s) and related rows. Task masters and groups are unchanged — "
                    f"you can bulk-upload tasks again.",
                )
            elif action == "configuration":
                deleted = delete_task_configuration_only()
                messages.success(
                    request,
                    "Deleted task masters and groups. "
                    f"Removed {deleted.get('task_masters', 0)} master(s) and "
                    f"{deleted.get('task_groups', 0)} group(s).",
                )
            else:
                messages.error(request, "Unknown action.")
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if exc.messages else str(exc))
        return redirect("task_data_manage")

    return render(
        request,
        "tasks/task_data_manage.html",
        {
            "counts": counts,
            "bulk_import_url": reverse("task_bulk_import"),
        },
    )


@require_perm("tasks.delete_taskgroup")
def task_group_delete(request, pk: int):
    group = get_object_or_404(TaskGroup, pk=pk)
    if request.method == "POST":
        try:
            group.delete()
        except ProtectedError:
            messages.error(
                request,
                "This task group cannot be deleted while task masters are linked to it. "
                "Remove or reassign those task masters first.",
            )
            return redirect("task_group_edit", pk=pk)
        messages.success(request, "Task group deleted.")
        return redirect("task_group_list")
    return render(request, "tasks/task_group_delete_confirm.html", {"group": group})


@require_perm("tasks.view_taskmaster")
def task_master_list(request):
    q = (request.GET.get("q") or "").strip()
    group_id = request.GET.get("group")
    active_filter = (request.GET.get("active") or "").strip().lower()
    from core.created_by import CREATED_BY_SELECT

    qs = TaskMaster.objects.select_related("task_group", *CREATED_BY_SELECT).order_by(
        "task_group__sort_order", "name"
    )
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    if group_id:
        qs = qs.filter(task_group_id=group_id)
    if active_filter == "yes":
        qs = qs.filter(is_active=True)
    elif active_filter == "no":
        qs = qs.filter(is_active=False)
    return render(
        request,
        "tasks/task_master_list.html",
        {
            "masters": qs,
            "q": q,
            "groups": TaskGroup.objects.filter(is_active=True),
            "group_id": group_id,
            "active_filter": active_filter,
        },
    )


def _task_master_form_context(form, *, mode: str, master: TaskMaster | None = None) -> dict:
    recurrence_config: dict = {}
    checklist_labels: list[str] = []
    if form.is_bound:
        try:
            recurrence_config = json.loads(form.data.get("recurrence_config_json") or "{}")
        except json.JSONDecodeError:
            recurrence_config = {}
        try:
            raw = json.loads(form.data.get("checklist_json") or "[]")
            checklist_labels = [str(x).strip() for x in raw if str(x).strip()] if isinstance(raw, list) else []
        except json.JSONDecodeError:
            checklist_labels = []
    elif master is not None:
        recurrence_config = master.recurrence_config or {}
        checklist_labels = master_checklist_labels(master)
    return {
        "form": form,
        "mode": mode,
        "master": master,
        "recurrence_config": recurrence_config,
        "checklist_labels": checklist_labels,
    }


@allow_embed_popup_frame
@require_perm("tasks.add_taskmaster")
def task_master_create(request):
    from core.embed_popup import (
        PICKER_TASK_MASTER,
        embed_form_template,
        embed_popup_context,
        embed_popup_request,
        render_popup_created,
    )
    from .period_keys import period_type_for_task_master

    if request.method == "POST":
        form = TaskMasterForm(request.POST)
        if form.is_valid():
            from core.created_by import save_form_with_creator

            master = save_form_with_creator(form, request.user)
            _provision_task_master_documents(master, user=request.user)
            from masters.master_request_service import try_complete_master_request
            from masters.models import MasterRequest

            mr = try_complete_master_request(
                request,
                master,
                request.POST.get("master_request_id"),
                MasterRequest.TYPE_TASK_MASTER,
            )
            if embed_popup_request(request):
                return render_popup_created(
                    request,
                    picker_kind=PICKER_TASK_MASTER,
                    item_id=master.pk,
                    item_label=f"{master.task_group.name} — {master.name}",
                    extra={
                        "period_type": period_type_for_task_master(master) or "",
                    },
                )
            if mr:
                messages.info(request, f"Linked to master request #{mr.pk}. Requester notified.")
            messages.success(request, "Task master created.")
            return redirect("task_master_list")
        messages.error(request, "Could not save task master. Please fix the errors below.")
    else:
        form = TaskMasterForm()
    from masters.master_request_service import master_request_link_context
    from masters.models import MasterRequest

    ctx = _task_master_form_context(form, mode="create")
    ctx.update(
        embed_popup_context(
            request,
            cancel_url=reverse("task_master_list"),
        )
    )
    ctx.update(master_request_link_context(request, MasterRequest.TYPE_TASK_MASTER))
    template = embed_form_template(
        request,
        normal="tasks/task_master_form.html",
        popup="tasks/task_master_form_popup.html",
    )
    return render(request, template, ctx)


@require_perm("tasks.change_taskmaster")
def task_master_edit(request, pk: int):
    master = get_object_or_404(TaskMaster, pk=pk)
    if request.method == "POST":
        form = TaskMasterForm(request.POST, instance=master)
        if form.is_valid():
            form.save()
            _sync_task_master_documents(master)
            messages.success(request, "Task master updated.")
            return redirect("task_master_list")
        messages.error(request, "Could not save task master. Please fix the errors below.")
    else:
        form = TaskMasterForm(instance=master)
    return render(
        request,
        "tasks/task_master_form.html",
        _task_master_form_context(form, mode="edit", master=master),
    )


@require_perm("tasks.delete_taskmaster")
def task_master_delete(request, pk: int):
    master = get_object_or_404(TaskMaster, pk=pk)
    if request.method == "POST":
        try:
            master.delete()
        except ProtectedError:
            messages.error(
                request,
                "This task master cannot be deleted while tasks or enrollments use it. "
                "Cancel or remove those tasks first, or archive the master instead.",
            )
            return redirect("task_master_edit", pk=pk)
        messages.success(request, "Task master deleted.")
        return redirect("task_master_list")
    return render(request, "tasks/task_master_delete_confirm.html", {"master": master})


def _bulk_csv_preview_context(
    request,
    *,
    rows,
    columns,
    upload_url_name: str,
    preview_title: str,
    preview_page_title: str,
    success_hint: str,
    cells_fn,
):
    error_rows = []
    for r in rows:
        if r.errors:
            error_rows.append(
                {
                    "row_num": r.row_num,
                    "errors": r.errors,
                    "preview_cells": cells_fn(r),
                }
            )
    can_import = bool(rows) and all(not r.errors for r in rows)
    return {
        "rows": rows,
        "error_rows": error_rows,
        "total_rows": len(rows),
        "error_count": len(error_rows),
        "can_import": can_import,
        "columns": columns,
        "preview_columns": columns,
        "upload_url_name": upload_url_name,
        "preview_title": preview_title,
        "preview_page_title": preview_page_title,
        "success_hint": success_hint,
    }


TASK_GROUP_IMPORT_SESSION_KEY = "task_group_import_csv"


@require_perm("tasks.add_taskgroup")
def task_group_bulk_import(request):
    from .task_group_csv_import import TASK_GROUP_CSV_COLUMNS, parse_task_groups_csv

    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = request.session.get(TASK_GROUP_IMPORT_SESSION_KEY)
        if not raw:
            messages.error(request, "Nothing to import. Please upload the CSV again.")
            return redirect("task_group_bulk_import")
        rows, file_errors = parse_task_groups_csv(raw.encode("utf-8"))
        if file_errors or any(r.errors for r in rows):
            messages.error(request, "Cannot import: fix validation errors and upload again.")
            return redirect("task_group_bulk_import")
        with transaction.atomic():
            for r in rows:
                TaskGroup.objects.create(**r.data)
        request.session.pop(TASK_GROUP_IMPORT_SESSION_KEY, None)
        messages.success(request, f"Imported {len(rows)} task group(s).")
        return redirect("task_group_list")

    if request.method == "POST":
        f = request.FILES.get("csv_file")
        if not f:
            messages.error(request, "Please choose a CSV file.")
            return redirect("task_group_bulk_import")
        raw_bytes = f.read()
        rows, file_errors = parse_task_groups_csv(raw_bytes)
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("task_group_bulk_import")
        try:
            request.session[TASK_GROUP_IMPORT_SESSION_KEY] = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            request.session[TASK_GROUP_IMPORT_SESSION_KEY] = raw_bytes.decode("cp1252", errors="replace")
        ctx = _bulk_csv_preview_context(
            request,
            rows=rows,
            columns=["Name", "Sort", "Active"],
            upload_url_name="task_group_bulk_import",
            preview_title="Task groups import",
            preview_page_title="Task groups — Import preview",
            success_hint="Click Confirm import to create all task groups.",
            cells_fn=lambda r: [
                r.data.get("name", ""),
                r.data.get("sort_order", ""),
                "Yes" if r.data.get("is_active") else "No",
            ],
        )
        if ctx["can_import"]:
            messages.success(request, f"File uploaded. {len(rows)} row(s) ready to import.")
        else:
            messages.error(request, f"{ctx['error_count']} row(s) have errors.")
        return render(request, "includes/bulk_csv_import_preview_page.html", ctx)

    return render(
        request,
        "includes/bulk_csv_import_page.html",
        {
            "import_title": "Task groups import",
            "import_page_title": "Task groups — Bulk upload (CSV)",
            "import_description": "Each row creates one task group. NAME is required; SORT_ORDER defaults to 0; IS_ACTIVE is YES/NO or blank (YES).",
            "columns": TASK_GROUP_CSV_COLUMNS,
            "template_url_name": "task_group_bulk_import_template",
            "cancel_url_name": "task_group_list",
        },
    )


@require_perm("tasks.add_taskgroup")
def task_group_bulk_import_template(request):
    from .task_group_csv_import import TASK_GROUP_CSV_COLUMNS

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="task-groups-template.csv"'
    writer = csv.writer(response)
    writer.writerow(TASK_GROUP_CSV_COLUMNS)
    writer.writerow(["GST", "0", "YES"])
    writer.writerow(["ROC", "1", "YES"])
    return response


TASK_MASTER_IMPORT_SESSION_KEY = "task_master_import_csv"


@require_perm("tasks.add_taskmaster")
def task_master_bulk_import(request):
    from .checklist import save_master_checklist
    from .task_master_csv_import import TASK_MASTER_CSV_COLUMNS, parse_task_masters_csv

    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = request.session.get(TASK_MASTER_IMPORT_SESSION_KEY)
        if not raw:
            messages.error(request, "Nothing to import. Please upload the CSV again.")
            return redirect("task_master_bulk_import")
        rows, file_errors = parse_task_masters_csv(raw.encode("utf-8"))
        if file_errors or any(r.errors for r in rows):
            messages.error(request, "Cannot import: fix validation errors and upload again.")
            return redirect("task_master_bulk_import")
        with transaction.atomic():
            for r in rows:
                d = dict(r.data)
                checklist = d.pop("checklist_items", [])
                master = TaskMaster.objects.create(**d)
                save_master_checklist(master, checklist)
                _provision_task_master_documents(master, user=request.user)
        request.session.pop(TASK_MASTER_IMPORT_SESSION_KEY, None)
        messages.success(request, f"Imported {len(rows)} task master(s).")
        return redirect("task_master_list")

    if request.method == "POST":
        f = request.FILES.get("csv_file")
        if not f:
            messages.error(request, "Please choose a CSV file.")
            return redirect("task_master_bulk_import")
        raw_bytes = f.read()
        rows, file_errors = parse_task_masters_csv(raw_bytes)
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("task_master_bulk_import")
        try:
            request.session[TASK_MASTER_IMPORT_SESSION_KEY] = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            request.session[TASK_MASTER_IMPORT_SESSION_KEY] = raw_bytes.decode("cp1252", errors="replace")
        ctx = _bulk_csv_preview_context(
            request,
            rows=rows,
            columns=["Group", "Name", "Priority", "Active", "Recurring"],
            upload_url_name="task_master_bulk_import",
            preview_title="Task masters import",
            preview_page_title="Task masters — Import preview",
            success_hint="Recurring masters need valid RECURRENCE_CONFIG_JSON. Click Confirm import to save.",
            cells_fn=lambda r: [
                r.data.get("task_group").name if r.data.get("task_group") else "",
                r.data.get("name", ""),
                r.data.get("default_priority", ""),
                "Yes" if r.data.get("is_active") else "No",
                "Yes" if r.data.get("is_recurring") else "No",
            ],
        )
        if ctx["can_import"]:
            messages.success(request, f"File uploaded. {len(rows)} row(s) ready to import.")
        else:
            messages.error(request, f"{ctx['error_count']} row(s) have errors.")
        return render(request, "includes/bulk_csv_import_preview_page.html", ctx)

    return render(
        request,
        "includes/bulk_csv_import_page.html",
        {
            "import_title": "Task masters import",
            "import_page_title": "Task masters — Bulk upload (CSV)",
            "import_description": (
                "TASK_GROUP must match an existing task group name. "
                "For recurring masters (IS_RECURRING=YES), provide FREQUENCY and RECURRENCE_CONFIG_JSON "
                "(same JSON as saved from the task master form). CHECKLIST_ITEMS: separate with | or ;."
            ),
            "columns": TASK_MASTER_CSV_COLUMNS,
            "template_url_name": "task_master_bulk_import_template",
            "cancel_url_name": "task_master_list",
        },
    )


@require_perm("tasks.add_taskmaster")
def task_master_bulk_import_template(request):
    from .task_master_csv_import import TASK_MASTER_CSV_COLUMNS

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="task-masters-template.csv"'
    writer = csv.writer(response)
    writer.writerow(TASK_MASTER_CSV_COLUMNS)
    writer.writerow(["GST", "GSTR-1", "", "normal", "YES", "NO", "", "", ""])
    return response


def _task_list_context(
    request,
    *,
    list_title,
    show_new_task,
    csv_url_name,
    base_qs=None,
    show_submitter_verifier_names: bool = False,
):
    filters = parse_task_list_filters(request)
    tasks = get_filtered_tasks(request.user, filters, base_qs=base_qs)
    ctx = filter_context(request.user, filters)
    qs = filters_query_string(filters)
    ctx.update(
        {
            "task_rows": prepare_task_list_rows(tasks),
            "list_title": list_title,
            "show_new_task": show_new_task,
            "show_submitter_verifier_names": show_submitter_verifier_names,
            "csv_export_url": reverse(csv_url_name) + (f"?{qs}" if qs else ""),
        }
    )
    return ctx


@require_perm("tasks.view_task")
def task_list(request):
    base = tasks_for_user(request.user)
    filters = parse_task_list_filters(request)
    if request.GET.get("open") == "1" and not filters.status:
        base = base.exclude(status__in=Task.CLOSED_STATUSES)
    return render(
        request,
        "tasks/task_list.html",
        _task_list_context(
            request,
            list_title="All tasks",
            show_new_task=True,
            csv_url_name="task_list_csv",
            base_qs=base,
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
            show_submitter_verifier_names=True,
        ),
    )


@require_perm("tasks.view_task")
def task_list_csv(request):
    filters = parse_task_list_filters(request)
    return task_list_csv_response(request, request.user, filters, filename="all-tasks.csv")


@require_perm("tasks.view_task")
def task_report_csv(request):
    filters = parse_task_list_filters(request)
    return task_list_csv_response(
        request,
        request.user,
        filters,
        filename="task-report.csv",
        show_submitter_verifier_names=True,
    )


@require_perm("tasks.add_task")
def task_create(request):
    if request.method == "POST":
        form = TaskCreateForm(request.POST, user=request.user)
        if form.is_valid():
            master = form.cleaned_data["task_master"]
            client = form.cleaned_data["client"]
            assignees = list(form.cleaned_data["assignees"])
            verifiers = form.cleaned_data["verifiers"]
            document_checker = form.cleaned_data["document_checker"]
            due_date = form.cleaned_data["due_date"]
            enrollment = start_enrollment_if_recurring(
                master=master,
                client=client,
                assignee_users=assignees,
                verifiers=verifiers,
                document_checker=document_checker,
                created_by=request.user,
            )
            task = create_task_from_master(
                master=master,
                client=client,
                assignee_users=assignees,
                verifiers=verifiers,
                document_checker=document_checker,
                created_by=request.user,
                period_key=form.cleaned_data["period_key"],
                period_type=form.cleaned_data.get("period_type") or "",
                enrollment=enrollment,
                due_date=due_date,
                is_billable=form.cleaned_data.get("is_billable"),
                fees_amount=form.cleaned_data.get("fees_amount"),
                description=form.cleaned_data.get("description") or "",
            )
            if form.cleaned_data.get("priority"):
                task.priority = form.cleaned_data["priority"]
                task.save(update_fields=["priority"])
            if task.status == Task.STATUS_PENDING_ASSIGNMENT:
                messages.success(
                    request,
                    f"Task created: {task.title}. Assigned users must approve the task before work can begin.",
                )
            else:
                messages.success(request, f"Task created: {task.title}")
            from masters.master_request_service import try_complete_master_request
            from masters.models import MasterRequest

            mr = try_complete_master_request(
                request,
                task,
                request.POST.get("master_request_id"),
                MasterRequest.TYPE_NEW_TASK,
            )
            if mr:
                messages.info(request, f"Linked to master request #{mr.pk}. Requester notified.")
            return redirect("task_detail", pk=task.pk)
    else:
        form = TaskCreateForm(user=request.user)
    from .user_labels import staff_users_queryset, user_display_label

    staff_users = [
        {
            "id": u.pk,
            "label": user_display_label(u),
            "search": f"{user_display_label(u)} {u.email}".lower(),
        }
        for u in staff_users_queryset()
    ]
    clients = []
    for c in form.fields["client"].queryset:
        pan = (c.pan or "").strip().upper()
        label = f"{c.client_name} — {pan}" if pan else c.client_name
        clients.append({"id": c.pk, "label": label, "search": f"{c.client_name} {pan} {c.pk}".lower()})
    from .period_keys import period_type_for_task_master

    masters_meta = {
        str(m.pk): {
            "period_type": period_type_for_task_master(m) or "",
            "is_recurring": m.is_recurring,
        }
        for m in TaskMaster.objects.filter(is_active=True, archived_at__isnull=True).only(
            "pk", "is_recurring", "frequency"
        )
    }
    task_groups = [
        {"id": g.pk, "name": g.name}
        for g in TaskGroup.objects.filter(is_active=True).order_by("sort_order", "name")
    ]
    from masters.master_request_service import master_request_link_context
    from masters.models import MasterRequest

    ctx = {
        "form": form,
        "staff_users_json": staff_users,
        "clients_json": clients,
        "masters_meta_json": masters_meta,
        "can_add_task_master": request.user.is_superuser
        or request.user.has_perm("tasks.add_taskmaster"),
        "task_groups_json": task_groups,
    }
    ctx.update(master_request_link_context(request, MasterRequest.TYPE_NEW_TASK))
    return render(request, "tasks/task_create.html", ctx)


@require_perm("tasks.add_taskmaster")
def task_master_quick_create_api(request):
    if request.method != "POST":
        return JsonResponse({"detail": "POST required."}, status=405)
    name = (request.POST.get("name") or "").strip()
    group_id = (request.POST.get("task_group") or "").strip()
    if not name:
        return JsonResponse({"detail": "Task master name is required."}, status=400)
    if not group_id:
        return JsonResponse({"detail": "Task group is required."}, status=400)
    group = get_object_or_404(TaskGroup, pk=group_id)
    try:
        master = TaskMaster(
            task_group=group,
            name=name,
            is_active=True,
            is_recurring=False,
        )
        master.full_clean()
        master.save()
        _provision_task_master_documents(master, user=request.user)
    except ValidationError as e:
        detail = "; ".join(
            msg for msgs in getattr(e, "message_dict", {}).values() for msg in msgs
        ) or str(e)
        return JsonResponse({"detail": detail}, status=400)
    label = f"{group.name} — {master.name}"
    return JsonResponse({"id": master.pk, "label": label, "created": True})


TASK_IMPORT_SESSION_KEY = "task_import_csv"


def _task_bulk_import_preview_context(request, *, rows):
    def cells_fn(r):
        d = r.data
        client_label = d.get("client_id_display") or (
            d["client"].client_id if d.get("client") else ""
        )
        master_label = d.get("task_master_display") or (
            d["task_master"].name if d.get("task_master") else ""
        )
        due_label = d.get("due_date") or d.get("due_date_display") or ""
        return [
            client_label,
            master_label,
            d.get("assignees_display") or "",
            d.get("verifiers_display") or "",
            str(due_label),
            d.get("period_key") or "",
        ]

    return _bulk_csv_preview_context(
        request,
        rows=rows,
        columns=["Client ID", "Task master", "Assignees", "Verifiers", "Due date", "Period"],
        upload_url_name="task_bulk_import",
        preview_title="Task import",
        preview_page_title="Task import preview",
        success_hint="Click Confirm import to create tasks. Assignees must approve before work begins.",
        cells_fn=cells_fn,
    )


def _render_task_bulk_import_preview(request, rows, *, flash_success: bool = False, flash_error: str = ""):
    ctx = _task_bulk_import_preview_context(request, rows=rows)
    if flash_success and ctx["can_import"]:
        messages.success(request, f"File uploaded. {ctx['total_rows']} row(s) ready to import.")
    elif flash_error:
        messages.error(request, flash_error)
    elif ctx["error_count"]:
        messages.error(
            request,
            f"{ctx['error_count']} row(s) have errors. Fix the CSV and upload again, or review the rows below.",
        )
    return render(request, "includes/bulk_csv_import_preview_page.html", ctx)


@require_perm("tasks.add_task")
def task_bulk_import(request):
    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = request.session.get(TASK_IMPORT_SESSION_KEY)
        if not raw:
            messages.error(request, "Import session expired. Please upload the file again.")
            return redirect("task_bulk_import")
        from .task_csv_import import parse_tasks_csv

        rows, file_errors = parse_tasks_csv(raw.encode("utf-8"), user=request.user)
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("task_bulk_import")
        if any(r.errors for r in rows):
            return _render_task_bulk_import_preview(
                request,
                rows,
                flash_error="Cannot import: fix the errors below and upload again.",
            )
        from django.db import IntegrityError

        created = 0
        try:
            with transaction.atomic():
                for row in rows:
                    d = row.data
                    master = d["task_master"]
                    client = d["client"]
                    assignees = d["assignees"]
                    verifiers = d["verifiers"]
                    document_checker = d["document_checker"]
                    enrollment = start_enrollment_if_recurring(
                        master=master,
                        client=client,
                        assignee_users=assignees,
                        verifiers=verifiers,
                        document_checker=document_checker,
                        created_by=request.user,
                    )
                    task = create_task_from_master(
                        master=master,
                        client=client,
                        assignee_users=assignees,
                        verifiers=verifiers,
                        document_checker=document_checker,
                        created_by=request.user,
                        period_key=d["period_key"],
                        period_type=d.get("period_type") or "",
                        enrollment=enrollment,
                        due_date=d["due_date"],
                        is_billable=d.get("is_billable"),
                        fees_amount=d.get("fees_amount"),
                    )
                    if d.get("priority"):
                        task.priority = d["priority"]
                        task.save(update_fields=["priority"])
                    created += 1
        except ValidationError as exc:
            msg = exc.messages[0] if exc.messages else str(exc)
            return _render_task_bulk_import_preview(
                request,
                rows,
                flash_error=f"Import stopped at row {created + 1}: {msg}",
            )
        except IntegrityError:
            return _render_task_bulk_import_preview(
                request,
                rows,
                flash_error=(
                    f"Import stopped: a task already exists for the same client, task type, and period "
                    f"(row {created + 1} or later). Delete the existing task or change the period."
                ),
            )
        request.session.pop(TASK_IMPORT_SESSION_KEY, None)
        messages.success(
            request,
            f"Imported {created} task(s). Verifiers are notified to approve assignments where required.",
        )
        return redirect("task_list" if request.user.has_perm("tasks.view_task") else "task_my_list")

    if request.method == "POST":
        from .task_csv_import import TASK_CSV_COLUMNS, parse_tasks_csv

        f = request.FILES.get("csv_file")
        if not f:
            messages.error(request, "Please choose a CSV file.")
            return redirect("task_bulk_import")
        raw_bytes = f.read()
        try:
            rows, file_errors = parse_tasks_csv(raw_bytes, user=request.user)
        except Exception as exc:
            messages.error(request, f"Could not read CSV file: {exc}")
            return redirect("task_bulk_import")
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("task_bulk_import")
        try:
            request.session[TASK_IMPORT_SESSION_KEY] = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            request.session[TASK_IMPORT_SESSION_KEY] = raw_bytes.decode("cp1252", errors="replace")
        return _render_task_bulk_import_preview(request, rows, flash_success=True)

    from .task_csv_import import TASK_CSV_COLUMNS

    return render(request, "tasks/task_bulk_import.html", {"columns": TASK_CSV_COLUMNS})


@require_perm("tasks.add_task")
def task_bulk_import_template(request):
    from .task_csv_import import TASK_CSV_COLUMNS

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="task-bulk-upload-template.csv"'
    writer = csv.writer(response)
    writer.writerow(TASK_CSV_COLUMNS)
    writer.writerow(
        [
            "CL001",
            "GST|GSTR-1",
            "staff@example.com",
            "verify@example.com",
            "docs@example.com",
            "monthly",
            "4",
            "2026",
            "",
            "",
            "",
            "",
            "2026-05-31",
            "normal",
            "NO",
            "",
        ]
    )
    return response


def can_edit_task_team(user, task: Task) -> bool:
    if not task_team_is_editable(task):
        return False
    return (
        user.is_superuser
        or user.has_perm("tasks.change_task")
        or user.has_perm("tasks.add_task")
        or task.created_by_id == user.pk
    )


@login_required
def task_edit(request, pk: int):
    task = get_object_or_404(task_detail_queryset(request.user), pk=pk)
    if not can_edit_task_team(request.user, task):
        raise PermissionDenied

    if request.method == "POST":
        form = TaskEditForm(request.POST, task=task, user=request.user)
        if form.is_valid():
            try:
                update_task_team(
                    task,
                    assignee_users=form.cleaned_data["assignees"],
                    verifiers=form.cleaned_data["verifiers"],
                    document_checker=form.cleaned_data["document_checker"],
                    due_date=form.cleaned_data["due_date"],
                    priority=form.cleaned_data["priority"],
                    description=form.cleaned_data.get("description") or "",
                    actor=request.user,
                )
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if exc.messages else str(exc))
            else:
                messages.success(request, "Task updated.")
                return redirect("task_detail", pk=task.pk)
    else:
        form = TaskEditForm(task=task, user=request.user)

    from .user_labels import staff_users_queryset, user_display_label

    staff_users = [
        {"id": u.pk, "label": user_display_label(u)}
        for u in staff_users_queryset()
    ]
    initial_assignees = [
        {"id": a.user_id, "label": user_display_label(a.user)}
        for a in task.assignments.select_related("user", "user__employee_profile")
    ]
    initial_verifiers = [
        {"id": u.pk, "label": user_display_label(u)}
        for u in task.verifiers.select_related("employee_profile")
    ]
    from .period_display import format_period_display

    period_cols = format_period_display(
        task.period_key,
        period_type=task.period_type or "",
        master=task.task_master,
    )
    return render(
        request,
        "tasks/task_edit.html",
        {
            "form": form,
            "task": task,
            "staff_users_json": staff_users,
            "initial_assignees_json": initial_assignees,
            "initial_verifiers_json": initial_verifiers,
            "period_frequency": period_cols.frequency,
            "period_label": period_cols.period,
        },
    )


@login_required
def task_detail(request, pk: int):
    from .verifiers import format_task_verifier_names, user_is_task_verifier

    task = get_object_or_404(task_detail_queryset(request.user), pk=pk)
    is_assignee = task.assignments.filter(user=request.user).exists()
    is_verifier = user_is_task_verifier(request.user, task)
    is_document_checker = task.document_checker_id == request.user.pk
    is_creator = task.created_by_id == request.user.pk
    can_view_task = (
        request.user.is_superuser
        or request.user.has_perm("tasks.view_task")
        or is_verifier
        or is_document_checker
        or is_creator
        or is_assignee
    )
    if not can_view_task:
        raise PermissionDenied

    remark_form = TaskRemarkForm()
    assignee_active = is_assignee and task.status != Task.STATUS_PENDING_ASSIGNMENT
    none_client_can_submit = may_submit_for_client_type(task)
    checklist_complete = checklist_ready_for_submit(task)
    can_submit = assignee_active and (
        (
            task.status in (Task.STATUS_ASSIGNED, Task.STATUS_REWORK)
            and none_client_can_submit
            and checklist_complete
        )
        or task.status == Task.STATUS_DOCUMENT_REWORK
    )
    submit_button_label = (
        "Resubmit for document check"
        if task.status == Task.STATUS_DOCUMENT_REWORK
        else "Submit for verification"
    )
    can_verify = is_verifier and task.status == Task.STATUS_SUBMITTED
    can_verify_rework = is_verifier and task.status == Task.STATUS_SUBMITTED
    can_complete_documents = (
        is_document_checker or request.user.is_superuser
    ) and task.status == Task.STATUS_VERIFIED
    can_send_back_documents = can_complete_documents
    can_approve_assignment = user_can_approve_task_assignment(request.user, task)
    can_toggle_checklist = assignee_active and task.status in (
        Task.STATUS_ASSIGNED,
        Task.STATUS_REWORK,
        Task.STATUS_DOCUMENT_REWORK,
    )
    can_manage_task = (
        assignee_active
        or is_creator
        or is_verifier
        or is_document_checker
        or request.user.has_perm("tasks.change_task")
    )
    can_cancel = can_manage_task and task.status in (
        Task.STATUS_PENDING_ASSIGNMENT,
        Task.STATUS_ASSIGNED,
        Task.STATUS_REWORK,
        Task.STATUS_DOCUMENT_REWORK,
        Task.STATUS_SUBMITTED,
        Task.STATUS_VERIFIED,
    )
    can_delete = request.user.has_perm("tasks.delete_task") and task.status in (
        Task.STATUS_PENDING_ASSIGNMENT,
        Task.STATUS_ASSIGNED,
        Task.STATUS_CANCELLED,
    )
    can_edit = can_edit_task_team(request.user, task)
    checklist_items = list(task.checklist_items.all())

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "checklist_set" and can_toggle_checklist:
            item_id = request.POST.get("item_id")
            mode = (request.POST.get("mode") or "").strip().lower()
            if item_id and str(item_id).isdigit():
                try:
                    if mode == "toggle":
                        toggle_task_checklist_item(
                            task=task,
                            item_id=int(item_id),
                            user=request.user,
                            done=request.POST.get("done") == "1",
                        )
                    else:
                        set_task_checklist_item_status(
                            task=task,
                            item_id=int(item_id),
                            user=request.user,
                            mode=mode,
                        )
                except ValidationError as exc:
                    messages.error(request, exc.messages[0] if exc.messages else str(exc))
            return redirect("task_detail", pk=pk)
        if action == "checklist_toggle" and can_toggle_checklist:
            item_id = request.POST.get("item_id")
            if item_id and str(item_id).isdigit():
                try:
                    toggle_task_checklist_item(
                        task=task,
                        item_id=int(item_id),
                        user=request.user,
                        done=request.POST.get("done") == "1",
                    )
                except ValidationError as exc:
                    messages.error(request, exc.messages[0] if exc.messages else str(exc))
            return redirect("task_detail", pk=pk)
        if action == "cancel" and can_cancel:
            cancel_task(task, request.user)
            messages.success(request, "Task cancelled. Recurring schedule stopped for this client and task type.")
            return redirect("task_detail", pk=pk)
        if action == "delete" and can_delete:
            delete_task(task, request.user)
            messages.success(request, "Task deleted.")
            return redirect("task_list")
        if action == "approve_assignment" and can_approve_assignment:
            approve_task_assignment(task, request.user)
            messages.success(request, "Task approved. You and other assigned users can now work on it.")
            return redirect("task_detail", pk=pk)
        if action == "submit" and can_submit:
            resubmit_for_documents = task.status == Task.STATUS_DOCUMENT_REWORK
            try:
                submit_task(task, request.user)
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if exc.messages else str(exc))
            else:
                if resubmit_for_documents:
                    messages.success(request, "Task resubmitted for document check.")
                else:
                    messages.success(request, "Task submitted for verification.")
            return redirect("task_detail", pk=pk)
        if action == "remark":
            remark_form = TaskRemarkForm(request.POST)
            if remark_form.is_valid():
                from .services import _log_activity

                _log_activity(
                    task,
                    request.user,
                    TaskActivity.TYPE_REMARK,
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
    from .period_display import format_period_display

    period_cols = format_period_display(
        task.period_key,
        period_type=task.period_type or "",
        master=task.task_master,
    )

    task_doc_ctx: dict = {"show_task_documents": False}
    if documents_module_enabled() and task_module_enabled():
        from documents.periods import extract_fy_from_period_key
        from documents.task_bridge import document_period_from_task, task_documents_locked, user_can_change_task_linked_document
        from documents.task_services import build_task_document_slots

        try:
            period_key, period_label = document_period_from_task(task)
        except ValidationError:
            period_key, period_label = "once", (task.period_key or "—")
        task_doc_slots = build_task_document_slots(task)
        for slot in task_doc_slots:
            doc = slot.get("document")
            if doc:
                slot["can_change"] = user_can_change_task_linked_document(
                    request.user, doc, task=task
                )
            else:
                slot["can_change"] = slot["can_upload"]
        task_doc_ctx = {
            "show_task_documents": True,
            "task_doc_slots": task_doc_slots,
            "task_doc_period_label": period_label,
            "task_doc_period_fy": extract_fy_from_period_key(period_key),
            "task_doc_locked": task_documents_locked(task),
        }

    return render(
        request,
        "tasks/task_detail.html",
        {
            "task": task,
            "period_frequency": period_cols.frequency,
            "period_label": period_cols.period,
            "activity_rows": activity_rows,
            "assignees": assignees,
            "verifier_label": format_task_verifier_names(task),
            "document_checker_label": user_person_name(task.document_checker),
            "remark_form": remark_form,
            "can_submit": can_submit,
            "can_verify": can_verify,
            "none_client_can_submit": none_client_can_submit,
            "none_client_submit_message": none_client_submit_block_message(),
            "can_verify_rework": can_verify_rework,
            "can_complete_documents": can_complete_documents,
            "can_send_back_documents": can_send_back_documents,
            "submit_button_label": submit_button_label,
            "can_approve_assignment": can_approve_assignment,
            "checklist_items": checklist_items,
            "checklist_complete": checklist_complete,
            "checklist_pending_labels": checklist_pending_labels(task),
            "can_toggle_checklist": can_toggle_checklist,
            "can_cancel": can_cancel,
            "can_delete": can_delete,
            "can_edit": can_edit,
            "assignment_pending": task.status == Task.STATUS_PENDING_ASSIGNMENT,
            **task_doc_ctx,
        },
    )


@login_required
def task_my_list(request):
    base = tasks_for_user(request.user).filter(assignments__user=request.user)
    filters = parse_task_list_filters(request)
    if not filters.status:
        base = base.exclude(status__in=Task.DONE_FOR_ASSIGNEE_STATUSES)
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
        base = base.exclude(status__in=Task.DONE_FOR_ASSIGNEE_STATUSES)
    return task_list_csv_response(
        request,
        request.user,
        filters,
        base_qs=base,
        filename="my-tasks.csv",
    )


@require_perm("tasks.verify_task")
def task_verify_queue(request):
    user = request.user
    assignment_base = tasks_for_user(user).none()
    submitted_base = tasks_for_user(user).filter(
        status=Task.STATUS_SUBMITTED,
        verifiers=user,
    )
    # New Client tasks are not allowed to submit/verify/complete; do not show any special "verify without submit" section.
    none_client_approve_base = tasks_for_user(user).none()
    filters = parse_task_list_filters(request)
    ctx = filter_context(user, filters)
    ctx.update(
        {
            "assignment_rows": prepare_task_list_rows(
                get_filtered_tasks(user, filters, base_qs=assignment_base)
            ),
            "submitted_rows": prepare_task_list_rows(
                get_filtered_tasks(user, filters, base_qs=submitted_base)
            ),
            "none_client_approve_rows": prepare_task_list_rows(
                get_filtered_tasks(user, filters, base_qs=none_client_approve_base)
            ),
            "list_title": "Verification queue",
        }
    )
    return render(request, "tasks/task_verify_queue.html", ctx)


@login_required
@require_POST
def task_assignment_approve(request, pk: int):
    task = get_object_or_404(
        tasks_for_user(request.user).filter(
            status=Task.STATUS_PENDING_ASSIGNMENT,
            assignments__user=request.user,
        ),
        pk=pk,
    )
    form = TaskVerifyForm(request.POST)
    message = form.cleaned_data["message"] if form.is_valid() else ""
    approve_task_assignment(task, request.user, message=message)
    messages.success(request, "Task approved. You can now work on this task.")
    return redirect("task_my_list")


@require_perm("tasks.verify_task")
@require_POST
def task_verify_approve(request, pk: int):
    task = get_object_or_404(
        tasks_for_user(request.user).filter(verifiers=request.user),
        pk=pk,
    )
    if task.status != Task.STATUS_SUBMITTED:
        raise Http404
    form = TaskVerifyForm(request.POST)
    message = form.cleaned_data["message"] if form.is_valid() else ""
    try:
        verify_task(task, request.user, message=message)
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if exc.messages else str(exc))
        return redirect("task_detail", pk=pk)
    messages.success(request, "Task verified. Sent to document checker.")
    return redirect("task_verify_queue")


@require_perm("tasks.check_documents")
def task_document_check_queue(request):
    user = request.user
    base = tasks_for_user(user).filter(
        status=Task.STATUS_VERIFIED,
        document_checker=user,
    )
    filters = parse_task_list_filters(request)
    ctx = filter_context(user, filters)
    ctx.update(
        {
            "document_check_rows": prepare_task_list_rows(
                get_filtered_tasks(user, filters, base_qs=base)
            ),
            "list_title": "Document check queue",
        }
    )
    return render(request, "tasks/task_document_check_queue.html", ctx)


@require_perm("tasks.check_documents")
@require_POST
def task_document_check_complete(request, pk: int):
    task = get_object_or_404(
        tasks_for_user(request.user).filter(
            status=Task.STATUS_VERIFIED,
            document_checker=request.user,
        ),
        pk=pk,
    )
    form = TaskVerifyForm(request.POST)
    message = form.cleaned_data["message"] if form.is_valid() else ""
    try:
        complete_task(task, request.user, message=message)
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if exc.messages else str(exc))
        return redirect("task_detail", pk=pk)
    messages.success(request, "Document check complete. Task is now complete.")
    return redirect("task_document_check_queue")


@require_perm("tasks.check_documents")
@require_POST
def task_document_check_send_back(request, pk: int):
    task = get_object_or_404(
        tasks_for_user(request.user).filter(
            status=Task.STATUS_VERIFIED,
            document_checker=request.user,
        ),
        pk=pk,
    )
    try:
        send_back_for_document_correction(task, request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if exc.messages else str(exc))
        return redirect("task_detail", pk=pk)
    messages.success(request, "Task sent back to users for document correction.")
    return redirect("task_document_check_queue")


@require_perm("tasks.verify_task")
@require_POST
def task_verify_rework(request, pk: int):
    task = get_object_or_404(
        tasks_for_user(request.user).filter(status=Task.STATUS_SUBMITTED, verifiers=request.user),
        pk=pk,
    )
    form = TaskVerifyForm(request.POST)
    message = form.cleaned_data["message"] if form.is_valid() else ""
    rework_task(task, request.user, message=message)
    messages.success(request, "Task sent for rework.")
    return redirect("task_verify_queue")


@require_perm("tasks.view_task")
def task_dashboard(request):
    """Task summary lives on the main dashboard."""
    return redirect(f"{reverse('dashboard')}#task-summary")


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
