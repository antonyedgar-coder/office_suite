import base64

from django.db import transaction, IntegrityError
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.core.exceptions import PermissionDenied, ValidationError

from core.ui_breadcrumbs import breadcrumbs as ui_breadcrumbs

from .director_mapping_import import (
    DIRECTOR_MAPPING_CSV_HEADERS,
    attach_client_master_validation,
    parse_director_mappings_csv,
    validate_director_mapping_import_active_uniqueness_in_file,
)
from .forms import (
    ClientDSCForm,
    ClientForm,
    ClientGroupForm,
    ClientPortalCredentialForm,
    DSCInOutForm,
    DirectorCompanyPickForm,
    DirectorForm,
    DirectorMappingRowFormSet,
    ExpenseCategoryForm,
    individual_clients_for_user,
)
from .dsc_expiry_notifications import reset_dsc_expiry_notification_schedule
from .client_activity import (
    CLIENT_ACTIVITY_DATE_PRESET_CHOICES,
    apply_client_activity_log_filters,
    build_client_activity_list_rows,
    build_client_activity_rows,
    client_activity_log_queryset_for_user,
    get_client_activity_timeline,
    log_client_activity,
    parse_client_activity_log_filters,
    user_display_name,
)
from .models import (
    DIRECTOR_COMPANY_TYPES,
    DIRECTOR_ELIGIBLE_CLIENT_TYPES,
    Client,
    ClientActivityLog,
    ClientDSC,
    ClientGroup,
    ClientPortalCredential,
    DSCInOut,
    DirectorMapping,
    ExpenseCategory,
    PortalName,
)
from .csv_import import parse_clients_csv, CSV_COLUMNS
from .group_csv_import import GROUP_CSV_COLUMNS, parse_client_groups_csv

from core.branch_access import filter_clients_by_branch
from core.decorators import require_perm
from core.feature_flags import task_module_enabled


def client_master_queryset_for_user(user):
    """List / edit / delete visibility: all for superuser & approvers; others see approved + own pending."""
    if user.is_superuser or user.has_perm("masters.approve_client"):
        qs = Client.objects.select_related("client_group").all().order_by("client_name")
    else:
        qs = (
            Client.objects.select_related("client_group")
            .filter(Q(approval_status=Client.APPROVED) | Q(approval_status=Client.PENDING, created_by=user))
            .order_by("client_name")
        )
    return filter_clients_by_branch(qs, user)


def _apply_new_client_approval(client, user):
    now = timezone.now()
    if user.is_superuser:
        client.approval_status = Client.APPROVED
        client.created_by = user
        client.approved_by = user
        client.approved_at = now
    else:
        client.approval_status = Client.PENDING
        client.created_by = user
        client.approved_by = None
        client.approved_at = None


def user_may_approve_pending_client(user, client: Client) -> bool:
    """Creators cannot approve/reject their own pending client; superuser can."""
    if user.is_superuser:
        return True
    if client.created_by_id and client.created_by_id == user.pk:
        return False
    return True


def _apply_updated_client_approval(client, user):
    now = timezone.now()
    if user.is_superuser:
        client.approval_status = Client.APPROVED
        client.approved_by = user
        client.approved_at = now
    else:
        client.approval_status = Client.PENDING
        client.approved_by = None
        client.approved_at = None


def _group_options_for_client_form(client: Client | None = None) -> list[dict[str, str]]:
    qs = ClientGroup.objects.filter(is_active=True).order_by("name")
    if client and getattr(client, "client_group_id", None):
        qs = ClientGroup.objects.filter(Q(is_active=True) | Q(pk=client.client_group_id)).order_by("name")
    return [{"id": str(g.pk), "label": f"{g.name} — {g.group_id}"} for g in qs]


def _parse_client_detail_task_filters(request, client_id: str) -> dict:
    from tasks.listing import _parse_preset_block

    d_preset, d_from, d_to = _parse_preset_block(request, "due")
    return {
        "client_id": client_id,
        "group_id": (request.GET.get("group") or "").strip(),
        "master_id": (request.GET.get("master") or "").strip(),
        "assignee_id": (request.GET.get("assignee") or "").strip(),
        "due_preset": d_preset,
        "due_from": d_from,
        "due_to": d_to,
    }


# Company types: directors appointed to this client (Director Mapping tab).
CLIENT_DETAIL_COMPANY_DIRECTOR_TYPES = frozenset(
    {"Private Limited", "Public Limited", "Nidhi Co", "Sec 8 Co", "FPO"}
)


def _client_detail_show_dsc_tab(client: Client, user) -> bool:
    return client.client_type == "Individual" and user.has_perm("masters.view_clientdsc")


def _client_detail_show_mis_tab(user) -> bool:
    return any(
        user.has_perm(code)
        for code in (
            "mis.view_feesdetail",
            "mis.view_receipt",
            "mis.view_expensedetail",
            "mis.view_tenderdetail",
        )
    )


def _client_detail_show_directors_tab(client: Client) -> bool:
    if client.client_type in CLIENT_DETAIL_COMPANY_DIRECTOR_TYPES:
        return True
    return client.client_type in DIRECTOR_ELIGIBLE_CLIENT_TYPES and client.is_director


def _client_detail_director_mapping_mode(client: Client) -> str | None:
    if client.client_type in CLIENT_DETAIL_COMPANY_DIRECTOR_TYPES:
        return "company"
    if client.client_type in DIRECTOR_ELIGIBLE_CLIENT_TYPES and client.is_director:
        return "person"
    return None


def _apply_client_detail_task_filters(qs, filters: dict):
    from django.utils.dateparse import parse_date

    if filters.get("group_id"):
        qs = qs.filter(task_master__task_group_id=filters["group_id"])
    if filters.get("master_id"):
        qs = qs.filter(task_master_id=filters["master_id"])
    if filters.get("assignee_id"):
        qs = qs.filter(assignments__user_id=filters["assignee_id"])
    d_from = parse_date(filters.get("due_from") or "")
    d_to = parse_date(filters.get("due_to") or "")
    if d_from:
        qs = qs.filter(due_date__gte=d_from)
    if d_to:
        qs = qs.filter(due_date__lte=d_to)
    return qs.distinct()


@require_perm("masters.view_client")
def client_detail(request, client_id: str):
    client = get_object_or_404(
        client_master_queryset_for_user(request.user).select_related(
            "client_group", "created_by", "approved_by"
        ),
        pk=client_id,
    )
    tab = (request.GET.get("tab") or "details").strip().lower()
    show_tasks = task_module_enabled() and request.user.has_perm("tasks.view_task")
    show_passwords = request.user.has_perm("masters.view_clientportalcredential")
    show_dsc = _client_detail_show_dsc_tab(client, request.user)
    show_mis = _client_detail_show_mis_tab(request.user)
    show_directors = _client_detail_show_directors_tab(client) and request.user.has_perm(
        "masters.view_directormapping"
    )
    allowed_tabs = {"details", "tasks", "passwords", "dsc", "mis", "directors"}
    if tab == "tasks" and not show_tasks:
        tab = "details"
    if tab == "passwords" and not show_passwords:
        tab = "details"
    if tab == "dsc" and not show_dsc:
        tab = "details"
    if tab == "mis" and not show_mis:
        tab = "details"
    if tab == "directors" and not show_directors:
        tab = "details"
    if tab not in allowed_tabs:
        tab = "details"

    ctx = {
        "client": client,
        "active_tab": tab,
        "show_tasks_tab": show_tasks,
        "show_passwords_tab": show_passwords,
        "show_dsc_tab": show_dsc,
        "show_mis_tab": show_mis,
        "show_directors_tab": show_directors,
        "can_edit_client": request.user.has_perm("masters.change_client"),
        "can_add_password": request.user.has_perm("masters.add_clientportalcredential"),
        "can_add_dsc": request.user.has_perm("masters.add_clientdsc"),
        "can_add_director_mapping": request.user.has_perm("masters.add_directormapping"),
    }

    if tab == "tasks" and show_tasks:
        from tasks.listing import prepare_task_list_rows
        from tasks.listing import tasks_queryset_for_user
        from tasks.date_presets import DATE_PRESET_CHOICES
        from tasks.models import TaskGroup, TaskMaster
        from tasks.user_labels import staff_users_queryset

        task_filters = _parse_client_detail_task_filters(request, client_id)
        qs = tasks_queryset_for_user(request.user).filter(client_id=client_id)
        qs = _apply_client_detail_task_filters(qs, task_filters)
        ctx["task_rows"] = prepare_task_list_rows(qs[:500], include_assignees=True)
        ctx["task_filters"] = task_filters
        ctx["date_preset_choices"] = DATE_PRESET_CHOICES
        ctx["task_groups"] = TaskGroup.objects.filter(is_active=True).order_by("sort_order", "name")
        masters_qs = TaskMaster.objects.filter(is_active=True, archived_at__isnull=True).select_related(
            "task_group"
        )
        if task_filters.get("group_id"):
            masters_qs = masters_qs.filter(task_group_id=task_filters["group_id"])
        ctx["task_masters"] = masters_qs.order_by("task_group__sort_order", "name")
        ctx["staff_users"] = staff_users_queryset()

    if tab == "passwords" and show_passwords:
        ctx["portal_passwords"] = (
            ClientPortalCredential.objects.filter(client_id=client_id)
            .select_related("portal", "created_by", "updated_by")
            .order_by("portal__name", "portal_username")
        )

    if tab == "dsc" and show_dsc:
        ctx["dsc_rows"] = (
            _dsc_qs_for_user(request.user)
            .filter(client_id=client.pk)
            .order_by("-expiry_date", "-created_at")
        )
        ctx["dsc_inout_rows"] = (
            _dsc_inout_qs_for_user(request.user)
            .filter(dsc__client_id=client.pk)
            .order_by("-in_date", "-pk")[:100]
        )

    if tab == "mis" and show_mis:
        from django.db.models import Q

        from core.branch_access import filter_mis_qs
        from mis.models import ExpenseDetail, FeesDetail, Receipt, TenderDetail

        mis_client = Q(client_id=client.pk)
        user = request.user
        ctx["mis_fees_rows"] = []
        ctx["mis_receipt_rows"] = []
        ctx["mis_expense_rows"] = []
        ctx["mis_tender_rows"] = []
        if user.has_perm("mis.view_feesdetail"):
            ctx["mis_fees_rows"] = list(
                filter_mis_qs(FeesDetail.objects.select_related("client"), user)
                .filter(mis_client)
                .order_by("-date", "-id")[:50]
            )
        if user.has_perm("mis.view_receipt"):
            ctx["mis_receipt_rows"] = list(
                filter_mis_qs(Receipt.objects.select_related("client"), user)
                .filter(mis_client)
                .order_by("-date", "-id")[:50]
            )
        if user.has_perm("mis.view_expensedetail"):
            ctx["mis_expense_rows"] = list(
                filter_mis_qs(ExpenseDetail.objects.select_related("client", "category"), user)
                .filter(mis_client)
                .order_by("-date", "-id")[:50]
            )
        if user.has_perm("mis.view_tenderdetail"):
            ctx["mis_tender_rows"] = list(
                filter_mis_qs(TenderDetail.objects.select_related("client"), user)
                .filter(mis_client)
                .order_by("-date", "-id")[:50]
            )
        ctx["mis_client_q"] = client.client_id

    if tab == "directors" and show_directors:
        from core.branch_access import filter_director_mapping_qs

        mode = _client_detail_director_mapping_mode(client)
        ctx["director_mapping_mode"] = mode
        base = filter_director_mapping_qs(
            DirectorMapping.objects.select_related("director", "company"),
            request.user,
        )
        if mode == "company":
            ctx["director_mappings"] = base.filter(company_id=client.pk).order_by(
                "-appointed_date", "director__client_name"
            )
        else:
            ctx["director_mappings"] = base.filter(director_id=client.pk).order_by(
                "-appointed_date", "company__client_name"
            )

    if tab == "details":
        if client.client_group_id:
            g = client.client_group
            ctx["group_display"] = f"{g.name} ({g.group_id})"
        else:
            ctx["group_display"] = "—"
        ctx["dob_display"] = client.dob.strftime("%d-%m-%Y") if client.dob else "—"
        created = timezone.localtime(client.created_at).strftime("%d-%m-%Y %H:%M")
        if client.created_by_id:
            created += f" — {user_display_name(client.created_by)}"
        ctx["created_display"] = created
        if client.approved_at:
            approved = timezone.localtime(client.approved_at).strftime("%d-%m-%Y %H:%M")
            if client.approved_by_id:
                approved += f" — {user_display_name(client.approved_by)}"
            ctx["approved_display"] = approved

    return render(request, "masters/client_detail.html", ctx)


@require_perm("masters.view_client")
def client_list(request):
    q = (request.GET.get("q") or "").strip().upper()
    qs = client_master_queryset_for_user(request.user)
    if q:
        qs = qs.filter(
            Q(client_name__icontains=q)
            | Q(client_group__name__icontains=q)
            | Q(client_group__group_id__icontains=q)
            | Q(file_no__icontains=q)
            | Q(pan__icontains=q)
            | Q(client_id__icontains=q)
            | Q(passport_no__icontains=q)
            | Q(aadhaar_no__icontains=q)
        )
    empty_state_add_url = reverse("client_create") if request.user.has_perm("masters.add_client") else ""
    return render(
        request,
        "masters/client_list.html",
        {
            "clients": qs,
            "q": q,
            "empty_state_add_url": empty_state_add_url,
            "breadcrumbs": ui_breadcrumbs(("Client Master",)),
        },
    )


@require_perm("masters.view_client")
def client_activity_log_list(request):
    filters = parse_client_activity_log_filters(request.GET)
    qs = client_activity_log_queryset_for_user(request.user)
    qs = apply_client_activity_log_filters(qs, filters)

    can_link_tasks = task_module_enabled() and (
        request.user.is_superuser or request.user.has_perm("tasks.view_task")
    )
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    activity_rows = build_client_activity_list_rows(page_obj.object_list, can_link_tasks=can_link_tasks)

    client_opts = []
    for c in client_master_queryset_for_user(request.user).values("client_id", "client_name", "pan"):
        pan = (c.get("pan") or "").strip().upper()
        name = c.get("client_name") or ""
        label = f"{name} — {pan}" if pan else name
        client_opts.append(
            {
                "id": c["client_id"],
                "label": label,
                "search": f"{name} {pan}".lower(),
            }
        )

    from tasks.user_labels import staff_users_queryset

    staff_names = []
    for u in staff_users_queryset():
        name = user_display_name(u)
        if name:
            staff_names.append(name)

    from .client_activity import task_master_choices_for_activity_log

    task_master_choices = task_master_choices_for_activity_log()
    show_task_type_filter = task_module_enabled()

    return render(
        request,
        "masters/client_activity_log_list.html",
        {
            "page_obj": page_obj,
            "activity_rows": activity_rows,
            "filters": filters,
            "category_choices": ClientActivityLog.CATEGORY_CHOICES,
            "date_preset_choices": CLIENT_ACTIVITY_DATE_PRESET_CHOICES,
            "can_link_tasks": can_link_tasks,
            "client_opts": client_opts,
            "staff_names": staff_names,
            "task_master_choices": task_master_choices,
            "show_task_type_filter": show_task_type_filter,
            "enable_task_module": task_module_enabled(),
            "breadcrumbs": ui_breadcrumbs(("Client activity log",)),
        },
    )


@require_perm("masters.add_client")
def client_create(request):
    if request.method == "POST":
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save(commit=False)
            _apply_new_client_approval(client, request.user)
            client.save()
            if client.approval_status == Client.APPROVED:
                log_client_activity(
                    client=client,
                    user=request.user,
                    category=ClientActivityLog.CATEGORY_CLIENT,
                    activity=f"Client master created ({client.client_id}).",
                    remarks=client.remarks,
                )
                messages.success(request, f"Client created: {client.client_id}")
            else:
                log_client_activity(
                    client=client,
                    user=request.user,
                    category=ClientActivityLog.CATEGORY_CLIENT,
                    activity=(
                        f"Client master created ({client.client_id}) and is pending approval."
                    ),
                    remarks=client.remarks,
                )
                messages.success(
                    request,
                    f"Client saved as {client.client_id} and is pending approval. "
                    "An approver must accept it before it can be used in MIS, director mapping, or DIR-3 KYC.",
                )
            return redirect("client_list")
    else:
        form = ClientForm()
    return render(
        request,
        "masters/client_form.html",
        {
            "form": form,
            "mode": "create",
            "groups_opts": _group_options_for_client_form(None),
            "cancel_url": reverse("client_list"),
            "breadcrumbs": ui_breadcrumbs(("Client Master", "client_list"), ("New client",)),
        },
    )


@require_perm("masters.change_client")
def client_edit(request, client_id: str):
    client = get_object_or_404(client_master_queryset_for_user(request.user), pk=client_id)
    if request.method == "POST":
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            client = form.save(commit=False)
            _apply_updated_client_approval(client, request.user)
            client.save()
            log_client_activity(
                client=client,
                user=request.user,
                category=ClientActivityLog.CATEGORY_CLIENT,
                activity="Client master updated.",
                remarks=client.remarks,
            )
            if client.approval_status == Client.APPROVED:
                messages.success(request, "Client updated.")
            else:
                messages.success(
                    request,
                    "Changes saved and this client is pending approval again before use elsewhere in the system.",
                )
            return redirect("client_list")
    else:
        form = ClientForm(instance=client)
    ctx = {
        "form": form,
        "mode": "edit",
        "client": client,
        "groups_opts": _group_options_for_client_form(client),
        "cancel_url": reverse("client_list"),
        "breadcrumbs": ui_breadcrumbs(
            ("Client Master", "client_list"),
            (f"Edit {client.client_id}",),
        ),
    }
    if request.user.has_perm("masters.view_client"):
        can_link_tasks = task_module_enabled() and (
            request.user.is_superuser or request.user.has_perm("tasks.view_task")
        )
        logs = get_client_activity_timeline(client)
        ctx["activity_rows"] = build_client_activity_list_rows(logs, can_link_tasks=can_link_tasks)
        ctx["enable_task_module"] = task_module_enabled()
    return render(request, "masters/client_form.html", ctx)


@require_perm("masters.delete_client")
def client_delete(request, client_id: str):
    client = get_object_or_404(client_master_queryset_for_user(request.user), pk=client_id)
    if request.method == "POST":
        log_client_activity(
            client=client,
            user=request.user,
            category=ClientActivityLog.CATEGORY_CLIENT,
            activity="Client master deleted.",
            remarks=client.remarks,
        )
        try:
            client.delete()
        except ProtectedError:
            messages.error(
                request,
                "This client cannot be deleted while it is still used by MIS records (fees, receipts, or expenses), "
                "director mappings, or DIR-3 KYC records. Remove or change those records first, then try again.",
            )
            return redirect("client_list")
        messages.success(request, f"Client deleted: {client_id}.")
        return redirect("client_list")
    return render(request, "masters/client_confirm_delete.html", {"client": client})


@require_perm("masters.approve_client")
def client_pending_list(request):
    pending = (
        Client.objects.filter(approval_status=Client.PENDING)
        .select_related("created_by")
        .order_by("created_at", "client_name")
    )
    return render(request, "masters/client_pending_list.html", {"pending_clients": pending})


@require_perm("masters.approve_client")
def client_approve(request, client_id: str):
    if request.method != "POST":
        return redirect("client_pending_list")
    client = get_object_or_404(Client, pk=client_id, approval_status=Client.PENDING)
    if not user_may_approve_pending_client(request.user, client):
        messages.error(request, "You cannot approve a client record that you created. Another approver must review it.")
        return redirect("client_pending_list")
    now = timezone.now()
    client.approval_status = Client.APPROVED
    client.approved_by = request.user
    client.approved_at = now
    client.save(update_fields=["approval_status", "approved_by", "approved_at", "updated_at"])
    log_client_activity(
        client=client,
        user=request.user,
        category=ClientActivityLog.CATEGORY_CLIENT,
        activity="Client master approved.",
        remarks=client.remarks,
    )
    messages.success(request, f"Client {client.client_id} approved.")
    return redirect("client_pending_list")


@require_perm("masters.approve_client")
def client_reject(request, client_id: str):
    if request.method != "POST":
        return redirect("client_pending_list")
    client = get_object_or_404(Client, pk=client_id, approval_status=Client.PENDING)
    if not user_may_approve_pending_client(request.user, client):
        messages.error(request, "You cannot reject a client record that you created. Another approver must review it.")
        return redirect("client_pending_list")
    cid = client.client_id
    cname = client.client_name
    log_client_activity(
        client=client,
        user=request.user,
        category=ClientActivityLog.CATEGORY_CLIENT,
        activity="Client master rejected and removed from approval queue.",
        remarks=(request.POST.get("reject_remarks") or "").strip() or client.remarks,
    )
    try:
        client.delete()
    except ProtectedError:
        messages.error(
            request,
            f"Cannot reject {cid}: this client is already used in MIS, director mapping, or DIR-3 KYC. "
            "Remove or change those links first, or edit the client record instead.",
        )
        return redirect("client_pending_list")
    messages.success(request, f"Client {cid} ({cname}) rejected and removed from pending approvals.")
    return redirect("client_pending_list")


@require_perm("masters.add_client")
def client_import(request):
    """
    Step 1 (POST): upload CSV -> preview
    Step 2 (POST confirm): create records (all-or-nothing)
    """
    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = request.session.get("client_import_csv")
        if not raw:
            messages.error(request, "Nothing to import. Please upload CSV again.")
            return redirect("client_import")

        rows, file_errors = parse_clients_csv(raw.encode("utf-8"))
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("client_import")

        bad = [r for r in rows if r.errors]
        if bad:
            messages.error(request, "CSV has errors. Please fix and re-upload.")
            return render(
                request,
                "masters/client_import_preview.html",
                {
                    "rows": rows,
                    "error_rows": [r for r in rows if r.errors],
                    "total_rows": len(rows),
                    "error_count": sum(1 for r in rows if r.errors),
                    "file_errors": file_errors,
                    "columns": CSV_COLUMNS,
                    "can_import": False,
                },
            )

        with transaction.atomic():
            for r in rows:
                c = Client(**r.data)
                _apply_new_client_approval(c, request.user)
                c.save()
                if c.approval_status == Client.APPROVED:
                    log_client_activity(
                        client=c,
                        user=request.user,
                        category=ClientActivityLog.CATEGORY_CLIENT,
                        activity=f"Client master created ({c.client_id}) via import.",
                    )
                else:
                    log_client_activity(
                        client=c,
                        user=request.user,
                        category=ClientActivityLog.CATEGORY_CLIENT,
                        activity=(
                            f"Client master created ({c.client_id}) via import and is pending approval."
                        ),
                    )

        request.session.pop("client_import_csv", None)
        if request.user.is_superuser:
            messages.success(request, f"Imported {len(rows)} clients successfully.")
        else:
            messages.success(
                request,
                f"Imported {len(rows)} client(s). They are pending approval before use in MIS, director mapping, or DIR-3 KYC.",
            )
        return redirect("client_list")

    if request.method == "POST":
        f = request.FILES.get("csv_file")
        if not f:
            messages.error(request, "Please choose a CSV file.")
            return redirect("client_import")

        raw_bytes = f.read()
        try:
            rows, file_errors = parse_clients_csv(raw_bytes)
        except Exception as e:
            messages.error(request, f"Could not read CSV file: {e}")
            return redirect("client_import")
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("client_import")

        # Store a UTF-8 copy in session for confirm step
        try:
            request.session["client_import_csv"] = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            request.session["client_import_csv"] = raw_bytes.decode("cp1252", errors="replace")

        can_import = all(len(r.errors) == 0 for r in rows) and len(rows) > 0
        if can_import:
            messages.success(request, f"File uploaded successfully. {len(rows)} rows are ready to import.")
        else:
            bad_count = sum(1 for r in rows if r.errors)
            messages.error(request, f"File uploaded, but {bad_count} row(s) have errors. Please fix them and re-upload.")
        return render(
            request,
            "masters/client_import_preview.html",
            {
                "rows": rows,
                "error_rows": [r for r in rows if r.errors],
                "total_rows": len(rows),
                "error_count": sum(1 for r in rows if r.errors),
                "file_errors": file_errors,
                "columns": CSV_COLUMNS,
                "can_import": can_import,
            },
        )

    return render(request, "masters/client_import.html", {"columns": CSV_COLUMNS})


@require_perm("masters.add_client")
def client_import_template(request):
    header = CSV_COLUMNS
    sample_rows = [
        [
            "Private Limited",
            "Trivandrum",
            "ABC PRIVATE LIMITED",
            "",
            "",
            "ABCDE1234F",
            "",
            "",
            "",
            "U12345MH2026PLC123456",
            "",
            "",
            "Address line",
            "Mr X",
            "9999999999",
            "test@example.com",
            "",
            "",
        ],
        [
            "LLP",
            "Nagercoil",
            "XYZ LLP",
            "",
            "",
            "AAAAA9999A",
            "27AAAAA9999A1Z5",
            "",
            "ABC-1234",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
        [
            "Individual",
            "Trivandrum",
            "RAHUL SHARMA",
            "",
            "",
            "BBBBB1111B",
            "",
            "10-05-1995",
            "",
            "",
            "YES",
            "12345678",
            "",
            "",
            "",
            "",
            "",
            "",
        ],
        [
            "Foreign Citizen",
            "Trivandrum",
            "JOHN SMITH",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "Flat 1, Example Street",
            "JOHN SMITH",
            "9999999999",
            "john@example.com",
            "A1234567",
            "",
        ],
    ]

    # Build CSV safely (always quote cells)
    def q(v: str) -> str:
        s = (v or "").replace('"', '""')
        return f'"{s}"'

    lines = []
    lines.append(",".join(q(c) for c in header))
    for row in sample_rows:
        lines.append(",".join(q(str(c)) for c in row))
    content = "\r\n".join(lines) + "\r\n"

    resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="client-master-template.csv"'
    return resp


@require_perm("masters.view_directormapping")
def director_list(request):
    q = (request.GET.get("q") or "").strip().upper()
    from core.branch_access import filter_director_mapping_qs

    qs = filter_director_mapping_qs(
        DirectorMapping.objects.select_related("director", "company").all(),
        request.user,
    )
    if q:
        qs = qs.filter(
            Q(director__client_name__icontains=q)
            | Q(director__din__icontains=q)
            | Q(company__client_name__icontains=q)
            | Q(company__client_id__icontains=q)
            | Q(company__cin__icontains=q)
            | Q(company__llpin__icontains=q)
        )
    qs = qs.order_by("-appointed_date", "company__client_name")
    return render(
        request,
        "masters/director_list.html",
        {"mappings": qs, "q": q, "breadcrumbs": ui_breadcrumbs(("Director Mapping",))},
    )


def _dm_director_queryset(user=None):
    from core.branch_access import approved_clients_for_user

    return (
        approved_clients_for_user(user)
        .filter(client_type__in=sorted(DIRECTOR_ELIGIBLE_CLIENT_TYPES), is_director=True)
        .exclude(din="")
        .order_by("client_name")
    )


def _dm_company_queryset(user=None):
    from core.branch_access import approved_clients_for_user

    return approved_clients_for_user(user).filter(client_type__in=sorted(DIRECTOR_COMPANY_TYPES)).order_by("client_name")


def _director_mapping_activity(*, mapping: DirectorMapping, verb: str) -> str:
    director_name = (mapping.director.client_name or "").strip() or mapping.director_id
    parts = [f"Director mapping {verb}: {director_name}"]
    if mapping.appointed_date:
        parts.append(f"appointed {mapping.appointed_date:%d-%m-%Y}")
    if mapping.cessation_date:
        parts.append(f"cessation {mapping.cessation_date:%d-%m-%Y}")
    return ". ".join(parts) + "."


def _log_director_mapping_company(*, company: Client, user, mapping: DirectorMapping, verb: str) -> None:
    log_client_activity(
        client=company,
        user=user,
        category=ClientActivityLog.CATEGORY_DIRECTOR,
        activity=_director_mapping_activity(mapping=mapping, verb=verb),
        remarks=mapping.remarks or "",
        metadata={"director_mapping_id": mapping.pk, "director_id": mapping.director_id},
    )


def _dm_client_options_json(qs, *, kind: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for c in qs:
        if kind == "director":
            label = f"{(c.client_name or '').strip()} — DIN {(c.din or '').strip()} — {c.pk}"
        else:
            name = (c.client_name or "").strip()
            label = f"{name} — {c.pk} ({c.client_type})"
            if (c.cin or "").strip():
                label += f" — CIN {c.cin.strip().upper()}"
            if (c.llpin or "").strip():
                label += f" · LLPIN {c.llpin.strip().upper()}"
        out.append({"id": str(c.pk), "label": label})
    return out


@require_perm("masters.add_directormapping")
def director_create(request):
    dir_qs = _dm_director_queryset(request.user)
    comp_qs = _dm_company_queryset(request.user)
    directors_opts = _dm_client_options_json(dir_qs, kind="director")
    companies_opts = _dm_client_options_json(comp_qs, kind="company")

    if request.method == "POST":
        company_form = DirectorCompanyPickForm(request.POST, prefix="co", user=request.user)
        formset = DirectorMappingRowFormSet(
            request.POST,
            prefix="lines",
            form_kwargs={"director_queryset": dir_qs},
        )
        if company_form.is_valid() and formset.is_valid():
            company = company_form.cleaned_data["company"]
            created = 0
            try:
                with transaction.atomic():
                    for form in formset.forms:
                        if not form.cleaned_data:
                            continue
                        director = form.cleaned_data.get("director")
                        appointed = form.cleaned_data.get("appointed_date")
                        if not director:
                            continue
                        m = DirectorMapping(
                            company=company,
                            director=director,
                            appointed_date=appointed or None,
                            cessation_date=form.cleaned_data.get("cessation_date") or None,
                            reason_for_cessation=(form.cleaned_data.get("reason_for_cessation") or "").strip() or "",
                            remarks=(form.cleaned_data.get("remarks") or "").strip(),
                        )
                        m.full_clean()
                        m.save()
                        _log_director_mapping_company(
                            company=company,
                            user=request.user,
                            mapping=m,
                            verb="added",
                        )
                        created += 1
            except ValidationError as ve:
                msgs = []
                if hasattr(ve, "message_dict") and ve.message_dict:
                    for mlist in ve.message_dict.values():
                        msgs.extend(mlist)
                else:
                    msgs = list(ve.messages)
                for msg in msgs:
                    messages.error(request, msg)
                return render(
                    request,
                    "masters/director_create_multi.html",
                    _director_create_multi_context(
                        company_form,
                        formset,
                        directors_opts,
                        companies_opts,
                    ),
                )
            except IntegrityError:
                messages.error(
                    request,
                    "Could not save one of the rows (duplicate director + company + same appointed date, or database constraint).",
                )
                return render(
                    request,
                    "masters/director_create_multi.html",
                    _director_create_multi_context(
                        company_form,
                        formset,
                        directors_opts,
                        companies_opts,
                    ),
                )

            messages.success(request, f"Saved {created} director mapping(s) for {company.client_name}.")
            return redirect("director_list")
    else:
        company_form = DirectorCompanyPickForm(prefix="co", user=request.user)
        formset = DirectorMappingRowFormSet(
            prefix="lines",
            form_kwargs={"director_queryset": dir_qs},
            initial=[{}],
        )

    return render(
        request,
        "masters/director_create_multi.html",
        _director_create_multi_context(company_form, formset, directors_opts, companies_opts),
    )


def _director_create_multi_context(company_form, formset, directors_opts, companies_opts):
    return {
        "company_form": company_form,
        "formset": formset,
        "directors_opts": directors_opts,
        "companies_opts": companies_opts,
        "cancel_url": reverse("director_list"),
        "breadcrumbs": ui_breadcrumbs(
            ("Director Mapping", "director_list"),
            ("New mappings",),
        ),
    }


@require_perm("masters.change_directormapping")
def director_edit(request, pk: int):
    from core.branch_access import filter_director_mapping_qs

    director = get_object_or_404(filter_director_mapping_qs(DirectorMapping.objects.all(), request.user), pk=pk)
    if request.method == "POST":
        form = DirectorForm(request.POST, instance=director, user=request.user)
        if form.is_valid():
            mapping = form.save()
            _log_director_mapping_company(
                company=mapping.company,
                user=request.user,
                mapping=mapping,
                verb="updated",
            )
            messages.success(request, "Director mapping updated.")
            return redirect("director_list")
    else:
        form = DirectorForm(instance=director, user=request.user)
    return render(
        request,
        "masters/director_form.html",
        {
            "form": form,
            "mode": "edit",
            "mapping": director,
            "cancel_url": reverse("director_list"),
            "breadcrumbs": ui_breadcrumbs(
                ("Director Mapping", "director_list"),
                ("Edit mapping",),
            ),
        },
    )


@require_perm("masters.delete_directormapping")
def director_delete(request, pk: int):
    from core.branch_access import filter_director_mapping_qs

    mapping = get_object_or_404(filter_director_mapping_qs(DirectorMapping.objects.all(), request.user), pk=pk)
    if request.method == "POST":
        _log_director_mapping_company(
            company=mapping.company,
            user=request.user,
            mapping=mapping,
            verb="removed",
        )
        mapping.delete()
        messages.success(request, "Director mapping deleted.")
        return redirect("director_list")
    return render(request, "masters/director_confirm_delete.html", {"mapping": mapping})


def _dm_session_put_file(request, key: str, raw_bytes: bytes) -> None:
    request.session[key] = base64.b64encode(raw_bytes).decode("ascii")


def _dm_session_get_file(request, key: str) -> bytes | None:
    s = request.session.get(key)
    if not s:
        return None
    try:
        return base64.b64decode(s.encode("ascii"))
    except Exception:
        return None


def _director_mapping_csv_template_response(filename: str, header: list[str], sample_rows: list[list[str]]):
    def q(v: str) -> str:
        s = (v or "").replace('"', '""')
        return f'"{s}"'

    lines = [",".join(q(c) for c in header)]
    for row in sample_rows:
        lines.append(",".join(q(str(c)) for c in row))
    content = "\r\n".join(lines) + "\r\n"
    resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@require_perm("masters.add_directormapping")
def director_mapping_bulk_import_template(request):
    header = DIRECTOR_MAPPING_CSV_HEADERS
    sample = [
        [
            "A00001",
            "01234567",
            "JOHN DIRECTOR",
            "BT0001",
            "ABC PRIVATE LIMITED",
            "2024-04-01",
            "",
            "",
        ],
        [
            "A00002",
            "07654321",
            "JANE SMITH",
            "BT0002",
            "XYZ LLP",
            "2023-01-15",
            "2025-03-31",
            "Resigned",
        ],
    ]
    return _director_mapping_csv_template_response("director-mapping-bulk-template.csv", header, sample)


@require_perm("masters.add_directormapping")
def director_mapping_bulk_import(request):
    session_key = "director_mapping_bulk_import_file"

    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = _dm_session_get_file(request, session_key)
        if not raw:
            messages.error(request, "Nothing to import. Please upload the file again.")
            return redirect("director_mapping_bulk_import")
        rows, file_errors = parse_director_mappings_csv(raw)
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("director_mapping_bulk_import")
        attach_client_master_validation(rows)
        validate_director_mapping_import_active_uniqueness_in_file(rows)
        bad = [r for r in rows if r.errors]
        if bad:
            messages.error(request, "File has errors. Fix and re-upload.")
            return render(
                request,
                "masters/director_mapping_import_preview.html",
                {
                    "rows": rows,
                    "error_rows": bad,
                    "total_rows": len(rows),
                    "file_errors": file_errors,
                    "can_import": False,
                },
            )
        with transaction.atomic():
            for row in rows:
                d = row.data
                dir_client = Client.approved_objects().get(client_id__iexact=d["director_client_id"])
                comp_client = Client.approved_objects().get(client_id__iexact=d["company_client_id"])
                obj = DirectorMapping(
                    director=dir_client,
                    company=comp_client,
                    appointed_date=d["appointed_date"],
                    cessation_date=d["cessation_date"],
                    reason_for_cessation=(d["reason_for_cessation"] or "").strip(),
                )
                obj.full_clean()
                obj.save()
                _log_director_mapping_company(
                    company=comp_client,
                    user=request.user,
                    mapping=obj,
                    verb="added via import",
                )
        request.session.pop(session_key, None)
        messages.success(request, f"Imported {len(rows)} director mapping(s).")
        return redirect("director_list")

    if request.method == "POST":
        f = request.FILES.get("upload_file")
        if not f:
            messages.error(request, "Please choose a CSV file (.csv).")
            return redirect("director_mapping_bulk_import")
        raw = f.read()
        _dm_session_put_file(request, session_key, raw)
        rows, file_errors = parse_director_mappings_csv(raw)
        if not file_errors:
            attach_client_master_validation(rows)
            validate_director_mapping_import_active_uniqueness_in_file(rows)
        can_import = bool(rows) and all(not r.errors for r in rows) and not file_errors
        error_rows = [r for r in rows if r.errors]
        return render(
            request,
            "masters/director_mapping_import_preview.html",
            {
                "rows": rows,
                "error_rows": error_rows,
                "total_rows": len(rows),
                "file_errors": file_errors,
                "can_import": can_import,
            },
        )

    return render(request, "masters/director_mapping_import.html")


@require_perm("masters.view_clientgroup")
def client_group_list(request):
    q = (request.GET.get("q") or "").strip()
    groups = ClientGroup.objects.all().order_by("name")
    if q:
        qu = q.upper()
        groups = groups.filter(
            Q(name__icontains=qu) | Q(group_id__icontains=qu) | Q(notes__icontains=q)
        )
    return render(request, "masters/client_group_list.html", {"groups": groups, "q": q})


@require_perm("masters.add_clientgroup")
def client_group_create(request):
    if request.method == "POST":
        form = ClientGroupForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Group created: {obj.group_id} — {obj.name}")
            return redirect("client_group_list")
    else:
        form = ClientGroupForm()
    return render(request, "masters/client_group_form.html", {"form": form, "mode": "create"})


@require_perm("masters.change_clientgroup")
def client_group_edit(request, pk: int):
    obj = get_object_or_404(ClientGroup, pk=pk)
    if request.method == "POST":
        form = ClientGroupForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Group updated.")
            return redirect("client_group_list")
    else:
        form = ClientGroupForm(instance=obj)
    return render(
        request,
        "masters/client_group_form.html",
        {"form": form, "mode": "edit", "group": obj},
    )


@require_perm("masters.delete_clientgroup")
def client_group_delete(request, pk: int):
    obj = get_object_or_404(ClientGroup, pk=pk)
    if request.method == "POST":
        try:
            obj.delete()
        except ProtectedError:
            messages.error(
                request,
                "This group cannot be deleted while clients are linked to it. "
                "Reassign or clear those clients in Client Master first.",
            )
            return redirect("client_group_edit", pk=pk)
        messages.success(request, "Group deleted.")
        return redirect("client_group_list")
    return render(request, "masters/client_group_delete_confirm.html", {"group": obj})


@login_required
def client_group_bulk_delete(request):
    """Superuser only: delete multiple groups from Group Master."""
    if not request.user.is_superuser:
        raise PermissionDenied

    if request.method != "POST":
        return redirect("client_group_list")

    ids = []
    for raw in request.POST.getlist("group_ids"):
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not ids:
        messages.warning(request, "Select at least one group to delete.")
        return redirect("client_group_list")

    if request.POST.get("confirm") == "1":
        groups = list(ClientGroup.objects.filter(pk__in=ids).order_by("name"))
        deleted = 0
        blocked: list[ClientGroup] = []
        for g in groups:
            try:
                g.delete()
                deleted += 1
            except ProtectedError:
                blocked.append(g)
        if deleted:
            messages.success(request, f"Deleted {deleted} group(s).")
        if blocked:
            sample = ", ".join(f"{g.group_id} ({g.name})" for g in blocked[:5])
            extra = f" (+{len(blocked) - 5} more)" if len(blocked) > 5 else ""
            messages.error(
                request,
                f"Could not delete {len(blocked)} group(s) still linked to clients: {sample}{extra}. "
                "Clear or reassign those clients in Client Master first.",
            )
        return redirect("client_group_list")

    groups = (
        ClientGroup.objects.filter(pk__in=ids)
        .annotate(client_count=Count("clients"))
        .order_by("name")
    )
    return render(
        request,
        "masters/client_group_bulk_delete_confirm.html",
        {"groups": groups},
    )


@require_perm("masters.add_clientgroup")
def client_group_bulk_import(request):
    """
    Step 1 (POST): upload CSV -> preview
    Step 2 (POST confirm): create all groups (all-or-nothing)
    """
    session_key = "client_group_import_csv"

    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = request.session.get(session_key)
        if not raw:
            messages.error(request, "Nothing to import. Please upload the CSV again.")
            return redirect("client_group_bulk_import")

        rows, file_errors = parse_client_groups_csv(raw.encode("utf-8"))
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("client_group_bulk_import")

        bad = [r for r in rows if r.errors]
        if bad:
            messages.error(request, "CSV has errors. Please fix and re-upload.")
            return render(
                request,
                "masters/client_group_import_preview.html",
                {
                    "rows": rows,
                    "error_rows": [r for r in rows if r.errors],
                    "total_rows": len(rows),
                    "error_count": sum(1 for r in rows if r.errors),
                    "file_errors": file_errors,
                    "columns": GROUP_CSV_COLUMNS,
                    "can_import": False,
                },
            )

        with transaction.atomic():
            for r in rows:
                ClientGroup(**r.data).save()

        request.session.pop(session_key, None)
        messages.success(request, f"Imported {len(rows)} group(s).")
        return redirect("client_group_list")

    if request.method == "POST":
        f = request.FILES.get("csv_file")
        if not f:
            messages.error(request, "Please choose a CSV file.")
            return redirect("client_group_bulk_import")

        raw_bytes = f.read()
        try:
            rows, file_errors = parse_client_groups_csv(raw_bytes)
        except Exception as e:
            messages.error(request, f"Could not read CSV file: {e}")
            return redirect("client_group_bulk_import")
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("client_group_bulk_import")

        try:
            request.session[session_key] = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            request.session[session_key] = raw_bytes.decode("cp1252", errors="replace")

        can_import = bool(rows) and all(len(r.errors) == 0 for r in rows)
        if can_import:
            messages.success(request, f"File uploaded successfully. {len(rows)} row(s) are ready to import.")
        else:
            bad_count = sum(1 for r in rows if r.errors)
            messages.error(
                request,
                f"File uploaded, but {bad_count} row(s) have errors. Please fix them and re-upload.",
            )
        return render(
            request,
            "masters/client_group_import_preview.html",
            {
                "rows": rows,
                "error_rows": [r for r in rows if r.errors],
                "total_rows": len(rows),
                "error_count": sum(1 for r in rows if r.errors),
                "file_errors": file_errors,
                "columns": GROUP_CSV_COLUMNS,
                "can_import": can_import,
            },
        )

    return render(request, "masters/client_group_import.html", {"columns": GROUP_CSV_COLUMNS})


@require_perm("masters.add_clientgroup")
def client_group_bulk_import_template(request):
    header = GROUP_CSV_COLUMNS
    sample_rows = [
        ["JC", "Example: first J group", "YES"],
        ["JACK LLP", "", ""],
        ["ALPHA HOLDINGS", "Notes optional", "NO"],
    ]

    def q(v: str) -> str:
        s = (v or "").replace('"', '""')
        return f'"{s}"'

    lines = [",".join(q(c) for c in header)]
    for row in sample_rows:
        lines.append(",".join(q(str(c)) for c in row))
    content = "\r\n".join(lines) + "\r\n"

    resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="group-master-template.csv"'
    return resp


def _portal_password_qs_for_user(user):
    qs = ClientPortalCredential.objects.select_related("portal", "client", "created_by", "updated_by")
    client_ids = client_master_queryset_for_user(user).values_list("pk", flat=True)
    return qs.filter(client_id__in=client_ids)


@require_perm("masters.view_clientportalcredential")
def portal_password_list(request):
    q = (request.GET.get("q") or "").strip()
    qs = _portal_password_qs_for_user(request.user)
    if q:
        qu = q.upper()
        qs = qs.filter(
            Q(client__client_name__icontains=q)
            | Q(client__pan__icontains=qu)
            | Q(client__client_id__icontains=qu)
            | Q(portal__name__icontains=q)
            | Q(portal_username__icontains=q)
        )
    rows = qs.order_by("-updated_at")[:500]
    return render(
        request,
        "masters/portal_password_list.html",
        {
            "rows": rows,
            "q": q,
            "breadcrumbs": ui_breadcrumbs(("Password management",)),
        },
    )


@require_perm("masters.add_clientportalcredential")
def portal_password_create(request):
    if request.method == "POST":
        form = ClientPortalCredentialForm(request.POST, user=request.user)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.created_by = request.user
            obj.updated_by = request.user
            obj.save()
            messages.success(request, "Portal password saved.")
            return redirect("portal_password_list")
    else:
        form = ClientPortalCredentialForm(user=request.user)
    return render(
        request,
        "masters/portal_password_form.html",
        {
            "form": form,
            "mode": "create",
            "cancel_url": reverse("portal_password_list"),
            "can_add_portal_name": request.user.is_superuser or request.user.has_perm("masters.add_portalname"),
            "breadcrumbs": ui_breadcrumbs(
                ("Password management", "portal_password_list"),
                ("New entry",),
            ),
        },
    )


@require_perm("masters.change_clientportalcredential")
def portal_password_edit(request, pk: int):
    obj = get_object_or_404(_portal_password_qs_for_user(request.user), pk=pk)
    if request.method == "POST":
        form = ClientPortalCredentialForm(request.POST, instance=obj, user=request.user)
        if form.is_valid():
            row = form.save(commit=False)
            row.updated_by = request.user
            row.save()
            messages.success(request, "Portal password updated.")
            return redirect("portal_password_list")
    else:
        form = ClientPortalCredentialForm(instance=obj, user=request.user)
        if obj.client_id:
            pan = (obj.client.pan or "").strip().upper()
            name = obj.client.client_name or ""
            form.fields["client_search"].initial = f"{name} — {pan}" if pan else name
    return render(
        request,
        "masters/portal_password_form.html",
        {
            "form": form,
            "mode": "edit",
            "obj": obj,
            "cancel_url": reverse("portal_password_list"),
            "can_add_portal_name": request.user.is_superuser or request.user.has_perm("masters.add_portalname"),
            "breadcrumbs": ui_breadcrumbs(
                ("Password management", "portal_password_list"),
                (f"Edit {obj.portal.name}",),
            ),
        },
    )


@require_perm("masters.add_portalname")
def portal_name_create_api(request):
    if request.method != "POST":
        return JsonResponse({"detail": "POST required."}, status=405)
    name = (request.POST.get("name") or "").strip()
    if not name:
        return JsonResponse({"detail": "Portal name is required."}, status=400)
    existing = PortalName.objects.filter(name__iexact=name).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.save(update_fields=["is_active"])
        return JsonResponse({"id": existing.pk, "name": existing.name, "created": False})
    portal = PortalName.objects.create(name=name)
    return JsonResponse({"id": portal.pk, "name": portal.name, "created": True})


@require_perm("masters.delete_clientportalcredential")
def portal_password_delete(request, pk: int):
    obj = get_object_or_404(_portal_password_qs_for_user(request.user), pk=pk)
    if request.method == "POST":
        label = str(obj)
        obj.delete()
        messages.success(request, f"Deleted: {label}.")
        return redirect("portal_password_list")
    return render(request, "masters/portal_password_confirm_delete.html", {"obj": obj})


def _dsc_client_ids_for_user(user):
    return individual_clients_for_user(user).values_list("pk", flat=True)


def _dsc_qs_for_user(user):
    return ClientDSC.objects.select_related("client", "created_by", "updated_by").filter(
        client_id__in=_dsc_client_ids_for_user(user)
    )


def _dsc_inout_qs_for_user(user):
    return DSCInOut.objects.select_related("dsc", "dsc__client").filter(dsc__client_id__in=_dsc_client_ids_for_user(user))


@require_perm("masters.view_clientdsc")
def dsc_list(request):
    q = (request.GET.get("q") or "").strip()
    qs = _dsc_qs_for_user(request.user)
    if q:
        qu = q.upper()
        qs = qs.filter(
            Q(client__client_name__icontains=q)
            | Q(client__pan__icontains=qu)
            | Q(client__client_id__icontains=qu)
        )
    rows = qs.order_by("-created_at")[:500]
    return render(
        request,
        "masters/dsc_list.html",
        {
            "rows": rows,
            "q": q,
            "breadcrumbs": ui_breadcrumbs(("DSC Management",), ("New DSC",)),
        },
    )


@require_perm("masters.add_clientdsc")
def dsc_create(request):
    if request.method == "POST":
        form = ClientDSCForm(request.POST, user=request.user)
        if form.is_valid():
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.created_by = request.user
                obj.updated_by = request.user
                obj.save()
                DSCInOut.objects.create(dsc=obj, in_date=timezone.localdate(obj.created_at))
            messages.success(request, "DSC saved. In-out record created with in date set to the creation date.")
            return redirect("dsc_list")
    else:
        form = ClientDSCForm(user=request.user)
    return render(
        request,
        "masters/dsc_form.html",
        {
            "form": form,
            "mode": "create",
            "cancel_url": reverse("dsc_list"),
            "breadcrumbs": ui_breadcrumbs(
                ("DSC Management",),
                ("New DSC", "dsc_list"),
                ("Add",),
            ),
        },
    )


@require_perm("masters.change_clientdsc")
def dsc_edit(request, pk: int):
    obj = get_object_or_404(_dsc_qs_for_user(request.user), pk=pk)
    if request.method == "POST":
        was_notify = obj.expiry_notification
        form = ClientDSCForm(request.POST, instance=obj, user=request.user)
        if form.is_valid():
            row = form.save(commit=False)
            row.updated_by = request.user
            row.save()
            if row.expiry_notification and not was_notify:
                reset_dsc_expiry_notification_schedule(row)
            messages.success(request, "DSC updated.")
            return redirect("dsc_list")
    else:
        form = ClientDSCForm(instance=obj, user=request.user)
        if obj.client_id:
            pan = (obj.client.pan or "").strip().upper()
            name = obj.client.client_name or ""
            form.fields["client_search"].initial = f"{name} — {pan}" if pan else name
    return render(
        request,
        "masters/dsc_form.html",
        {
            "form": form,
            "mode": "edit",
            "obj": obj,
            "cancel_url": reverse("dsc_list"),
            "breadcrumbs": ui_breadcrumbs(
                ("DSC Management",),
                ("New DSC", "dsc_list"),
                (obj.client.client_name,),
            ),
        },
    )


@require_perm("masters.delete_clientdsc")
def dsc_delete(request, pk: int):
    obj = get_object_or_404(_dsc_qs_for_user(request.user), pk=pk)
    if request.method == "POST":
        label = str(obj)
        obj.delete()
        messages.success(request, f"Deleted: {label}.")
        return redirect("dsc_list")
    return render(request, "masters/dsc_confirm_delete.html", {"obj": obj})


@require_perm("masters.view_dscinout")
def dsc_inout_list(request):
    q = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    today = timezone.localdate()
    qs = _dsc_inout_qs_for_user(request.user)
    if q:
        qu = q.upper()
        qs = qs.filter(
            Q(dsc__client__client_name__icontains=q)
            | Q(dsc__client__pan__icontains=qu)
            | Q(dsc__client__client_id__icontains=qu)
        )
    if status == "in_office":
        qs = qs.filter(out_date__isnull=True)
    elif status == "with_client":
        qs = qs.filter(out_date__isnull=False)
    elif status == "active_dsc":
        qs = qs.filter(dsc__expiry_date__gt=today)
    rows = qs.order_by("-in_date", "-pk")[:500]
    return render(
        request,
        "masters/dsc_inout_list.html",
        {
            "rows": rows,
            "q": q,
            "status": status,
            "today": today,
            "breadcrumbs": ui_breadcrumbs(("DSC Management",), ("DSC In-Out",)),
        },
    )


@require_perm("masters.change_dscinout")
def dsc_inout_edit(request, pk: int):
    obj = get_object_or_404(_dsc_inout_qs_for_user(request.user), pk=pk)
    if request.method == "POST":
        form = DSCInOutForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "DSC in-out updated.")
            return redirect("dsc_inout_list")
    else:
        form = DSCInOutForm(instance=obj)
    return render(
        request,
        "masters/dsc_inout_form.html",
        {
            "form": form,
            "obj": obj,
            "cancel_url": reverse("dsc_inout_list"),
            "breadcrumbs": ui_breadcrumbs(
                ("DSC Management",),
                ("DSC In-Out", "dsc_inout_list"),
                (obj.dsc.client.client_name,),
            ),
        },
    )


@login_required
def dsc_notification_list(request):
    from .models import DSCNotification

    if not (
        request.user.is_superuser
        or request.user.has_perm("masters.view_clientdsc")
        or getattr(getattr(request.user, "employee_profile", None), "receive_dsc_expiry_notifications", False)
    ):
        raise PermissionDenied
    qs = DSCNotification.objects.filter(user=request.user).select_related("dsc", "dsc__client")[:200]
    return render(request, "masters/dsc_notification_list.html", {"notifications": qs})


@login_required
@require_POST
def dsc_notification_mark_read(request, pk: int):
    from .models import DSCNotification

    n = get_object_or_404(DSCNotification, pk=pk, user=request.user)
    n.is_read = True
    n.read_at = timezone.now()
    n.save(update_fields=["is_read", "read_at"])
    if n.link:
        return redirect(n.link)
    return redirect("dsc_notification_list")


def _masters_bulk_csv_preview_context(
    *,
    rows,
    preview_columns,
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
        "preview_columns": preview_columns,
        "upload_url_name": upload_url_name,
        "preview_title": preview_title,
        "preview_page_title": preview_page_title,
        "success_hint": success_hint,
    }


EXPENSE_CATEGORY_IMPORT_SESSION_KEY = "expense_category_import_csv"


@require_perm("masters.add_expensecategory")
def expense_category_bulk_import(request):
    from .expense_category_csv_import import EXPENSE_CATEGORY_CSV_COLUMNS, parse_expense_categories_csv

    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = request.session.get(EXPENSE_CATEGORY_IMPORT_SESSION_KEY)
        if not raw:
            messages.error(request, "Nothing to import. Please upload the CSV again.")
            return redirect("expense_category_bulk_import")
        rows, file_errors = parse_expense_categories_csv(raw.encode("utf-8"))
        if file_errors or any(r.errors for r in rows):
            messages.error(request, "Cannot import: fix validation errors and upload again.")
            return redirect("expense_category_bulk_import")
        with transaction.atomic():
            for r in rows:
                ExpenseCategory.objects.create(**r.data)
        request.session.pop(EXPENSE_CATEGORY_IMPORT_SESSION_KEY, None)
        messages.success(request, f"Imported {len(rows)} expense categor{'y' if len(rows) == 1 else 'ies'}.")
        return redirect("expense_category_list")

    if request.method == "POST":
        f = request.FILES.get("csv_file")
        if not f:
            messages.error(request, "Please choose a CSV file.")
            return redirect("expense_category_bulk_import")
        raw_bytes = f.read()
        rows, file_errors = parse_expense_categories_csv(raw_bytes)
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("expense_category_bulk_import")
        try:
            request.session[EXPENSE_CATEGORY_IMPORT_SESSION_KEY] = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            request.session[EXPENSE_CATEGORY_IMPORT_SESSION_KEY] = raw_bytes.decode("cp1252", errors="replace")
        ctx = _masters_bulk_csv_preview_context(
            rows=rows,
            preview_columns=["Name", "Active"],
            upload_url_name="expense_category_bulk_import",
            preview_title="Expense categories import",
            preview_page_title="Expense categories — Import preview",
            success_hint="Click Confirm import to create all categories.",
            cells_fn=lambda r: [r.data.get("name", ""), "Yes" if r.data.get("is_active") else "No"],
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
            "import_title": "Expense categories import",
            "import_page_title": "Expense categories — Bulk upload (CSV)",
            "import_description": "NAME is required. IS_ACTIVE is YES/NO or blank (defaults to YES).",
            "columns": EXPENSE_CATEGORY_CSV_COLUMNS,
            "template_url_name": "expense_category_bulk_import_template",
            "cancel_url_name": "expense_category_list",
        },
    )


@require_perm("masters.add_expensecategory")
def expense_category_bulk_import_template(request):
    from .expense_category_csv_import import EXPENSE_CATEGORY_CSV_COLUMNS

    def q(v: str) -> str:
        s = (v or "").replace('"', '""')
        return f'"{s}"'

    lines = [",".join(q(c) for c in EXPENSE_CATEGORY_CSV_COLUMNS)]
    for row in [["Office rent", "YES"], ["Travel", "YES"], ["Stationery", "NO"]]:
        lines.append(",".join(q(c) for c in row))
    content = "\r\n".join(lines) + "\r\n"
    resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="expense-categories-template.csv"'
    return resp


PORTAL_PASSWORD_IMPORT_SESSION_KEY = "portal_password_import_csv"


@require_perm("masters.add_clientportalcredential")
def portal_password_bulk_import(request):
    from .portal_password_csv_import import PORTAL_PASSWORD_CSV_COLUMNS, parse_portal_passwords_csv

    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = request.session.get(PORTAL_PASSWORD_IMPORT_SESSION_KEY)
        if not raw:
            messages.error(request, "Nothing to import. Please upload the CSV again.")
            return redirect("portal_password_bulk_import")
        rows, file_errors = parse_portal_passwords_csv(raw.encode("utf-8"), user=request.user)
        if file_errors or any(r.errors for r in rows):
            messages.error(request, "Cannot import: fix validation errors and upload again.")
            return redirect("portal_password_bulk_import")
        with transaction.atomic():
            for r in rows:
                d = dict(r.data)
                obj = ClientPortalCredential.objects.create(
                    client=d["client"],
                    portal=d["portal"],
                    portal_username=d["portal_username"],
                    portal_password=d["portal_password"],
                    created_by=request.user,
                    updated_by=request.user,
                )
        request.session.pop(PORTAL_PASSWORD_IMPORT_SESSION_KEY, None)
        messages.success(request, f"Imported {len(rows)} portal password(s).")
        return redirect("portal_password_list")

    if request.method == "POST":
        f = request.FILES.get("csv_file")
        if not f:
            messages.error(request, "Please choose a CSV file.")
            return redirect("portal_password_bulk_import")
        raw_bytes = f.read()
        rows, file_errors = parse_portal_passwords_csv(raw_bytes, user=request.user)
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("portal_password_bulk_import")
        try:
            request.session[PORTAL_PASSWORD_IMPORT_SESSION_KEY] = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            request.session[PORTAL_PASSWORD_IMPORT_SESSION_KEY] = raw_bytes.decode("cp1252", errors="replace")
        ctx = _masters_bulk_csv_preview_context(
            rows=rows,
            preview_columns=["Client", "Portal", "Username"],
            upload_url_name="portal_password_bulk_import",
            preview_title="Portal passwords import",
            preview_page_title="Password management — Import preview",
            success_hint="Portal names must exist in Portal names master (active). Click Confirm import to save.",
            cells_fn=lambda r: [
                r.data["client"].client_id if r.data.get("client") else "",
                r.data["portal"].name if r.data.get("portal") else "",
                r.data.get("portal_username", ""),
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
            "import_title": "Portal passwords import",
            "import_page_title": "Password management — Bulk upload (CSV)",
            "import_description": (
                "CLIENT_ID must be an approved client in your branch. "
                "PORTAL_NAME must match an active portal in Portal names master."
            ),
            "columns": PORTAL_PASSWORD_CSV_COLUMNS,
            "template_url_name": "portal_password_bulk_import_template",
            "cancel_url_name": "portal_password_list",
        },
    )


@require_perm("masters.add_clientportalcredential")
def portal_password_bulk_import_template(request):
    from .portal_password_csv_import import PORTAL_PASSWORD_CSV_COLUMNS

    def q(v: str) -> str:
        s = (v or "").replace('"', '""')
        return f'"{s}"'

    lines = [",".join(q(c) for c in PORTAL_PASSWORD_CSV_COLUMNS)]
    lines.append(",".join(q(c) for c in ["A00001", "GST", "gst_user", "secret123"]))
    content = "\r\n".join(lines) + "\r\n"
    resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="portal-passwords-template.csv"'
    return resp


DSC_IMPORT_SESSION_KEY = "dsc_import_csv"


@require_perm("masters.add_clientdsc")
def dsc_bulk_import(request):
    from .dsc_csv_import import DSC_CSV_COLUMNS, parse_dsc_csv

    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = request.session.get(DSC_IMPORT_SESSION_KEY)
        if not raw:
            messages.error(request, "Nothing to import. Please upload the CSV again.")
            return redirect("dsc_bulk_import")
        rows, file_errors = parse_dsc_csv(raw.encode("utf-8"), user=request.user)
        if file_errors or any(r.errors for r in rows):
            messages.error(request, "Cannot import: fix validation errors and upload again.")
            return redirect("dsc_bulk_import")
        with transaction.atomic():
            for r in rows:
                d = dict(r.data)
                obj = ClientDSC.objects.create(
                    client=d["client"],
                    issue_date=d["issue_date"],
                    expiry_date=d["expiry_date"],
                    expiry_notification=d["expiry_notification"],
                    dsc_password=d["dsc_password"],
                    created_by=request.user,
                    updated_by=request.user,
                )
                DSCInOut.objects.create(dsc=obj, in_date=timezone.localdate(obj.created_at))
        request.session.pop(DSC_IMPORT_SESSION_KEY, None)
        messages.success(request, f"Imported {len(rows)} DSC record(s). In-out entries created.")
        return redirect("dsc_list")

    if request.method == "POST":
        f = request.FILES.get("csv_file")
        if not f:
            messages.error(request, "Please choose a CSV file.")
            return redirect("dsc_bulk_import")
        raw_bytes = f.read()
        rows, file_errors = parse_dsc_csv(raw_bytes, user=request.user)
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("dsc_bulk_import")
        try:
            request.session[DSC_IMPORT_SESSION_KEY] = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            request.session[DSC_IMPORT_SESSION_KEY] = raw_bytes.decode("cp1252", errors="replace")
        ctx = _masters_bulk_csv_preview_context(
            rows=rows,
            preview_columns=["Client", "Issue", "Expiry", "Notify"],
            upload_url_name="dsc_bulk_import",
            preview_title="DSC import",
            preview_page_title="DSC — Import preview",
            success_hint="Individual clients only. In-out records are created on import. Click Confirm import to save.",
            cells_fn=lambda r: [
                r.data["client"].client_id if r.data.get("client") else "",
                r.data.get("issue_date", ""),
                r.data.get("expiry_date", ""),
                "Yes" if r.data.get("expiry_notification") else "No",
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
            "import_title": "DSC import",
            "import_page_title": "DSC — Bulk upload (CSV)",
            "import_description": (
                "CLIENT_ID must be an approved Individual client in your branch. "
                "Dates: YYYY-MM-DD or DD-MM-YYYY. EXPIRY_NOTIFICATION: YES or NO."
            ),
            "columns": DSC_CSV_COLUMNS,
            "template_url_name": "dsc_bulk_import_template",
            "cancel_url_name": "dsc_list",
        },
    )


@require_perm("masters.add_clientdsc")
def dsc_bulk_import_template(request):
    from .dsc_csv_import import DSC_CSV_COLUMNS

    def q(v: str) -> str:
        s = (v or "").replace('"', '""')
        return f'"{s}"'

    lines = [",".join(q(c) for c in DSC_CSV_COLUMNS)]
    lines.append(",".join(q(c) for c in ["A00001", "2024-01-01", "2027-01-01", "YES", "dsc-secret"]))
    content = "\r\n".join(lines) + "\r\n"
    resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="dsc-template.csv"'
    return resp


@require_perm("masters.view_expensecategory")
def expense_category_list(request):
    q = (request.GET.get("q") or "").strip()
    qs = ExpenseCategory.objects.all()
    if q:
        qs = qs.filter(name__icontains=q)
    rows = qs.order_by("name")[:500]
    return render(
        request,
        "masters/expense_category_list.html",
        {"rows": rows, "q": q},
    )


@require_perm("masters.add_expensecategory")
def expense_category_create(request):
    if request.method == "POST":
        form = ExpenseCategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense category saved.")
            return redirect("expense_category_list")
    else:
        form = ExpenseCategoryForm()
    return render(
        request,
        "masters/expense_category_form.html",
        {
            "form": form,
            "mode": "create",
            "cancel_url": reverse("expense_category_list"),
        },
    )


@require_perm("masters.change_expensecategory")
def expense_category_edit(request, pk: int):
    obj = get_object_or_404(ExpenseCategory, pk=pk)
    if request.method == "POST":
        form = ExpenseCategoryForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Expense category updated.")
            return redirect("expense_category_list")
    else:
        form = ExpenseCategoryForm(instance=obj)
    return render(
        request,
        "masters/expense_category_form.html",
        {
            "form": form,
            "mode": "edit",
            "obj": obj,
            "cancel_url": reverse("expense_category_list"),
        },
    )


@require_perm("masters.delete_expensecategory")
def expense_category_delete(request, pk: int):
    obj = get_object_or_404(ExpenseCategory, pk=pk)
    if request.method == "POST":
        try:
            label = str(obj)
            obj.delete()
        except ProtectedError:
            messages.error(
                request,
                "This category cannot be deleted because it is used on MIS expense entries.",
            )
            return redirect("expense_category_list")
        messages.success(request, f"Deleted: {label}.")
        return redirect("expense_category_list")
    return render(request, "masters/expense_category_confirm_delete.html", {"obj": obj})

