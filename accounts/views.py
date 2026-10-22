from decimal import Decimal
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.deletion import ProtectedError
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.created_by import stamp_created_by

from core.decorators import require_perm
from core.site_settings import get_site_settings
from tasks.listing import tasks_queryset_for_user
from tasks.models import Task

from .forms import (
    ALL_LEDGERS,
    AccountForm,
    AccountGroupForm,
    InvoiceItemFormSet,
    InvoicePartyForm,
    LedgerReportForm,
    MainHeadForm,
    ParentGroupForm,
    ReportDateForm,
    ReportPeriodForm,
    TrialBalanceForm,
    UnbilledInvoiceForm,
    VoucherForm,
    JournalLineFormSet,
    VoucherLineFormSet,
)
from .permissions import (
    can_add_voucher,
    can_change_voucher,
    can_delete_voucher,
    can_print_voucher,
    can_view_voucher_type,
    first_addable_voucher_type,
    voucher_action_flags,
)
from .models import (
    REGISTER_TABS,
    REGISTER_TYPE_KEYS,
    SALES_INVOICE_GST,
    SALES_INVOICE_GST_B2C,
    SALES_INVOICE_NGST,
    SALES_INVOICE_KEYS,
    SALES_INVOICE_TABS,
    SERIES_GST,
    SERIES_GST_B2C,
    SERIES_NGST,
    sales_series_uses_gst,
    series_for_sales_tax_kind,
    tax_kind_for_sales_series,
    VOUCHER_CONTRA,
    VOUCHER_CREDIT_NOTE,
    VOUCHER_DEBIT_NOTE,
    VOUCHER_JOURNAL,
    VOUCHER_PAYMENT,
    VOUCHER_PURCHASE,
    VOUCHER_RECEIPT,
    VOUCHER_SALES,
    VOUCHER_TYPE_CHOICES,
    VOUCHER_TYPE_KEYS,
    Account,
    AccountGroup,
    Voucher,
)
from .export import (
    billwise_outstanding_excel_response,
    billwise_outstanding_pdf_response,
    book_register_excel_response,
    book_register_pdf_response,
    bs_excel_response,
    bs_pdf_response,
    ledger_excel_response,
    ledger_pdf_response,
    pnl_excel_response,
    pnl_pdf_response,
    tb_excel_response,
    tb_pdf_response,
    voucher_register_pdf_response,
)
from .services import (
    balance_sheet,
    build_contra_lines,
    build_invoice_lines,
    build_payment_lines,
    build_receipt_lines,
    cash_equivalent_ledgers,
    is_sundry_creditor,
    is_sundry_debtor,
    line_account_ledgers,
    money,
    outstanding_bills_for_account,
    pending_recovery_rows,
    outstanding_party_bills_for_note,
    build_unbilled_queue,
    create_invoices_from_unbilled_keys,
    filter_unbilled_queue,
    delete_voucher,
    all_ledger_sections,
    billwise_outstanding_sections,
    book_register_rows,
    is_gst_output_account,
    sales_register_totals,
    ledger_lines,
    amount_in_indian_words,
    post_voucher,
    update_voucher,
    profit_and_loss,
    sales_invoice_document,
    seed_chart_of_accounts,
    backfill_approved_client_ledgers,
    import_legacy_vouchers,
    sundry_debtors_ledgers,
    TB_FORMAT_TB,
    TB_REPORT_GROUP,
    financial_year_start,
    trial_balance,
)


def _note_alloc_items(formset) -> list[dict]:
    items = []
    for form in formset.forms:
        if not hasattr(form, "cleaned_data"):
            continue
        data = form.cleaned_data
        if not data or data.get("DELETE"):
            continue
        account = data.get("account")
        if not account or not (is_sundry_debtor(account) or is_sundry_creditor(account)):
            continue
        amount = money(data.get("debit")) + money(data.get("credit"))
        if amount <= 0:
            continue
        items.append(
            {
                "account": account,
                "amount": amount,
                "bill_alloc": data.get("bill_alloc") or "",
            }
        )
    return items


def _line_dicts(formset) -> list[dict]:
    rows = []
    for form in formset.forms:
        if not hasattr(form, "cleaned_data"):
            continue
        data = form.cleaned_data
        if not data or data.get("DELETE"):
            continue
        account = data.get("account")
        if not account:
            continue
        rows.append(
            {
                "account": account,
                "debit": data.get("debit") or 0,
                "credit": data.get("credit") or 0,
            }
        )
    return rows


def user_is_accounts_admin(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__iexact="Admin").exists()


def _group_kind(obj: AccountGroup) -> str:
    if obj.is_main_head():
        return "main"
    if obj.is_parent_group():
        return "parent"
    return "account"


def _form_for_kind(kind: str, *args, **kwargs):
    if kind == "main":
        return MainHeadForm(*args, **kwargs)
    if kind == "parent":
        return ParentGroupForm(*args, **kwargs)
    return AccountGroupForm(*args, **kwargs)


def _tab_redirect(kind: str):
    return redirect(f"{reverse('accounts_group_list')}?tab={kind}")


@require_perm("accounts.view_accountgroup")
def group_list(request):
    seed_chart_of_accounts()
    is_admin = user_is_accounts_admin(request.user)
    default_tab = "parent"
    tab = (request.GET.get("tab") or default_tab).strip()
    if tab not in ("account", "parent", "main"):
        tab = default_tab
    if tab == "main":
        rows = AccountGroup.main_heads().order_by("name")
        title = "Main Account"
    elif tab == "parent":
        rows = AccountGroup.parent_groups().select_related("parent").order_by("name")
        title = "Primary group"
    else:
        rows = AccountGroup.account_groups().select_related("parent", "parent__parent").order_by("name")
        title = "Account group"
    return render(
        request,
        "accounts/group_list.html",
        {
            "rows": rows,
            "tab": tab,
            "is_accounts_admin": is_admin,
            "list_title": title,
        },
    )


@require_perm("accounts.add_accountgroup")
def group_create(request):
    kind = (request.POST.get("kind") or request.GET.get("kind") or "account").strip()
    if kind not in ("account", "parent", "main"):
        kind = "account"
    if kind == "main" and not user_is_accounts_admin(request.user):
        raise PermissionDenied
    form = _form_for_kind(kind, request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.created_by = request.user
        try:
            obj.full_clean()
            obj.save()
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Saved.")
            return _tab_redirect(kind)
    parent_options = []
    if kind == "account":
        parent_options = [
            {"id": g.pk, "label": g.name}
            for g in AccountGroup.parent_groups().filter(is_active=True).select_related("parent").order_by("name")
        ]
    return render(
        request,
        "accounts/group_form.html",
        {
            "form": form,
            "mode": "create",
            "kind": kind,
            "parent_options": parent_options,
        },
    )


@require_perm("accounts.change_accountgroup")
def group_edit(request, pk: int):
    obj = get_object_or_404(AccountGroup, pk=pk)
    kind = _group_kind(obj)
    if kind == "main" and not user_is_accounts_admin(request.user):
        raise PermissionDenied
    form = _form_for_kind(kind, request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        group = form.save(commit=False)
        try:
            group.full_clean()
            group.save()
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Updated.")
            return _tab_redirect(kind)
    parent_options = []
    if kind == "account":
        parent_options = [
            {"id": g.pk, "label": g.name}
            for g in AccountGroup.parent_groups().filter(is_active=True).select_related("parent").order_by("name")
        ]
    return render(
        request,
        "accounts/group_form.html",
        {
            "form": form,
            "mode": "edit",
            "obj": obj,
            "kind": kind,
            "parent_options": parent_options,
        },
    )


@require_perm("accounts.delete_accountgroup")
@require_POST
def group_delete(request, pk: int):
    obj = get_object_or_404(AccountGroup, pk=pk)
    kind = _group_kind(obj)
    if kind == "main":
        messages.error(request, "Main heads cannot be deleted.")
        return _tab_redirect(kind)
    if obj.system_key:
        messages.error(request, "System groups cannot be deleted.")
        return _tab_redirect(kind)
    if obj.children.exists():
        messages.error(request, "This group has sub-groups and cannot be deleted.")
        return _tab_redirect(kind)
    if obj.accounts.exists():
        messages.error(request, "This group has account ledgers and cannot be deleted.")
        return _tab_redirect(kind)
    name = obj.name
    try:
        obj.delete()
    except ProtectedError:
        messages.error(request, "This group is in use and cannot be deleted.")
        return _tab_redirect(kind)
    label = "Account group" if kind == "account" else "Primary group"
    messages.success(request, f"{label} {name} deleted.")
    return _tab_redirect(kind)


def filter_account_ledgers(queryset, *, account="", account_group="", primary_group=""):
    account = (account or "").strip()
    account_group = (account_group or "").strip()
    primary_group = (primary_group or "").strip()
    if account:
        queryset = queryset.filter(name__icontains=account)
    if account_group:
        queryset = queryset.filter(
            group__parent__parent__isnull=False,
            group__name__icontains=account_group,
        )
    if primary_group:
        queryset = queryset.filter(
            Q(
                group__parent__isnull=False,
                group__parent__parent__isnull=True,
                group__name__icontains=primary_group,
            )
            | Q(
                group__parent__parent__isnull=False,
                group__parent__name__icontains=primary_group,
            )
        )
    return queryset


@require_perm("accounts.view_account")
def account_list(request):
    seed_chart_of_accounts()
    account_q = (request.GET.get("account") or request.GET.get("q") or "").strip()
    account_group_q = (request.GET.get("account_group") or "").strip()
    primary_group_q = (request.GET.get("primary_group") or "").strip()
    rows = filter_account_ledgers(
        Account.objects.select_related("group", "group__parent", "client").order_by("name"),
        account=account_q,
        account_group=account_group_q,
        primary_group=primary_group_q,
    )
    return render(
        request,
        "accounts/account_list.html",
        {
            "rows": rows,
            "account_q": account_q,
            "account_group_q": account_group_q,
            "primary_group_q": primary_group_q,
            "has_search": bool(account_q or account_group_q or primary_group_q),
            "tab": "ledger",
            "is_accounts_admin": user_is_accounts_admin(request.user),
        },
    )


@require_perm("accounts.add_account")
def account_create(request):
    form = AccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.created_by = request.user
        try:
            obj.full_clean()
            obj.save()
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Account saved.")
            return redirect("accounts_account_list")
    return render(request, "accounts/account_form.html", {"form": form, "mode": "create"})


@require_perm("accounts.change_account")
def account_edit(request, pk: int):
    obj = get_object_or_404(Account, pk=pk)
    form = AccountForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        acc = form.save(commit=False)
        try:
            acc.full_clean()
            acc.save()
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Account updated.")
            return redirect("accounts_account_list")
    return render(request, "accounts/account_form.html", {"form": form, "mode": "edit", "obj": obj})


@require_perm("accounts.delete_account")
@require_POST
def account_delete(request, pk: int):
    obj = get_object_or_404(Account, pk=pk)
    if obj.system_key:
        messages.error(request, "System accounts cannot be deleted.")
        return redirect("accounts_account_list")
    if obj.voucher_lines.exists():
        messages.error(request, "This account is used on a voucher and cannot be deleted.")
        return redirect("accounts_account_list")
    name = obj.name
    try:
        obj.delete()
    except ProtectedError:
        messages.error(request, "This account is used on a voucher and cannot be deleted.")
        return redirect("accounts_account_list")
    messages.success(request, f"Account {name} deleted.")
    return redirect("accounts_account_list")


GROUP_IMPORT_SESSION_KEY = "accounts_group_import_csv"
PRIMARY_GROUP_IMPORT_SESSION_KEY = "accounts_primary_group_import_csv"
LEDGER_IMPORT_SESSION_KEY = "accounts_ledger_import_csv"
VOUCHER_BOOKS_IMPORT_SESSION_KEY = "accounts_voucher_books_import_csv"


def _csv_template_response(filename: str, columns: list[str], sample_rows: list[list[str]]) -> HttpResponse:
    def q(v: str) -> str:
        s = (v or "").replace('"', '""')
        return f'"{s}"'

    lines = [",".join(q(c) for c in columns)]
    for row in sample_rows:
        lines.append(",".join(q(c) for c in row))
    content = "\r\n".join(lines) + "\r\n"
    resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def _accounts_bulk_preview_context(*, rows, preview_columns, upload_url_name, preview_title, preview_page_title, success_hint, cells_fn):
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


@require_perm("accounts.add_accountgroup")
def primary_group_bulk_import(request):
    from .csv_import import PRIMARY_GROUP_CSV_COLUMNS, parse_primary_groups_csv

    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = request.session.get(PRIMARY_GROUP_IMPORT_SESSION_KEY)
        if not raw:
            messages.error(request, "Nothing to import. Please upload the CSV again.")
            return redirect("accounts_primary_group_bulk_import")
        rows, file_errors = parse_primary_groups_csv(raw.encode("utf-8"))
        if file_errors or any(r.errors for r in rows):
            messages.error(request, "Cannot import: fix validation errors and upload again.")
            return redirect("accounts_primary_group_bulk_import")
        with transaction.atomic():
            for r in rows:
                obj = AccountGroup(
                    name=r.data["name"],
                    parent=r.data["parent"],
                    main_head=r.data["parent"].resolved_main_head(),
                    is_active=r.data["is_active"],
                )
                stamp_created_by(obj, request.user)
                obj.full_clean()
                obj.save()
        request.session.pop(PRIMARY_GROUP_IMPORT_SESSION_KEY, None)
        messages.success(request, f"Imported {len(rows)} primary group{'s' if len(rows) != 1 else ''}.")
        return redirect(f"{reverse('accounts_group_list')}?tab=parent")

    if request.method == "POST":
        f = request.FILES.get("csv_file")
        if not f:
            messages.error(request, "Please choose a CSV file.")
            return redirect("accounts_primary_group_bulk_import")
        raw_bytes = f.read()
        rows, file_errors = parse_primary_groups_csv(raw_bytes)
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("accounts_primary_group_bulk_import")
        request.session[PRIMARY_GROUP_IMPORT_SESSION_KEY] = _decode_csv_session(raw_bytes)
        ctx = _accounts_bulk_preview_context(
            rows=rows,
            preview_columns=["Name", "Main head", "Active"],
            upload_url_name="accounts_primary_group_bulk_import",
            preview_title="Primary groups import",
            preview_page_title="Primary group — Import preview",
            success_hint="Click Confirm import to create all primary groups.",
            cells_fn=lambda r: [
                r.data.get("name", ""),
                r.data.get("parent_name", ""),
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
            "import_title": "Primary groups import",
            "import_page_title": "Primary group — Bulk upload (CSV)",
            "import_description": (
                "NAME and MAIN_HEAD are required. MAIN_HEAD must be Assets, Liabilities, Income, or Expenses. "
                "IS_ACTIVE is YES/NO or blank (defaults to YES)."
            ),
            "columns": PRIMARY_GROUP_CSV_COLUMNS,
            "template_url_name": "accounts_primary_group_bulk_import_template",
            "cancel_url_name": "accounts_group_list",
            "cancel_url": f"{reverse('accounts_group_list')}?tab=parent",
        },
    )


@require_perm("accounts.add_accountgroup")
def primary_group_bulk_import_template(request):
    from .csv_import import PRIMARY_GROUP_CSV_COLUMNS

    return _csv_template_response(
        "primary-groups-template.csv",
        PRIMARY_GROUP_CSV_COLUMNS,
        [
            ["Sundry Debtors", "Assets", "YES"],
            ["Direct Income", "Income", "YES"],
            ["Direct Expenses", "Expenses", "YES"],
        ],
    )


@require_perm("accounts.add_accountgroup")
def group_bulk_import(request):
    from .csv_import import ACCOUNT_GROUP_CSV_COLUMNS, parse_account_groups_csv

    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = request.session.get(GROUP_IMPORT_SESSION_KEY)
        if not raw:
            messages.error(request, "Nothing to import. Please upload the CSV again.")
            return redirect("accounts_group_bulk_import")
        rows, file_errors = parse_account_groups_csv(raw.encode("utf-8"))
        if file_errors or any(r.errors for r in rows):
            messages.error(request, "Cannot import: fix validation errors and upload again.")
            return redirect("accounts_group_bulk_import")
        with transaction.atomic():
            for r in rows:
                obj = AccountGroup(
                    name=r.data["name"],
                    parent=r.data["parent"],
                    main_head=r.data["parent"].resolved_main_head(),
                    is_active=r.data["is_active"],
                )
                stamp_created_by(obj, request.user)
                obj.full_clean()
                obj.save()
        request.session.pop(GROUP_IMPORT_SESSION_KEY, None)
        messages.success(request, f"Imported {len(rows)} account group{'s' if len(rows) != 1 else ''}.")
        return redirect(f"{reverse('accounts_group_list')}?tab=account")

    if request.method == "POST":
        f = request.FILES.get("csv_file")
        if not f:
            messages.error(request, "Please choose a CSV file.")
            return redirect("accounts_group_bulk_import")
        raw_bytes = f.read()
        rows, file_errors = parse_account_groups_csv(raw_bytes)
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("accounts_group_bulk_import")
        request.session[GROUP_IMPORT_SESSION_KEY] = _decode_csv_session(raw_bytes)
        ctx = _accounts_bulk_preview_context(
            rows=rows,
            preview_columns=["Name", "Primary group", "Active"],
            upload_url_name="accounts_group_bulk_import",
            preview_title="Account groups import",
            preview_page_title="Account group — Import preview",
            success_hint="Click Confirm import to create all account groups.",
            cells_fn=lambda r: [
                r.data.get("name", ""),
                r.data.get("parent_name", ""),
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
            "import_title": "Account groups import",
            "import_page_title": "Account group — Bulk upload (CSV)",
            "import_description": (
                "NAME and PRIMARY_GROUP are required. PRIMARY_GROUP must match an existing Primary Group. "
                "MAIN_HEAD is optional (Assets, Liabilities, Income, Expenses) when the same primary group "
                "name exists under more than one main head. IS_ACTIVE is YES/NO or blank (defaults to YES)."
            ),
            "columns": ACCOUNT_GROUP_CSV_COLUMNS,
            "template_url_name": "accounts_group_bulk_import_template",
            "cancel_url_name": "accounts_group_list",
            "cancel_url": f"{reverse('accounts_group_list')}?tab=account",
        },
    )


@require_perm("accounts.add_accountgroup")
def group_bulk_import_template(request):
    from .csv_import import ACCOUNT_GROUP_CSV_COLUMNS

    return _csv_template_response(
        "account-groups-template.csv",
        ACCOUNT_GROUP_CSV_COLUMNS,
        [
            ["Trade receivables", "Sundry Debtors", "Assets", "YES"],
            ["Local sales", "Direct Income", "Income", "YES"],
        ],
    )


@require_perm("accounts.add_account")
def account_bulk_import(request):
    from .csv_import import ACCOUNT_LEDGER_CSV_COLUMNS, parse_account_ledgers_csv

    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = request.session.get(LEDGER_IMPORT_SESSION_KEY)
        if not raw:
            messages.error(request, "Nothing to import. Please upload the CSV again.")
            return redirect("accounts_account_bulk_import")
        rows, file_errors = parse_account_ledgers_csv(raw.encode("utf-8"))
        if file_errors or any(r.errors for r in rows):
            messages.error(request, "Cannot import: fix validation errors and upload again.")
            return redirect("accounts_account_bulk_import")
        with transaction.atomic():
            for r in rows:
                obj = Account(
                    name=r.data["name"],
                    group=r.data["group"],
                    address=r.data.get("address") or "",
                    gstin=r.data.get("gstin") or "",
                    hsn_code=r.data.get("hsn_code") or "",
                    gst_rate=r.data.get("gst_rate"),
                    is_pure_agent=bool(r.data.get("is_pure_agent")),
                    pan=r.data.get("pan") or "",
                    opening_balance=r.data.get("opening_balance") or Decimal("0.00"),
                    is_active=r.data["is_active"],
                )
                stamp_created_by(obj, request.user)
                obj.full_clean()
                obj.save()
        request.session.pop(LEDGER_IMPORT_SESSION_KEY, None)
        messages.success(request, f"Imported {len(rows)} account ledger{'s' if len(rows) != 1 else ''}.")
        return redirect("accounts_account_list")

    if request.method == "POST":
        f = request.FILES.get("csv_file")
        if not f:
            messages.error(request, "Please choose a CSV file.")
            return redirect("accounts_account_bulk_import")
        raw_bytes = f.read()
        rows, file_errors = parse_account_ledgers_csv(raw_bytes)
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("accounts_account_bulk_import")
        request.session[LEDGER_IMPORT_SESSION_KEY] = _decode_csv_session(raw_bytes)
        ctx = _accounts_bulk_preview_context(
            rows=rows,
            preview_columns=["Name", "Primary group", "Account group", "GSTIN", "Opening"],
            upload_url_name="accounts_account_bulk_import",
            preview_title="Account ledgers import",
            preview_page_title="Account ledger — Import preview",
            success_hint="Click Confirm import to create all account ledgers.",
            cells_fn=lambda r: [
                r.data.get("name", ""),
                r.data.get("primary_name", ""),
                r.data.get("account_group_name", ""),
                r.data.get("gstin", ""),
                r.data.get("opening_balance", ""),
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
            "import_title": "Account ledgers import",
            "import_page_title": "Account ledger — Bulk upload (CSV)",
            "import_description": (
                "NAME and PRIMARY_GROUP are required. ACCOUNT_GROUP is optional; leave it blank to place the "
                "ledger under the primary group. GST_RATE is a percent (for example 18). PURE_AGENT and "
                "IS_ACTIVE are YES/NO (PURE_AGENT defaults to NO). OPENING_BALANCE defaults to 0."
            ),
            "columns": ACCOUNT_LEDGER_CSV_COLUMNS,
            "template_url_name": "accounts_account_bulk_import_template",
            "cancel_url_name": "accounts_account_list",
        },
    )


@require_perm("accounts.add_account")
def account_bulk_import_template(request):
    from .csv_import import ACCOUNT_LEDGER_CSV_COLUMNS

    return _csv_template_response(
        "account-ledgers-template.csv",
        ACCOUNT_LEDGER_CSV_COLUMNS,
        [
            [
                "Office rent",
                "Direct Expenses",
                "",
                "",
                "",
                "",
                "",
                "NO",
                "",
                "0",
                "YES",
            ],
            [
                "ABC Traders",
                "Sundry Debtors",
                "Trade receivables",
                "M.G. Road, Kochi",
                "32AAAAA0000A1Z5",
                "9983",
                "18",
                "NO",
                "AAAAA0000A",
                "0",
                "YES",
            ],
        ],
    )


@login_required
def voucher_books_bulk_import(request):
    """Superuser one-time: import old-software vouchers keeping their serials."""
    if not request.user.is_superuser:
        raise PermissionDenied
    from .csv_import import VOUCHER_BOOKS_CSV_COLUMNS, parse_voucher_books_csv

    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = request.session.get(VOUCHER_BOOKS_IMPORT_SESSION_KEY)
        if not raw:
            messages.error(request, "Nothing to import. Please upload the CSV again.")
            return redirect("accounts_voucher_books_bulk_import")
        rows, file_errors = parse_voucher_books_csv(raw.encode("utf-8"))
        if file_errors or not rows or any(r.errors for r in rows):
            messages.error(request, "Cannot import: fix validation errors and upload again.")
            return redirect("accounts_voucher_books_bulk_import")
        with transaction.atomic():
            created = import_legacy_vouchers(rows=rows, actor=request.user)
        request.session.pop(VOUCHER_BOOKS_IMPORT_SESSION_KEY, None)
        messages.success(
            request,
            f"Imported {created} voucher{'s' if created != 1 else ''} ({len(rows)} line{'s' if len(rows) != 1 else ''}).",
        )
        return redirect("accounts_voucher_list")

    if request.method == "POST":
        f = request.FILES.get("csv_file")
        if not f:
            messages.error(request, "Please choose a CSV file.")
            return redirect("accounts_voucher_books_bulk_import")
        raw_bytes = f.read()
        rows, file_errors = parse_voucher_books_csv(raw_bytes)
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("accounts_voucher_books_bulk_import")
        request.session[VOUCHER_BOOKS_IMPORT_SESSION_KEY] = _decode_csv_session(raw_bytes)
        ctx = _accounts_bulk_preview_context(
            rows=rows,
            preview_columns=["Date", "Type", "Number", "Account", "Debit", "Credit", "Series"],
            upload_url_name="accounts_voucher_books_bulk_import",
            preview_title="Old books import",
            preview_page_title="Old books — Import preview",
            success_hint="Click Confirm import to post these vouchers with their old numbers.",
            cells_fn=lambda r: [
                r.data["date"].strftime("%d-%m-%Y") if r.data.get("date") else "",
                r.data.get("voucher_type") or "",
                r.data.get("number") or "",
                r.data.get("account_name") or "",
                r.data.get("debit") or "",
                r.data.get("credit") or "",
                r.data.get("series") or "",
            ],
        )
        if ctx["can_import"]:
            messages.success(request, f"File uploaded. {len(rows)} line(s) ready to import.")
        else:
            messages.error(request, f"{ctx['error_count']} row(s) have errors.")
        return render(request, "includes/bulk_csv_import_preview_page.html", ctx)

    return render(
        request,
        "includes/bulk_csv_import_page.html",
        {
            "import_title": "Old books import",
            "import_page_title": "Old books — Bulk upload (CSV)",
            "import_description": (
                "Import vouchers from the previous software from 01-04-2026 to cutover. "
                "Keep the old NUMBER on every line of the same voucher. The same NUMBER may be used on "
                "different voucher types (Receipt 1 and Sales 1). This does not use this software's "
                "GST/NGST monthly serial — new vouchers posted here still start at 00001. "
                "Create Account Ledgers first. One CSV row per debit or credit line. "
                "Bill-wise receipt knock-off is not imported."
            ),
            "columns": VOUCHER_BOOKS_CSV_COLUMNS,
            "template_url_name": "accounts_voucher_books_bulk_import_template",
            "cancel_url_name": "settings_hub",
        },
    )


@login_required
def voucher_books_bulk_import_template(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    from .csv_import import VOUCHER_BOOKS_CSV_COLUMNS

    return _csv_template_response(
        "old-books-vouchers-template.csv",
        VOUCHER_BOOKS_CSV_COLUMNS,
        [
            ["01-04-2026", "Journal", "JV-24-0001", "Opening", "Cash", "1000.00", "", "JV"],
            ["01-04-2026", "Journal", "JV-24-0001", "Opening", "Capital", "", "1000.00", "JV"],
            ["02-04-2026", "GST", "INV/24-25/001", "Fees", "ABC Traders", "1180.00", "", "GST"],
            ["02-04-2026", "GST", "INV/24-25/001", "Fees", "Professional income", "", "1000.00", "GST"],
            ["02-04-2026", "GST", "INV/24-25/001", "Fees", "GST output", "", "180.00", "GST"],
            ["03-04-2026", "GST-B2C", "12", "Walk-in fees", "ABC Traders", "590.00", "", "GSTB2C"],
            ["03-04-2026", "GST-B2C", "12", "Walk-in fees", "Professional income", "", "500.00", "GSTB2C"],
            ["03-04-2026", "GST-B2C", "12", "Walk-in fees", "GST output", "", "90.00", "GSTB2C"],
        ],
    )


def _decode_csv_session(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw_bytes.decode("cp1252", errors="replace")


@require_perm("accounts.view_voucher")
def account_outstanding(request, pk: int):
    account = get_object_or_404(Account, pk=pk, is_active=True)
    for_note = (request.GET.get("for") or "").strip() == "note"
    ignore_raw = (request.GET.get("ignore") or "").strip()
    ignore_receipt_id = int(ignore_raw) if ignore_raw.isdigit() else None
    if for_note:
        bills = outstanding_party_bills_for_note(account, ignore_receipt_id=ignore_receipt_id)
        party_kind = "creditor" if is_sundry_creditor(account) else "debtor" if is_sundry_debtor(account) else ""
    else:
        bills = outstanding_bills_for_account(account, ignore_receipt_id=ignore_receipt_id)
        party_kind = "debtor" if is_sundry_debtor(account) else ""
    return JsonResponse(
        {
            "id": account.pk,
            "name": account.name,
            "party_kind": party_kind,
            "has_bills": bool(bills),
            "bills": [
                {
                    "id": row["id"],
                    "number": row["number"],
                    "date": row["date"],
                    "invoice_amount": str(row["invoice_amount"]),
                    "outstanding": str(row["outstanding"]),
                    "is_opening": bool(row.get("is_opening")),
                }
                for row in bills
            ],
        }
    )


@require_perm("accounts.view_voucher")
def account_recovery_tasks(request, pk: int):
    account = get_object_or_404(Account, pk=pk, is_active=True)
    if not account.client_id:
        return JsonResponse({"tasks": []})
    rows = (
        Task.objects.filter(client_id=account.client_id)
        .exclude(status=Task.STATUS_CANCELLED)
        .select_related("task_master")
        .order_by("-due_date", "-pk")[:80]
    )
    return JsonResponse(
        {
            "tasks": [
                {
                    "id": task.pk,
                    "label": f"{task.display_title} ({task.period_key})",
                }
                for task in rows
            ]
        }
    )


@require_perm("accounts.view_voucher")
def account_pending_recoveries(request, pk: int):
    account = get_object_or_404(Account, pk=pk, is_active=True)
    ignore_raw = (request.GET.get("ignore") or "").strip()
    ignore_invoice_id = int(ignore_raw) if ignore_raw.isdigit() else None
    rows = pending_recovery_rows(party=account, ignore_invoice_id=ignore_invoice_id)
    return JsonResponse(
        {
            "recoveries": [
                {
                    "id": row["id"],
                    "number": row["number"],
                    "date": row["date"].isoformat() if row["date"] else "",
                    "account_id": row["account_id"],
                    "account_name": row["account_name"],
                    "task_label": row["task_label"],
                    "pending": str(row["pending"]),
                }
                for row in rows
            ]
        }
    )


def _voucher_type(request) -> str:
    raw = (request.POST.get("voucher_type") or request.GET.get("type") or VOUCHER_SALES).strip()
    return raw if raw in VOUCHER_TYPE_KEYS else VOUCHER_SALES


def _voucher_register_qs(vtype: str):
    amount_field = DecimalField(max_digits=14, decimal_places=2)
    return (
        Voucher.objects.filter(voucher_type=vtype)
        .annotate(amount=Coalesce(Sum("lines__debit"), Value(Decimal("0.00"), output_field=amount_field)))
        .order_by("-date", "-id")
    )


@login_required
def voucher_list(request):
    requested = (request.GET.get("type") or "").strip()
    vtype = requested if requested in VOUCHER_TYPE_KEYS else VOUCHER_SALES
    if not can_view_voucher_type(request.user, vtype):
        if not requested:
            tabs = voucher_action_flags(request.user, vtype)["voucher_tabs"]
            if tabs:
                return redirect(f"{reverse('accounts_voucher_list')}?type={tabs[0][0]}")
        raise PermissionDenied
    export = (request.GET.get("export") or "").strip().lower()
    rows = _voucher_register_qs(vtype)
    list_title = dict(VOUCHER_TYPE_CHOICES)[vtype]
    if export == "pdf":
        if not can_print_voucher(request.user, vtype):
            raise PermissionDenied
        settings = get_site_settings()
        return voucher_register_pdf_response(
            rows,
            title=list_title,
            voucher_type=vtype,
            company_name=(settings.company_name or "").strip(),
            company_address=(settings.address or "").strip(),
        )
    flags = voucher_action_flags(request.user, vtype)
    return render(
        request,
        "accounts/voucher_list.html",
        {
            "rows": rows[:500],
            "vtype": vtype,
            "list_title": list_title,
            "pdf_url": f"{reverse('accounts_voucher_list')}?{urlencode({'type': vtype, 'export': 'pdf'})}",
            **flags,
        },
    )


def _entry_initials(voucher: Voucher) -> dict:
    lines = list(voucher.lines.select_related("account", "account__group", "account__group__parent"))
    vtype = voucher.voucher_type
    party = None
    items = []
    tax_kind = None
    receivers = []
    payers = []
    if vtype == VOUCHER_SALES:
        party_line = next((ln for ln in lines if money(ln.debit) > 0), None)
        party = party_line.account if party_line else None
        has_gst = False
        used_allocs = set()
        for ln in lines:
            if money(ln.credit) <= 0:
                continue
            if is_gst_output_account(ln.account):
                has_gst = True
                continue
            rec_id = None
            for alloc in voucher.recovery_allocations.select_related("payment_line"):
                if alloc.pk in used_allocs:
                    continue
                if alloc.payment_line.account_id == ln.account_id and money(alloc.amount) == money(ln.credit):
                    rec_id = alloc.payment_line_id
                    used_allocs.add(alloc.pk)
                    break
            items.append({"account": ln.account_id, "amount": money(ln.credit), "recovery_line": rec_id})
        tax_kind = tax_kind_for_sales_series(voucher.series)
        if tax_kind == "ngst" and (voucher.series == SERIES_GST or has_gst):
            tax_kind = "gst"
    elif vtype == VOUCHER_PURCHASE:
        party_line = next((ln for ln in lines if money(ln.credit) > 0), None)
        party = party_line.account if party_line else None
        items = [{"account": ln.account_id, "amount": money(ln.debit)} for ln in lines if money(ln.debit) > 0]
    elif vtype == VOUCHER_RECEIPT:
        party_line = next((ln for ln in lines if money(ln.debit) > 0), None)
        party = party_line.account if party_line else None
        items = [{"account": ln.account_id, "amount": money(ln.credit)} for ln in lines if money(ln.credit) > 0]
    elif vtype == VOUCHER_PAYMENT:
        party_line = next((ln for ln in lines if money(ln.credit) > 0), None)
        party = party_line.account if party_line else None
        items = [{"account": ln.account_id, "amount": money(ln.debit)} for ln in lines if money(ln.debit) > 0]
    elif vtype == VOUCHER_CONTRA:
        receivers = [{"account": ln.account_id, "amount": money(ln.debit)} for ln in lines if money(ln.debit) > 0]
        payers = [{"account": ln.account_id, "amount": money(ln.credit)} for ln in lines if money(ln.credit) > 0]
    return {
        "party": party,
        "items": items,
        "tax_kind": tax_kind,
        "receivers": receivers,
        "payers": payers,
    }


@login_required
def voucher_create(request):
    requested = (request.POST.get("voucher_type") or request.GET.get("type") or "").strip()
    vtype = requested if requested in VOUCHER_TYPE_KEYS else VOUCHER_SALES
    if not can_add_voucher(request.user, vtype):
        if request.method != "POST" and not requested:
            fallback = first_addable_voucher_type(request.user)
            if fallback:
                return redirect(f"{reverse('accounts_voucher_create')}?type={fallback}")
        raise PermissionDenied
    return _save_voucher(request)


@login_required
def voucher_edit(request, pk: int):
    voucher = get_object_or_404(
        Voucher.objects.prefetch_related("lines__account", "tasks", "recovery_allocations__payment_line"),
        pk=pk,
    )
    if not can_change_voucher(request.user, voucher.voucher_type):
        raise PermissionDenied
    return _save_voucher(request, voucher=voucher)


def _save_voucher(request, voucher=None):
    existing = voucher if voucher and voucher.pk else None
    vtype = existing.voucher_type if existing else _voucher_type(request)
    if existing:
        if not can_change_voucher(request.user, vtype):
            raise PermissionDenied
    elif not can_add_voucher(request.user, vtype):
        raise PermissionDenied
    invoice_mode = vtype in (VOUCHER_SALES, VOUCHER_PURCHASE)
    receipt_mode = vtype == VOUCHER_RECEIPT
    payment_mode = vtype == VOUCHER_PAYMENT
    contra_mode = vtype == VOUCHER_CONTRA
    journal_mode = vtype in (VOUCHER_JOURNAL, VOUCHER_CREDIT_NOTE, VOUCHER_DEBIT_NOTE)
    note_mode = vtype in (VOUCHER_CREDIT_NOTE, VOUCHER_DEBIT_NOTE)
    compact_entry = receipt_mode or payment_mode
    amount_entry = invoice_mode or compact_entry
    form_voucher = existing or Voucher()
    task_id = (request.POST.get("task_id") or request.GET.get("task") or "").strip()
    linked_task = None if existing else (Task.objects.filter(pk=int(task_id)).first() if task_id.isdigit() else None)
    party_initial = {}
    item_initial = None
    recv_initial = None
    pay_initial = None
    if existing and request.method != "POST":
        initials = _entry_initials(existing)
        if initials["party"]:
            party_initial = {"party": initials["party"]}
            if initials["tax_kind"]:
                party_initial["tax_kind"] = initials["tax_kind"]
        item_initial = initials["items"] or None
        recv_initial = initials["receivers"] or None
        pay_initial = initials["payers"] or None
    elif invoice_mode and linked_task and request.method != "POST":
        party_acc = Account.objects.filter(client=linked_task.client).first()
        if party_acc:
            party_initial = {"party": party_acc}

    if request.method == "POST":
        form = VoucherForm(request.POST, instance=form_voucher, locked_type=vtype)
        party_form = InvoicePartyForm(request.POST, voucher_type=vtype) if amount_entry else None
        item_formset = InvoiceItemFormSet(request.POST, voucher_type=vtype) if amount_entry else None
        contra_recv_formset = (
            InvoiceItemFormSet(request.POST, prefix="recv", voucher_type=vtype) if contra_mode else None
        )
        contra_pay_formset = (
            InvoiceItemFormSet(request.POST, prefix="pay", voucher_type=vtype) if contra_mode else None
        )
        formset = None if (amount_entry or contra_mode) else (
            JournalLineFormSet(request.POST, instance=form_voucher)
            if journal_mode
            else VoucherLineFormSet(request.POST, instance=form_voucher)
        )
        forms_ok = form.is_valid()
        if amount_entry:
            forms_ok = forms_ok and party_form.is_valid() and item_formset.is_valid()
        elif contra_mode:
            forms_ok = forms_ok and contra_recv_formset.is_valid() and contra_pay_formset.is_valid()
        else:
            forms_ok = forms_ok and formset.is_valid()
        if forms_ok:
            linked_tasks = [linked_task] if linked_task else []
            try:
                items = None
                tax_kind = None
                if amount_entry:
                    items = [
                        {
                            "account": row.get("account"),
                            "amount": row.get("amount"),
                            "bill_alloc": row.get("bill_alloc") or "",
                            "recovery_line": row.get("recovery_line") or "",
                        }
                        for row in item_formset.cleaned_data
                        if row and not row.get("DELETE")
                    ]
                    with_gst = False
                    tax_kind = None
                    if invoice_mode:
                        if vtype == VOUCHER_SALES:
                            tax_kind = party_form.cleaned_data.get("tax_kind")
                            with_gst = sales_series_uses_gst(series_for_sales_tax_kind(tax_kind))
                        line_rows = build_invoice_lines(
                            voucher_type=vtype,
                            party=party_form.cleaned_data["party"],
                            items=items,
                            with_gst=with_gst,
                        )
                    elif receipt_mode:
                        line_rows = build_receipt_lines(
                            mode=party_form.cleaned_data["party"],
                            items=items,
                        )
                    else:
                        line_rows = build_payment_lines(
                            mode=party_form.cleaned_data["party"],
                            items=items,
                        )
                elif contra_mode:
                    with_gst = False

                    def _contra_items(formset):
                        return [
                            {"account": row.get("account"), "amount": row.get("amount")}
                            for row in formset.cleaned_data
                            if row and not row.get("DELETE")
                        ]

                    line_rows = build_contra_lines(
                        receivers=_contra_items(contra_recv_formset),
                        payers=_contra_items(contra_pay_formset),
                    )
                else:
                    line_rows = _line_dicts(formset)
                    with_gst = any(
                        getattr(row["account"], "system_key", None) in (
                            "gst_output",
                            "cgst_output",
                            "sgst_output",
                            "igst_output",
                        )
                        and row.get("credit")
                        for row in line_rows
                    )
                receipt_items = (
                    items
                    if receipt_mode
                    else _note_alloc_items(formset)
                    if journal_mode
                    else None
                )
                on_behalf_of = form.cleaned_data.get("on_behalf_of") if payment_mode else None
                on_behalf_task = form.cleaned_data.get("on_behalf_task") if payment_mode else None
                recovery_items = items if invoice_mode and vtype == VOUCHER_SALES else None
                if existing:
                    posted = update_voucher(
                        existing,
                        voucher_date=form.cleaned_data["date"],
                        narration=form.cleaned_data.get("narration") or "",
                        lines=line_rows,
                        receipt_items=receipt_items,
                        on_behalf_of=on_behalf_of,
                        on_behalf_task=on_behalf_task,
                        recovery_items=recovery_items,
                    )
                else:
                    posted = post_voucher(
                        voucher_type=vtype,
                        voucher_date=form.cleaned_data["date"],
                        narration=form.cleaned_data.get("narration") or "",
                        lines=line_rows,
                        actor=request.user,
                        with_gst=with_gst,
                        tax_kind=tax_kind,
                        tasks=linked_tasks or None,
                        receipt_items=receipt_items,
                        on_behalf_of=on_behalf_of,
                        on_behalf_task=on_behalf_task,
                        recovery_items=recovery_items,
                    )
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if getattr(exc, "messages", None) else str(exc))
            else:
                messages.success(request, f"Voucher {posted.number} saved.")
                return redirect("accounts_voucher_detail", pk=posted.pk)
    else:
        form = (
            VoucherForm(instance=existing, locked_type=vtype)
            if existing
            else VoucherForm(initial={"voucher_type": vtype}, locked_type=vtype)
        )
        party_form = InvoicePartyForm(initial=party_initial, voucher_type=vtype) if amount_entry else None
        item_formset = (
            InvoiceItemFormSet(initial=item_initial, voucher_type=vtype) if amount_entry else None
        )
        contra_recv_formset = (
            InvoiceItemFormSet(prefix="recv", initial=recv_initial, voucher_type=vtype) if contra_mode else None
        )
        contra_pay_formset = (
            InvoiceItemFormSet(prefix="pay", initial=pay_initial, voucher_type=vtype) if contra_mode else None
        )
        formset = None if (amount_entry or contra_mode) else (
            JournalLineFormSet(instance=form_voucher) if journal_mode else VoucherLineFormSet(instance=form_voucher)
        )
    outstanding_url = reverse("accounts_account_outstanding", args=[0])
    recoveries_url = reverse("accounts_account_recoveries", args=[0])
    if existing:
        outstanding_url = f"{outstanding_url}?ignore={existing.pk}"
        recoveries_url = f"{recoveries_url}?ignore={existing.pk}"
    return render(
        request,
        "accounts/voucher_form.html",
        {
            "form": form,
            "formset": formset,
            "party_form": party_form,
            "item_formset": item_formset,
            "invoice_mode": invoice_mode,
            "receipt_mode": receipt_mode,
            "payment_mode": payment_mode,
            "compact_entry": compact_entry,
            "contra_mode": contra_mode,
            "journal_mode": journal_mode,
            "note_mode": note_mode,
            "billwise_mode": journal_mode,
            "contra_recv_formset": contra_recv_formset,
            "contra_pay_formset": contra_pay_formset,
            "linked_task": linked_task,
            "obj": existing,
            "vtype": vtype,
            "list_title": dict(VOUCHER_TYPE_CHOICES)[vtype],
            "outstanding_url": outstanding_url,
            "recoveries_url": recoveries_url,
            "recovery_tasks_url": reverse("accounts_account_recovery_tasks", args=[0]),
            "on_behalf_options": [
                {"id": a.pk, "label": a.name, "search": " ".join(filter(None, [a.name, a.gstin, a.pan]))}
                for a in sundry_debtors_ledgers()
            ]
            if payment_mode or invoice_mode
            else [],
            "account_meta": {
                str(a.pk): {
                    "name": a.name,
                    "hsn": a.hsn_code or "",
                    "rate": str(a.gst_rate if a.gst_rate is not None else ""),
                    "pure": bool(a.is_pure_agent),
                    "address": a.address or "",
                    "gstin": a.gstin or "",
                    "pan": a.pan or "",
                }
                for a in Account.objects.filter(is_active=True)
            },
            "party_options": [
                {"id": a.pk, "label": a.name, "search": " ".join(filter(None, [a.name, a.gstin, a.pan]))}
                for a in (
                    sundry_debtors_ledgers()
                    if vtype == VOUCHER_SALES
                    else cash_equivalent_ledgers()
                    if vtype in (VOUCHER_RECEIPT, VOUCHER_PAYMENT, VOUCHER_CONTRA)
                    else Account.objects.filter(is_active=True).order_by("name")
                )
            ],
            "line_account_options": [
                {"id": a.pk, "label": a.name, "search": a.name}
                for a in line_account_ledgers(vtype)
            ],
            "company_gstin": (getattr(get_site_settings(), "gstin", None) or "").strip().upper(),
            "company_address": (getattr(get_site_settings(), "address", None) or "").strip(),
            **voucher_action_flags(request.user, vtype),
        },
    )


def _ledger_back_url(next_url: str) -> str:
    raw = (next_url or "").strip()
    if not raw.startswith("/") or raw.startswith("//"):
        return ""
    ledger_path = reverse("accounts_ledger").rstrip("/")
    path = raw.split("?", 1)[0].rstrip("/")
    if path != ledger_path:
        return ""
    return raw


@login_required
@require_POST
def voucher_delete(request, pk: int):
    obj = get_object_or_404(Voucher, pk=pk)
    if not can_delete_voucher(request.user, obj.voucher_type):
        raise PermissionDenied
    vtype = obj.voucher_type
    number = obj.number
    next_url = _ledger_back_url(request.POST.get("next") or "")
    try:
        delete_voucher(obj)
    except ProtectedError:
        messages.error(request, f"{number} cannot be deleted because it is used on another record.")
        if next_url:
            return redirect(next_url)
        return redirect("accounts_voucher_detail", pk=pk)
    messages.success(request, f"{number} deleted.")
    if next_url:
        return redirect(next_url)
    return redirect(f"{reverse('accounts_voucher_list')}?type={vtype}")


@login_required
def voucher_detail(request, pk: int):
    obj = get_object_or_404(
        Voucher.objects.select_related("on_behalf_of", "on_behalf_task").prefetch_related(
            "lines__account",
            "tasks",
            "receipt_allocations__against",
            "receipt_allocations__party",
            "recovery_allocations__payment_line__voucher",
        ),
        pk=pk,
    )
    if not can_view_voucher_type(request.user, obj.voucher_type):
        raise PermissionDenied
    return render(
        request,
        "accounts/voucher_detail.html",
        {
            "obj": obj,
            "vtype": obj.voucher_type,
            "back_to_ledger": _ledger_back_url(request.GET.get("next") or ""),
            **voucher_action_flags(request.user, obj.voucher_type),
        },
    )


@login_required
def voucher_print(request, pk: int):
    obj = get_object_or_404(
        Voucher.objects.select_related("on_behalf_of", "on_behalf_task").prefetch_related("lines__account"),
        pk=pk,
    )
    if obj.voucher_type == VOUCHER_SALES:
        return redirect("accounts_sales_invoice_print", pk=obj.pk)
    if not can_print_voucher(request.user, obj.voucher_type):
        raise PermissionDenied
    settings = get_site_settings()
    amount = obj.debit_total()
    return render(
        request,
        "accounts/voucher_print.html",
        {
            "obj": obj,
            "vtype": obj.voucher_type,
            "company_name": (settings.company_name or "").strip(),
            "company_address": (settings.address or "").strip(),
            "amount": amount,
            "amount_words": amount_in_indian_words(amount),
        },
    )


@require_perm("accounts.view_voucher")
def sales_invoice_print(request, pk: int):
    obj = get_object_or_404(Voucher.objects.prefetch_related("lines__account", "tasks"), pk=pk)
    if obj.voucher_type != VOUCHER_SALES:
        messages.error(request, "Print layout is available for sales invoices.")
        return redirect("accounts_voucher_detail", pk=obj.pk)
    return render(
        request,
        "accounts/sales_invoice_print.html",
        {"obj": obj, "invoice": sales_invoice_document(obj), "vtype": obj.voucher_type},
    )


@require_perm("accounts.post_voucher")
def unbilled_tasks(request):
    seed_chart_of_accounts()
    qs = (
        tasks_queryset_for_user(request.user)
        .filter(status=Task.STATUS_COMPLETE, is_billable=True, bill_raised=False)
        .exclude(fees_amount__isnull=True)
        .exclude(fees_amount=0)
        .select_related("client", "task_master")
        .order_by("-completed_at")
    )
    q = (request.POST.get("q") or request.GET.get("q") or "").strip()
    fee_tasks = list(qs[:500])
    rows = filter_unbilled_queue(build_unbilled_queue(tasks=fee_tasks), q)
    form = UnbilledInvoiceForm(request.POST or None)
    if request.method == "POST":
        keys = [str(x).strip() for x in request.POST.getlist("item") if str(x).strip()]
        if not keys:
            messages.error(request, "Select at least one fees or recovery row.")
        elif form.is_valid():
            tax_kind = form.cleaned_data["invoice_type"]
            try:
                created = create_invoices_from_unbilled_keys(
                    keys=keys,
                    tasks=fee_tasks,
                    actor=request.user,
                    voucher_date=form.cleaned_data["invoice_date"],
                    tax_kind=tax_kind,
                )
            except ValidationError as exc:
                messages.error(request, exc.messages[0] if getattr(exc, "messages", None) else str(exc))
            else:
                numbers = ", ".join(v.number for v in created)
                messages.success(request, f"Created invoice(s): {numbers}")
                list_url = reverse("accounts_unbilled_tasks")
                if q:
                    list_url = f"{list_url}?{urlencode({'q': q})}"
                return redirect(list_url)
    return render(
        request,
        "accounts/unbilled_tasks.html",
        {"rows": rows, "form": form, "q": q},
    )


def _trial_balance_selection(request):
    initial = {
        "date_from": financial_year_start(),
        "date_to": timezone.localdate(),
        "tb_report": TB_REPORT_GROUP,
        "report_format": TB_FORMAT_TB,
    }
    form = TrialBalanceForm(request.GET or None, initial=initial)
    date_from = initial["date_from"]
    date_to = initial["date_to"]
    report = initial["tb_report"]
    fmt = initial["report_format"]
    get_data = request.GET.copy()
    get_data.pop("export", None)
    if get_data and form.is_valid():
        date_from = form.cleaned_data.get("date_from") or date_from
        date_to = form.cleaned_data.get("date_to") or date_to
        report = form.cleaned_data.get("tb_report") or report
        fmt = form.cleaned_data.get("report_format") or fmt
    return form, date_from, date_to, report, fmt


@require_perm("accounts.view_accounts_reports")
def report_trial_balance(request):
    form, date_from, date_to, report, fmt = _trial_balance_selection(request)
    data = trial_balance(date_from=date_from, date_to=date_to, report=report, fmt=fmt)
    export = (request.GET.get("export") or "").strip().lower()
    if export in ("xlsx", "excel", "csv"):
        return tb_excel_response(
            data,
            date_from=date_from,
            date_to=date_to,
            company_name=get_site_settings().company_name,
        )
    if export == "pdf":
        return tb_pdf_response(
            data,
            date_from=date_from,
            date_to=date_to,
            company_name=get_site_settings().company_name,
        )
    empty_colspan = 3
    if data["show_group_column"]:
        empty_colspan += 1
    if data["show_opening"]:
        empty_colspan += 2
    if data["show_transactions"]:
        empty_colspan += 2
    query = urlencode(
        {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "tb_report": report,
            "report_format": fmt,
        }
    )
    return render(
        request,
        "accounts/report_trial_balance.html",
        {
            "form": form,
            "date_from": date_from,
            "date_to": date_to,
            "data": data,
            "rows": data["rows"],
            "totals": data["totals"],
            "empty_colspan": empty_colspan,
            "excel_url": f"{reverse('accounts_trial_balance')}?{query}&export=xlsx",
            "pdf_url": f"{reverse('accounts_trial_balance')}?{query}&export=pdf",
        },
    )


@require_perm("accounts.view_accounts_reports")
def report_profit_loss(request):
    initial = {
        "date_from": financial_year_start(),
        "date_to": timezone.localdate(),
    }
    export = (request.GET.get("export") or "").strip().lower()
    form = ReportPeriodForm(request.GET or None, initial=initial)
    date_from = initial["date_from"]
    date_to = initial["date_to"]
    if request.GET and form.is_valid():
        date_from = form.cleaned_data.get("date_from") or date_from
        date_to = form.cleaned_data.get("date_to") or date_to
    data = profit_and_loss(date_from=date_from, date_to=date_to)
    settings = get_site_settings()
    company_name = (settings.company_name or "").strip()
    company_address = (settings.address or "").strip()
    if export in ("xlsx", "excel", "csv"):
        return pnl_excel_response(
            data,
            date_from=date_from,
            date_to=date_to,
            company_name=company_name,
            company_address=company_address,
        )
    if export == "pdf":
        return pnl_pdf_response(
            data,
            date_from=date_from,
            date_to=date_to,
            company_name=company_name,
            company_address=company_address,
        )
    query = urlencode(
        {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        }
    )
    return render(
        request,
        "accounts/report_pnl.html",
        {
            "data": data,
            "form": form,
            "date_from": date_from,
            "date_to": date_to,
            "company_name": company_name,
            "company_address": company_address,
            "excel_url": f"{reverse('accounts_profit_loss')}?{query}&export=xlsx",
            "pdf_url": f"{reverse('accounts_profit_loss')}?{query}&export=pdf",
        },
    )


@require_perm("accounts.view_accounts_reports")
def report_balance_sheet(request):
    initial = {"date_to": timezone.localdate()}
    export = (request.GET.get("export") or "").strip().lower()
    form = ReportDateForm(request.GET or None, initial=initial)
    date_to = initial["date_to"]
    if request.GET and form.is_valid():
        date_to = form.cleaned_data.get("date_to") or date_to
    data = balance_sheet(date_to=date_to)
    settings = get_site_settings()
    company_name = (settings.company_name or "").strip()
    company_address = (settings.address or "").strip()
    if export in ("xlsx", "excel", "csv"):
        return bs_excel_response(
            data,
            date_to=date_to,
            company_name=company_name,
            company_address=company_address,
        )
    if export == "pdf":
        return bs_pdf_response(
            data,
            date_to=date_to,
            company_name=company_name,
            company_address=company_address,
        )
    query = urlencode({"date_to": date_to.isoformat()})
    return render(
        request,
        "accounts/report_balance_sheet.html",
        {
            "data": data,
            "form": form,
            "as_on": date_to,
            "company_name": company_name,
            "company_address": company_address,
            "excel_url": f"{reverse('accounts_balance_sheet')}?{query}&export=xlsx",
            "pdf_url": f"{reverse('accounts_balance_sheet')}?{query}&export=pdf",
        },
    )


@require_perm("accounts.view_accounts_reports")
def report_ledger(request):
    export = (request.GET.get("export") or "").strip().lower()
    form = LedgerReportForm(request.GET or None)
    rows = []
    sections = []
    account = None
    all_ledgers = False
    date_from = None
    date_to = None
    if request.GET and form.is_valid():
        raw_account = (form.cleaned_data.get("account") or "").strip()
        date_from = form.cleaned_data.get("date_from")
        date_to = form.cleaned_data.get("date_to")
        if raw_account == ALL_LEDGERS:
            all_ledgers = True
            sections = all_ledger_sections(date_from=date_from, date_to=date_to)
        elif raw_account.isdigit():
            account = Account.objects.filter(pk=int(raw_account), is_active=True).first()
            if account:
                rows = ledger_lines(account, date_from=date_from, date_to=date_to)
    settings = get_site_settings()
    company_name = (settings.company_name or "").strip()
    company_address = (settings.address or "").strip()
    if (account or all_ledgers) and export in ("xlsx", "excel", "csv"):
        return ledger_excel_response(
            rows,
            account=account,
            date_from=date_from,
            date_to=date_to,
            company_name=company_name,
            company_address=company_address,
            sections=sections or None,
        )
    if (account or all_ledgers) and export == "pdf":
        return ledger_pdf_response(
            rows,
            account=account,
            date_from=date_from,
            date_to=date_to,
            company_name=company_name,
            company_address=company_address,
            sections=sections or None,
        )
    query = urlencode(
        {
            "account": ALL_LEDGERS if all_ledgers else (account.pk if account else ""),
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
        }
    )
    return render(
        request,
        "accounts/report_ledger.html",
        {
            "form": form,
            "rows": rows,
            "sections": sections,
            "account": account,
            "all_ledgers": all_ledgers,
            "ledger_return_url": request.get_full_path(),
            "excel_url": f"{reverse('accounts_ledger')}?{query}&export=xlsx",
            "pdf_url": f"{reverse('accounts_ledger')}?{query}&export=pdf",
        },
    )


def _register_type(request) -> str:
    raw = (request.GET.get("type") or VOUCHER_SALES).strip()
    return raw if raw in REGISTER_TYPE_KEYS else VOUCHER_SALES


def _sales_invoice_kind(request) -> str:
    raw = (request.GET.get("invoice") or SALES_INVOICE_GST).strip().lower()
    return raw if raw in SALES_INVOICE_KEYS else SALES_INVOICE_GST


@require_perm("accounts.view_accounts_reports")
def report_register(request):
    vtype = _register_type(request)
    invoice_kind = _sales_invoice_kind(request) if vtype == VOUCHER_SALES else ""
    initial = {
        "date_from": financial_year_start(),
        "date_to": timezone.localdate(),
    }
    form = ReportPeriodForm(request.GET or None, initial=initial)
    date_from = initial["date_from"]
    date_to = initial["date_to"]
    get_data = request.GET.copy()
    get_data.pop("export", None)
    if get_data and form.is_valid():
        date_from = form.cleaned_data.get("date_from") or date_from
        date_to = form.cleaned_data.get("date_to") or date_to
    title = dict(REGISTER_TABS)[vtype]
    series = None
    if vtype == VOUCHER_SALES:
        series = {
            SALES_INVOICE_GST: SERIES_GST,
            SALES_INVOICE_GST_B2C: SERIES_GST_B2C,
            SALES_INVOICE_NGST: SERIES_NGST,
        }.get(invoice_kind, SERIES_GST)
        title = f"{title} — {dict(SALES_INVOICE_TABS)[invoice_kind]}"
    rows = book_register_rows(voucher_type=vtype, date_from=date_from, date_to=date_to, series=series)
    if vtype == VOUCHER_SALES:
        column_totals = sales_register_totals(rows, gst=invoice_kind != SALES_INVOICE_NGST)
        total = column_totals["total"]
    else:
        column_totals = {}
        total = money(sum((row["amount"] for row in rows), Decimal("0.00")))
    export = (request.GET.get("export") or "").strip().lower()
    settings = get_site_settings()
    company_name = (settings.company_name or "").strip()
    company_address = (settings.address or "").strip()
    if export in ("xlsx", "excel", "csv"):
        return book_register_excel_response(
            rows,
            title=title,
            date_from=date_from,
            date_to=date_to,
            company_name=company_name,
            company_address=company_address,
            invoice_kind=invoice_kind,
        )
    if export == "pdf":
        return book_register_pdf_response(
            rows,
            title=title,
            date_from=date_from,
            date_to=date_to,
            company_name=company_name,
            company_address=company_address,
            invoice_kind=invoice_kind,
        )
    query_data = {
        "type": vtype,
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
    }
    if invoice_kind:
        query_data["invoice"] = invoice_kind
    query = urlencode(query_data)
    return render(
        request,
        "accounts/report_register.html",
        {
            "form": form,
            "rows": rows,
            "total": total,
            "column_totals": column_totals,
            "vtype": vtype,
            "invoice_kind": invoice_kind,
            "list_title": title,
            "register_tabs": REGISTER_TABS,
            "report_kind": vtype,
            "sales_invoice_tabs": SALES_INVOICE_TABS if vtype == VOUCHER_SALES else [],
            "date_from": date_from,
            "date_to": date_to,
            "excel_url": f"{reverse('accounts_register')}?{query}&export=xlsx",
            "pdf_url": f"{reverse('accounts_register')}?{query}&export=pdf",
        },
    )


@require_perm("accounts.view_accounts_reports")
def report_billwise_outstanding(request):
    initial = {"date_to": timezone.localdate()}
    form = ReportPeriodForm(request.GET or None, initial=initial)
    as_on = initial["date_to"]
    get_data = request.GET.copy()
    get_data.pop("export", None)
    if get_data and form.is_valid():
        as_on = form.cleaned_data.get("date_to") or as_on
    data = billwise_outstanding_sections(as_on=as_on)
    export = (request.GET.get("export") or "").strip().lower()
    settings = get_site_settings()
    company_name = (settings.company_name or "").strip()
    company_address = (settings.address or "").strip()
    title = "Bill wise outstanding"
    if export in ("xlsx", "excel", "csv"):
        return billwise_outstanding_excel_response(
            data,
            title=title,
            company_name=company_name,
            company_address=company_address,
        )
    if export == "pdf":
        return billwise_outstanding_pdf_response(
            data,
            title=title,
            company_name=company_name,
            company_address=company_address,
        )
    query = urlencode({"date_to": as_on.isoformat() if as_on else ""})
    return render(
        request,
        "accounts/report_billwise_outstanding.html",
        {
            "form": form,
            "data": data,
            "as_on": as_on,
            "list_title": title,
            "register_tabs": REGISTER_TABS,
            "report_kind": "outstanding",
            "date_to": as_on,
            "excel_url": f"{reverse('accounts_billwise_outstanding')}?{query}&export=xlsx",
            "pdf_url": f"{reverse('accounts_billwise_outstanding')}?{query}&export=pdf",
        },
    )


@require_perm("accounts.post_voucher")
def report_pending_recoveries(request):
    return redirect("accounts_unbilled_tasks")


@login_required
def sync_client_ledgers(request):
    """Superuser one-time: create Sundry Debtor ledgers for approved Client Master rows."""
    if not request.user.is_superuser:
        raise PermissionDenied
    from masters.models import Client

    preview = backfill_approved_client_ledgers(dry_run=True)
    if request.method == "POST" and request.POST.get("confirm") == "1":
        result = backfill_approved_client_ledgers(dry_run=False)
        created = result["created"]
        updated = result["updated"]
        skipped = result["skipped_unapproved"]
        messages.success(
            request,
            f"Created {created} ledger(s). Already linked {updated}. Skipped unapproved {skipped}.",
        )
        for row in result["errors"]:
            messages.warning(request, row)
        return redirect("accounts_account_list")
    return render(
        request,
        "accounts/sync_client_ledgers.html",
        {
            "preview": preview,
            "approved_pending": preview["created"],
            "already_linked": preview["updated"],
            "skipped_unapproved": preview["skipped_unapproved"],
            "approved_total": Client.objects.filter(approval_status=Client.APPROVED).count(),
        },
    )
