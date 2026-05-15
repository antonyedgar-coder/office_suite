from decimal import Decimal
from django.contrib import messages
import base64
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from core.decorators import require_perm

from .forms import ExpenseDetailForm, FeesDetailForm, ReceiptForm
from .models import ExpenseDetail, FeesDetail, Receipt
from .xlsx_import import (
    parse_expenses_csv,
    parse_expenses_xlsx,
    parse_fees_csv,
    parse_fees_xlsx,
    parse_mis_combined_csv,
    parse_receipts_csv,
    parse_receipts_xlsx,
)


def _client_search_q(request):
    return (request.GET.get("q") or "").strip().upper()


@require_perm("mis.view_feesdetail")
def fees_list(request):
    q = _client_search_q(request)
    qs = FeesDetail.objects.select_related("client").all()
    if q:
        qs = qs.filter(
            Q(client__client_name__icontains=q)
            | Q(client__client_id__icontains=q)
            | Q(pan_no__icontains=q)
        )
    qs = qs.order_by("-date", "-id")[:500]
    return render(request, "mis/fees_list.html", {"rows": qs, "q": q})


@require_perm("mis.add_feesdetail")
def fees_create(request):
    if request.method == "POST":
        form = FeesDetailForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Fees saved for {obj.client.client_name}.")
            return redirect("mis_fees_list")
    else:
        form = FeesDetailForm()
    return render(request, "mis/fees_form.html", {"form": form, "mode": "create"})


@require_perm("mis.change_feesdetail")
def fees_edit(request, pk: int):
    obj = get_object_or_404(FeesDetail, pk=pk)
    if request.method == "POST":
        form = FeesDetailForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Fees updated for {obj.client.client_name}.")
            return redirect("mis_fees_list")
    else:
        form = FeesDetailForm(instance=obj)
    return render(request, "mis/fees_form.html", {"form": form, "mode": "edit", "obj": obj})


@require_perm("mis.delete_feesdetail")
def fees_delete(request, pk: int):
    obj = get_object_or_404(FeesDetail, pk=pk)
    if request.method == "POST":
        label = f"{obj.client.client_name} ({obj.date})"
        obj.delete()
        messages.success(request, f"Fees entry deleted: {label}.")
        return redirect("mis_fees_list")
    return render(request, "mis/fees_confirm_delete.html", {"obj": obj})


@require_perm("mis.view_receipt")
def receipt_list(request):
    q = _client_search_q(request)
    qs = Receipt.objects.select_related("client").all()
    if q:
        qs = qs.filter(
            Q(client__client_name__icontains=q)
            | Q(client__client_id__icontains=q)
            | Q(pan_no__icontains=q)
        )
    qs = qs.order_by("-date", "-id")[:500]
    return render(request, "mis/receipt_list.html", {"rows": qs, "q": q})


@require_perm("mis.add_receipt")
def receipt_create(request):
    if request.method == "POST":
        form = ReceiptForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Receipt saved for {obj.client.client_name}.")
            return redirect("mis_receipt_list")
    else:
        form = ReceiptForm()
    return render(request, "mis/receipt_form.html", {"form": form, "mode": "create"})


@require_perm("mis.change_receipt")
def receipt_edit(request, pk: int):
    obj = get_object_or_404(Receipt, pk=pk)
    if request.method == "POST":
        form = ReceiptForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Receipt updated for {obj.client.client_name}.")
            return redirect("mis_receipt_list")
    else:
        form = ReceiptForm(instance=obj)
    return render(request, "mis/receipt_form.html", {"form": form, "mode": "edit", "obj": obj})


@require_perm("mis.delete_receipt")
def receipt_delete(request, pk: int):
    obj = get_object_or_404(Receipt, pk=pk)
    if request.method == "POST":
        label = f"{obj.client.client_name} ({obj.date})"
        obj.delete()
        messages.success(request, f"Receipt deleted: {label}.")
        return redirect("mis_receipt_list")
    return render(request, "mis/receipt_confirm_delete.html", {"obj": obj})


@require_perm("mis.view_expensedetail")
def expense_list(request):
    q = _client_search_q(request)
    qs = ExpenseDetail.objects.select_related("client").all()
    if q:
        qs = qs.filter(
            Q(client__client_name__icontains=q)
            | Q(client__client_id__icontains=q)
            | Q(pan_no__icontains=q)
        )
    qs = qs.order_by("-date", "-id")[:500]
    return render(request, "mis/expense_list.html", {"rows": qs, "q": q})


@require_perm("mis.add_expensedetail")
def expense_create(request):
    if request.method == "POST":
        form = ExpenseDetailForm(request.POST)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Expense saved for {obj.client.client_name}.")
            return redirect("mis_expense_list")
    else:
        form = ExpenseDetailForm()
    return render(request, "mis/expense_form.html", {"form": form, "mode": "create"})


@require_perm("mis.change_expensedetail")
def expense_edit(request, pk: int):
    obj = get_object_or_404(ExpenseDetail, pk=pk)
    if request.method == "POST":
        form = ExpenseDetailForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save()
            messages.success(request, f"Expense updated for {obj.client.client_name}.")
            return redirect("mis_expense_list")
    else:
        form = ExpenseDetailForm(instance=obj)
    return render(request, "mis/expense_form.html", {"form": form, "mode": "edit", "obj": obj})


@require_perm("mis.delete_expensedetail")
def expense_delete(request, pk: int):
    obj = get_object_or_404(ExpenseDetail, pk=pk)
    if request.method == "POST":
        label = f"{obj.client.client_name} ({obj.date})"
        obj.delete()
        messages.success(request, f"Expense entry deleted: {label}.")
        return redirect("mis_expense_list")
    return render(request, "mis/expense_confirm_delete.html", {"obj": obj})


def _xlsx_template_response(filename: str, header: list[str], sample_rows: list[list[str]]):
    # Minimal XML-free template: just provide CSV-like content in xlsx is overkill.
    # We'll send a simple HTML table as .xlsx isn't trivial without generating binary.
    # Instead, provide CSV download as a template that opens in Excel.
    lines = []
    lines.append(",".join(header))
    for r in sample_rows:
        lines.append(",".join(str(c) for c in r))
    content = "\r\n".join(lines) + "\r\n"
    resp = HttpResponse(content, content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def _session_put_file(request, key: str, raw_bytes: bytes) -> None:
    request.session[key] = base64.b64encode(raw_bytes).decode("ascii")


def _session_get_file(request, key: str) -> bytes | None:
    s = request.session.get(key)
    if not s:
        return None
    try:
        return base64.b64decode(s.encode("ascii"))
    except Exception:
        return None


@require_perm("mis.add_feesdetail")
def fees_import_template(request):
    header = ["DATE", "CLIENT_ID", "CLIENT_NAME", "FEES_AMOUNT", "GST_AMOUNT", "RECEIPTS_AMOUNT", "EXPENSES_AMOUNT"]
    sample = [["2026-05-10", "A00001", "ABC PRIVATE LIMITED", "10000", "1800", "", "500"]]
    return _xlsx_template_response("mis-fees-template.csv", header, sample)


@require_perm("mis.add_receipt")
def receipts_import_template(request):
    # kept for backward compatibility; use combined template
    return fees_import_template(request)


@require_perm("mis.add_expensedetail")
def expenses_import_template(request):
    # kept for backward compatibility; use combined template
    return fees_import_template(request)


def _client_by_id(client_id: str):
    from masters.models import Client

    return Client.approved_objects().filter(client_id__iexact=client_id.strip()).first()


@require_perm("mis.add_feesdetail")
def mis_bulk_import_template(request):
    header = ["DATE", "CLIENT_ID", "CLIENT_NAME", "FEES_AMOUNT", "GST_AMOUNT", "RECEIPTS_AMOUNT", "EXPENSES_AMOUNT"]
    sample = [
        ["2026-05-10", "A00001", "ABC PRIVATE LIMITED", "10000", "1800", "11800", "500"],
        ["2026-05-11", "B00002", "XYZ LLP", "5000", "900", "", ""],
    ]
    return _xlsx_template_response("mis-bulk-template.csv", header, sample)


@require_perm("mis.add_feesdetail")
def mis_bulk_import(request):
    # Requires at least add_feesdetail; superuser can do all. You can grant add_receipt/add_expensedetail too,
    # but this combined importer will only create those rows if you have the corresponding add permission.
    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = _session_get_file(request, "mis_bulk_import_file")
        if not raw:
            messages.error(request, "Nothing to import. Please upload the file again.")
            return redirect("mis_bulk_import")
        rows, file_errors = parse_mis_combined_csv(raw)
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("mis_bulk_import")
        bad = [r for r in rows if r.errors]
        if bad:
            messages.error(request, "File has errors. Fix and re-upload.")
            return render(
                request,
                "mis/import_preview_combined.html",
                {"rows": rows, "file_errors": file_errors, "can_import": False},
            )

        with transaction.atomic():
            for r in rows:
                c = _client_by_id(r.data["client_id"])
                if not c:
                    raise ValueError(f"Client not found for Client ID {r.data['client_id']}")
                if (c.client_name or "").strip().upper() != (r.data.get("client_name") or "").strip().upper():
                    raise ValueError(f"Client name mismatch for {r.data['client_id']}")

                fees = r.data.get("fees_amount")
                gst = r.data.get("gst_amount")
                receipts = r.data.get("receipts_amount")
                expenses = r.data.get("expenses_amount")

                if request.user.is_superuser or request.user.has_perm("mis.add_feesdetail"):
                    if fees is not None or gst is not None:
                        FeesDetail.objects.create(
                            date=r.data["date"],
                            client=c,
                            fees_amount=fees or Decimal("0.00"),
                            gst_amount=gst or Decimal("0.00"),
                        )

                if request.user.is_superuser or request.user.has_perm("mis.add_receipt"):
                    if receipts is not None:
                        Receipt.objects.create(date=r.data["date"], client=c, amount_received=receipts)

                if request.user.is_superuser or request.user.has_perm("mis.add_expensedetail"):
                    if expenses is not None:
                        ExpenseDetail.objects.create(date=r.data["date"], client=c, expenses_paid=expenses, notes="")

        request.session.pop("mis_bulk_import_file", None)
        messages.success(request, f"Imported {len(rows)} row(s) into MIS.")
        return redirect("mis_fees_list")

    if request.method == "POST":
        f = request.FILES.get("upload_file")
        if not f:
            messages.error(request, "Please choose a CSV file (.csv).")
            return redirect("mis_bulk_import")
        raw = f.read()
        _session_put_file(request, "mis_bulk_import_file", raw)
        rows, file_errors = parse_mis_combined_csv(raw)
        for r in rows:
            cid = (r.data.get("client_id") or "").strip()
            c = _client_by_id(cid) if cid else None
            if cid and not c:
                r.errors.append("CLIENT_ID not found in Client Master.")
            elif c and (c.client_name or "").strip().upper() != (r.data.get("client_name") or "").strip().upper():
                r.errors.append("CLIENT_NAME does not match Client Master for this CLIENT_ID.")
        can_import = bool(rows) and all(not r.errors for r in rows) and not file_errors
        return render(
            request,
            "mis/import_preview_combined.html",
            {"rows": rows, "file_errors": file_errors, "can_import": can_import},
        )

    return render(request, "mis/import_combined.html")


@require_perm("mis.add_feesdetail")
def fees_import(request):
    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = _session_get_file(request, "mis_fees_import_xlsx")
        if not raw:
            messages.error(request, "Nothing to import. Please upload the file again.")
            return redirect("mis_fees_import")
        kind = request.session.get("mis_fees_import_kind") or "csv"
        rows, file_errors = (parse_fees_csv(raw) if kind == "csv" else parse_fees_xlsx(raw))
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("mis_fees_import")
        bad = [r for r in rows if r.errors]
        if bad:
            messages.error(request, "File has errors. Fix and re-upload.")
            return render(
                request,
                "mis/import_preview.html",
                {"rows": rows, "file_errors": file_errors, "mode": "fees", "can_import": False},
            )
        with transaction.atomic():
            for r in rows:
                c = _client_by_id(r.data["client_id"])
                if not c:
                    raise ValueError(f"Client not found for Client ID {r.data['client_id']}")
                if (c.client_name or "").strip().upper() != (r.data.get("client_name") or "").strip().upper():
                    raise ValueError(f"Client name mismatch for {r.data['client_id']}")
                FeesDetail.objects.create(
                    date=r.data["date"],
                    client=c,
                    fees_amount=r.data["fees_amount"],
                    gst_amount=r.data["gst_amount"],
                )
        request.session.pop("mis_fees_import_xlsx", None)
        messages.success(request, f"Imported {len(rows)} fee row(s).")
        return redirect("mis_fees_list")

    if request.method == "POST":
        f = request.FILES.get("upload_file")
        if not f:
            messages.error(request, "Please choose a file (.csv or .xlsx).")
            return redirect("mis_fees_import")
        raw = f.read()
        _session_put_file(request, "mis_fees_import_xlsx", raw)
        name = (getattr(f, "name", "") or "").lower()
        kind = "xlsx" if name.endswith(".xlsx") else "csv"
        request.session["mis_fees_import_kind"] = kind
        rows, file_errors = (parse_fees_xlsx(raw) if kind == "xlsx" else parse_fees_csv(raw))
        for r in rows:
            cid = (r.data.get("client_id") or "").strip()
            c = _client_by_id(cid) if cid else None
            if cid and not c:
                r.errors.append("CLIENT_ID not found in Client Master.")
            elif c and (c.client_name or "").strip().upper() != (r.data.get("client_name") or "").strip().upper():
                r.errors.append("CLIENT_NAME does not match Client Master for this CLIENT_ID.")
        can_import = bool(rows) and all(not r.errors for r in rows) and not file_errors
        return render(
            request,
            "mis/import_preview.html",
            {"rows": rows, "file_errors": file_errors, "mode": "fees", "can_import": can_import},
        )

    return render(request, "mis/import.html", {"mode": "fees"})


@require_perm("mis.add_receipt")
def receipts_import(request):
    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = _session_get_file(request, "mis_receipts_import_xlsx")
        if not raw:
            messages.error(request, "Nothing to import. Please upload the file again.")
            return redirect("mis_receipts_import")
        kind = request.session.get("mis_receipts_import_kind") or "csv"
        rows, file_errors = (parse_receipts_csv(raw) if kind == "csv" else parse_receipts_xlsx(raw))
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("mis_receipts_import")
        bad = [r for r in rows if r.errors]
        if bad:
            messages.error(request, "File has errors. Fix and re-upload.")
            return render(
                request,
                "mis/import_preview.html",
                {"rows": rows, "file_errors": file_errors, "mode": "receipts", "can_import": False},
            )
        with transaction.atomic():
            for r in rows:
                c = _client_by_id(r.data["client_id"])
                if not c:
                    raise ValueError(f"Client not found for Client ID {r.data['client_id']}")
                if (c.client_name or "").strip().upper() != (r.data.get("client_name") or "").strip().upper():
                    raise ValueError(f"Client name mismatch for {r.data['client_id']}")
                Receipt.objects.create(date=r.data["date"], client=c, amount_received=r.data["amount_received"])
        request.session.pop("mis_receipts_import_xlsx", None)
        messages.success(request, f"Imported {len(rows)} receipt row(s).")
        return redirect("mis_receipt_list")

    if request.method == "POST":
        f = request.FILES.get("upload_file")
        if not f:
            messages.error(request, "Please choose a file (.csv or .xlsx).")
            return redirect("mis_receipts_import")
        raw = f.read()
        _session_put_file(request, "mis_receipts_import_xlsx", raw)
        name = (getattr(f, "name", "") or "").lower()
        kind = "xlsx" if name.endswith(".xlsx") else "csv"
        request.session["mis_receipts_import_kind"] = kind
        rows, file_errors = (parse_receipts_xlsx(raw) if kind == "xlsx" else parse_receipts_csv(raw))
        for r in rows:
            cid = (r.data.get("client_id") or "").strip()
            c = _client_by_id(cid) if cid else None
            if cid and not c:
                r.errors.append("CLIENT_ID not found in Client Master.")
            elif c and (c.client_name or "").strip().upper() != (r.data.get("client_name") or "").strip().upper():
                r.errors.append("CLIENT_NAME does not match Client Master for this CLIENT_ID.")
        can_import = bool(rows) and all(not r.errors for r in rows) and not file_errors
        return render(
            request,
            "mis/import_preview.html",
            {"rows": rows, "file_errors": file_errors, "mode": "receipts", "can_import": can_import},
        )

    return render(request, "mis/import.html", {"mode": "receipts"})


@require_perm("mis.add_expensedetail")
def expenses_import(request):
    if request.method == "POST" and request.POST.get("confirm") == "1":
        raw = _session_get_file(request, "mis_expenses_import_xlsx")
        if not raw:
            messages.error(request, "Nothing to import. Please upload the file again.")
            return redirect("mis_expenses_import")
        kind = request.session.get("mis_expenses_import_kind") or "csv"
        rows, file_errors = (parse_expenses_csv(raw) if kind == "csv" else parse_expenses_xlsx(raw))
        if file_errors:
            messages.error(request, file_errors[0])
            return redirect("mis_expenses_import")
        bad = [r for r in rows if r.errors]
        if bad:
            messages.error(request, "File has errors. Fix and re-upload.")
            return render(
                request,
                "mis/import_preview.html",
                {"rows": rows, "file_errors": file_errors, "mode": "expenses", "can_import": False},
            )
        with transaction.atomic():
            for r in rows:
                c = _client_by_id(r.data["client_id"])
                if not c:
                    raise ValueError(f"Client not found for Client ID {r.data['client_id']}")
                if (c.client_name or "").strip().upper() != (r.data.get("client_name") or "").strip().upper():
                    raise ValueError(f"Client name mismatch for {r.data['client_id']}")
                ExpenseDetail.objects.create(
                    date=r.data["date"],
                    client=c,
                    expenses_paid=r.data["expenses_paid"],
                    notes=(
                        f"Fees Amount: {r.data.get('fees_amount')} | "
                        if r.data.get("fees_amount") is not None
                        else ""
                    ),
                )
        request.session.pop("mis_expenses_import_xlsx", None)
        messages.success(request, f"Imported {len(rows)} expense row(s).")
        return redirect("mis_expense_list")

    if request.method == "POST":
        f = request.FILES.get("upload_file")
        if not f:
            messages.error(request, "Please choose a file (.csv or .xlsx).")
            return redirect("mis_expenses_import")
        raw = f.read()
        _session_put_file(request, "mis_expenses_import_xlsx", raw)
        name = (getattr(f, "name", "") or "").lower()
        kind = "xlsx" if name.endswith(".xlsx") else "csv"
        request.session["mis_expenses_import_kind"] = kind
        rows, file_errors = (parse_expenses_xlsx(raw) if kind == "xlsx" else parse_expenses_csv(raw))
        for r in rows:
            cid = (r.data.get("client_id") or "").strip()
            c = _client_by_id(cid) if cid else None
            if cid and not c:
                r.errors.append("CLIENT_ID not found in Client Master.")
            elif c and (c.client_name or "").strip().upper() != (r.data.get("client_name") or "").strip().upper():
                r.errors.append("CLIENT_NAME does not match Client Master for this CLIENT_ID.")
        can_import = bool(rows) and all(not r.errors for r in rows) and not file_errors
        return render(
            request,
            "mis/import_preview.html",
            {"rows": rows, "file_errors": file_errors, "mode": "expenses", "can_import": can_import},
        )

    return render(request, "mis/import.html", {"mode": "expenses"})

