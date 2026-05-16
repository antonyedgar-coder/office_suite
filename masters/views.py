import base64

from django.db import transaction, IntegrityError
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.http import HttpResponse
from django.utils import timezone
from django.core.exceptions import ValidationError

from .director_mapping_import import (
    DIRECTOR_MAPPING_CSV_HEADERS,
    attach_client_master_validation,
    parse_director_mappings_csv,
    validate_director_mapping_import_active_uniqueness_in_file,
)
from .forms import ClientForm, ClientGroupForm, DirectorCompanyPickForm, DirectorForm, DirectorMappingRowFormSet
from .models import DIRECTOR_COMPANY_TYPES, DIRECTOR_ELIGIBLE_CLIENT_TYPES, Client, ClientGroup, DirectorMapping
from .csv_import import parse_clients_csv, CSV_COLUMNS
from .group_csv_import import GROUP_CSV_COLUMNS, parse_client_groups_csv

from core.branch_access import filter_clients_by_branch
from core.decorators import require_perm


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
    return render(request, "masters/client_list.html", {"clients": qs, "q": q})


@require_perm("masters.add_client")
def client_create(request):
    if request.method == "POST":
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save(commit=False)
            _apply_new_client_approval(client, request.user)
            client.save()
            if client.approval_status == Client.APPROVED:
                messages.success(request, f"Client created: {client.client_id}")
            else:
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
        {"form": form, "mode": "create", "groups_opts": _group_options_for_client_form(None)},
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
    return render(
        request,
        "masters/client_form.html",
        {
            "form": form,
            "mode": "edit",
            "client": client,
            "groups_opts": _group_options_for_client_form(client),
        },
    )


@require_perm("masters.delete_client")
def client_delete(request, client_id: str):
    client = get_object_or_404(client_master_queryset_for_user(request.user), pk=client_id)
    if request.method == "POST":
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
    now = timezone.now()
    client.approval_status = Client.APPROVED
    client.approved_by = request.user
    client.approved_at = now
    client.save(update_fields=["approval_status", "approved_by", "approved_at", "updated_at"])
    messages.success(request, f"Client {client.client_id} approved.")
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
    return render(request, "masters/director_list.html", {"mappings": qs, "q": q})


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
                        )
                        m.full_clean()
                        m.save()
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
                    {
                        "company_form": company_form,
                        "formset": formset,
                        "directors_opts": directors_opts,
                        "companies_opts": companies_opts,
                    },
                )
            except IntegrityError:
                messages.error(
                    request,
                    "Could not save one of the rows (duplicate director + company + same appointed date, or database constraint).",
                )
                return render(
                    request,
                    "masters/director_create_multi.html",
                    {
                        "company_form": company_form,
                        "formset": formset,
                        "directors_opts": directors_opts,
                        "companies_opts": companies_opts,
                    },
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
        {
            "company_form": company_form,
            "formset": formset,
            "directors_opts": directors_opts,
            "companies_opts": companies_opts,
        },
    )


@require_perm("masters.change_directormapping")
def director_edit(request, pk: int):
    from core.branch_access import filter_director_mapping_qs

    director = get_object_or_404(filter_director_mapping_qs(DirectorMapping.objects.all(), request.user), pk=pk)
    if request.method == "POST":
        form = DirectorForm(request.POST, instance=director, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Director mapping updated.")
            return redirect("director_list")
    else:
        form = DirectorForm(instance=director, user=request.user)
    return render(request, "masters/director_form.html", {"form": form, "mode": "edit", "mapping": director})


@require_perm("masters.delete_directormapping")
def director_delete(request, pk: int):
    from core.branch_access import filter_director_mapping_qs

    mapping = get_object_or_404(filter_director_mapping_qs(DirectorMapping.objects.all(), request.user), pk=pk)
    if request.method == "POST":
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
            "AN0001",
            "01234567",
            "JOHN DIRECTOR",
            "BT0001",
            "ABC PRIVATE LIMITED",
            "2024-04-01",
            "",
            "",
        ],
        [
            "AT0001",
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

