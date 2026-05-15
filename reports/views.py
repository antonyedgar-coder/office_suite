import csv
from collections import defaultdict
from datetime import date
from io import StringIO

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render

from dirkyc.fy import fy_label_to_date_range
from dirkyc.models import Dir3Kyc
from masters.models import DIRECTOR_COMPANY_TYPES, DIRECTOR_ELIGIBLE_CLIENT_TYPES, Client, DirectorMapping
from mis.models import ExpenseDetail, FeesDetail, Receipt

from .dir3_compliance import build_director_dir3_compliance_rows
from .forms import (
    ClientMasterReportFilterForm,
    DirectorMappingReportForm,
    Dir3KycReportForm,
    MISClientWiseFilterForm,
    MISFlexibleReportForm,
    MISPeriodFilterForm,
    MISTypeWiseFilterForm,
)

from core.decorators import require_perm


def _normalize_upper(v: str) -> str:
    return (v or "").strip().upper()


def _can_suggest_directors(user) -> bool:
    return user.is_superuser or user.has_perm("reports.view_director_mapping_report") or user.has_perm(
        "reports.view_dir3kyc_report"
    )


@login_required
def api_suggest_directors(request):
    if not _can_suggest_directors(request.user):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    slot = (request.GET.get("slot") or "any").strip().lower()
    q = (request.GET.get("q") or "").strip()
    if len(q) < 1:
        return JsonResponse({"results": []})
    qs = Client.approved_objects().filter(
        client_type__in=sorted(DIRECTOR_ELIGIBLE_CLIENT_TYPES), is_director=True
    ).exclude(din="")
    qu = _normalize_upper(q)
    if slot == "din":
        qs = qs.filter(din__icontains=qu)
    elif slot == "name":
        qs = qs.filter(client_name__icontains=qu)
    else:
        qs = qs.filter(Q(din__icontains=qu) | Q(client_name__icontains=qu) | Q(client_id__icontains=qu))
    qs = qs.order_by("client_name")[:25]
    results = []
    for c in qs:
        label = f"{c.client_name} — DIN {c.din} — {c.client_id}"
        if slot == "din":
            val = (c.din or "").strip().upper()
        elif slot == "name":
            val = (c.client_name or "").strip()
        else:
            val = c.client_id
        results.append({"value": val, "label": label})
    return JsonResponse({"results": results})


@login_required
def api_suggest_companies(request):
    u = request.user
    if not (u.is_superuser or u.has_perm("reports.view_director_mapping_report")):
        return JsonResponse({"detail": "Forbidden"}, status=403)
    slot = (request.GET.get("slot") or "any").strip().lower()
    q = (request.GET.get("q") or "").strip()
    if len(q) < 1:
        return JsonResponse({"results": []})
    qs = Client.approved_objects().filter(client_type__in=sorted(DIRECTOR_COMPANY_TYPES))
    qu = _normalize_upper(q)
    if slot == "cin":
        qs = qs.filter(Q(cin__icontains=qu) | Q(llpin__icontains=qu))
    elif slot == "name":
        qs = qs.filter(client_name__icontains=qu)
    else:
        qs = qs.filter(
            Q(client_name__icontains=qu)
            | Q(client_id__icontains=qu)
            | Q(cin__icontains=qu)
            | Q(llpin__icontains=qu)
        )
    qs = qs.order_by("client_name")[:25]
    results = []
    for c in qs:
        cinp = (c.cin or "").strip().upper()
        llp = (c.llpin or "").strip().upper()
        reg = ""
        if cinp:
            reg = f"CIN {cinp}"
        if llp:
            reg = (reg + " · " if reg else "") + f"LLPIN {llp}"
        label = f"{c.client_name} — {c.client_id} ({c.client_type})" + (f" — {reg}" if reg else "")
        if slot == "cin":
            val = cinp or llp
        elif slot == "name":
            val = (c.client_name or "").strip()
        else:
            val = c.client_id
        results.append({"value": val, "label": label})
    return JsonResponse({"results": results})


def _apply_client_filters(qs, form: ClientMasterReportFilterForm):
    """AND combination of all provided filters."""
    if not form.is_valid():
        return qs.none()

    cd = form.cleaned_data
    t = cd.get("client_type") or ""
    if t:
        qs = qs.filter(client_type=t)

    br = cd.get("branch") or ""
    if br:
        qs = qs.filter(branch=br)

    name = (cd.get("client_name") or "").strip()
    if name:
        qs = qs.filter(client_name__icontains=_normalize_upper(name))

    din = (cd.get("din") or "").strip()
    if din:
        qs = qs.filter(din__icontains=din)

    pan = (cd.get("pan") or "").strip()
    if pan:
        qs = qs.filter(pan__icontains=_normalize_upper(pan))

    gstin = (cd.get("gstin") or "").strip()
    if gstin:
        qs = qs.filter(gstin__icontains=_normalize_upper(gstin))

    cin = (cd.get("cin") or "").strip()
    if cin:
        qs = qs.filter(cin__icontains=_normalize_upper(cin))

    llpin = (cd.get("llpin") or "").strip()
    if llpin:
        qs = qs.filter(llpin__icontains=_normalize_upper(llpin))

    director_flag = cd.get("is_director") or ""
    if director_flag == "1":
        qs = qs.filter(is_director=True)
    elif director_flag == "0":
        qs = qs.filter(is_director=False)

    return qs.select_related("client_group").order_by("client_name")


CLIENT_MASTER_CSV_COLUMNS = [
    "CLIENT_ID",
    "CLIENT_TYPE",
    "BRANCH",
    "CLIENT_NAME",
    "GROUP",
    "FILE_NO",
    "PAN",
    "PASSPORT_NO",
    "AADHAAR_NO",
    "GSTIN",
    "DOB",
    "LLPIN",
    "CIN",
    "IS_DIRECTOR",
    "DIN",
    "ADDRESS",
    "CONTACT_PERSON",
    "MOBILE",
    "EMAIL",
]


@login_required
def report_index(request):
    """
    /reports/ — users who can open Client Master go straight there; others with only
    access_reports_menu see this overview (placeholders for Client Master / Employee Report).
    """
    u = request.user
    if u.is_superuser or u.has_perm("reports.view_client_master_report") or u.has_perm(
        "reports.export_client_master_report"
    ):
        return redirect("reports_client_master")
    if u.is_superuser or u.has_perm("reports.view_director_mapping_report"):
        return redirect("reports_director_mapping")
    if u.is_superuser or u.has_perm("reports.view_dir3kyc_report"):
        return redirect("reports_dir3kyc")
    if u.has_perm("reports.access_reports_menu"):
        return render(request, "reports/index.html")
    raise PermissionDenied


@require_perm("reports.view_client_master_report")
def client_master_report(request):
    form = ClientMasterReportFilterForm(request.GET or None)
    base = Client.approved_objects().select_related("client_group")
    qs = base.all()
    count = 0
    clients = []

    if request.GET:
        if form.is_valid():
            qs = _apply_client_filters(base, form)
            count = qs.count()
            clients = list(qs[:500])
    else:
        form = ClientMasterReportFilterForm()

    return render(
        request,
        "reports/client_master_report.html",
        {
            "form": form,
            "clients": clients,
            "count": count,
            "truncated": count > 500,
        },
    )


@require_perm("reports.export_client_master_report")
def client_master_report_csv(request):
    base = Client.approved_objects().select_related("client_group")
    if not request.GET:
        qs = base.order_by("client_name")
    else:
        form = ClientMasterReportFilterForm(request.GET)
        if not form.is_valid():
            return HttpResponse("Invalid filters.", status=400)
        qs = _apply_client_filters(base, form)

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(CLIENT_MASTER_CSV_COLUMNS)

    for c in qs.iterator(chunk_size=500):
        writer.writerow(
            [
                c.client_id,
                c.client_type,
                c.branch,
                c.client_name,
                c.client_group.name if c.client_group_id else "",
                c.file_no,
                c.pan,
                c.passport_no,
                c.aadhaar_no,
                c.gstin,
                c.dob.strftime("%d-%m-%Y") if c.dob else "",
                c.llpin,
                c.cin,
                "YES" if c.is_director else "",
                c.din,
                c.address,
                c.contact_person,
                c.mobile,
                c.email,
            ]
        )

    response = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    filename = "client-master-report.csv"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _dt_range(form):
    cd = form.cleaned_data
    return cd["from_date"], cd["to_date"]


MIS_MONTH_LABELS = [
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
    "January",
    "February",
    "March",
]

MIS_DETAIL_ORDER = ("FEES", "GST", "RECEIPTS", "EXPENSES")
_MIS_DETAIL_FIELD = {"FEES": "fees", "GST": "gst", "RECEIPTS": "receipts", "EXPENSES": "expenses"}


def _mis_metric_float(block: dict | None, dk: str) -> float:
    if not block:
        return 0.0
    return float(block.get(_MIS_DETAIL_FIELD[dk]) or 0)


def _mis_prune_row_col_bool(matrix: list[list[float]]) -> tuple[list[bool], list[bool]]:
    """Remove rows/columns that are entirely zero (iterates until stable)."""
    if not matrix:
        return [], []
    n_r = len(matrix)
    n_c = len(matrix[0])
    row_keep = [True] * n_r
    col_keep = [True] * n_c
    while True:
        col_new = []
        for c in range(n_c):
            nz = False
            for r in range(n_r):
                if not row_keep[r]:
                    continue
                if matrix[r][c] != 0.0:
                    nz = True
                    break
            col_new.append(nz)
        row_new = []
        for r in range(n_r):
            nz = False
            for c in range(n_c):
                if not col_new[c]:
                    continue
                if matrix[r][c] != 0.0:
                    nz = True
                    break
            row_new.append(nz)
        if col_new == col_keep and row_new == row_keep:
            break
        col_keep, row_keep = col_new, row_new
    return row_keep, col_keep


def _mis_sparse_metric_table(rows: list[dict], detail_order: list[str]) -> tuple[list[dict], list[str], dict]:
    """
    Drop rows where all selected metrics are zero, and metrics that are zero for all remaining rows.
    Returns filtered rows, visible detail keys (order preserved), and totals over visible columns only.
    """
    empty_totals = {"fees": 0, "gst": 0, "receipts": 0, "expenses": 0}
    if not rows or not detail_order:
        return [], [], empty_totals
    fields = [_MIS_DETAIL_FIELD[dk] for dk in detail_order]
    matrix = [[float(rows[i].get(f) or 0) for f in fields] for i in range(len(rows))]
    row_keep, col_keep = _mis_prune_row_col_bool(matrix)
    visible_detail_order = [detail_order[c] for c in range(len(detail_order)) if col_keep[c]]
    sparse_rows = [rows[i] for i in range(len(rows)) if row_keep[i]]
    totals = {"fees": 0, "gst": 0, "receipts": 0, "expenses": 0}
    for r in sparse_rows:
        for dk in visible_detail_order:
            totals[_MIS_DETAIL_FIELD[dk]] += float(r.get(_MIS_DETAIL_FIELD[dk]) or 0)
    return sparse_rows, visible_detail_order, totals


def _mis_sparse_month_multi_pivot(
    pivot_rows: list[dict],
    fy_columns: list[str],
    detail_order: list[str],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """
    Month × (FY × metric) grid: drop all-zero rows (months) and all-zero columns.
    Returns body rows (month_label + cells), column_specs, footer_cells, fy_header_groups.
    """
    if not pivot_rows or not fy_columns or not detail_order:
        return [], [], [], []

    n_r = len(pivot_rows)
    n_f = len(fy_columns)
    n_d = len(detail_order)
    n_c = n_f * n_d

    matrix: list[list[float]] = []
    for i in range(n_r):
        row: list[float] = []
        for fi in range(n_f):
            block = pivot_rows[i]["by_fy"][fi]
            for dk in detail_order:
                row.append(_mis_metric_float(block, dk))
        matrix.append(row)

    row_keep, col_keep = _mis_prune_row_col_bool(matrix)
    col_indices = [c for c in range(n_c) if col_keep[c]]

    column_specs: list[dict] = []
    prev_fy_lbl: str | None = None
    for idx_c, c in enumerate(col_indices):
        fi = c // n_d
        di = c % n_d
        fy_lbl = fy_columns[fi]
        group_start = idx_c > 0 and fy_lbl != prev_fy_lbl
        prev_fy_lbl = fy_lbl
        column_specs.append({"fy": fy_lbl, "dk": detail_order[di], "group_start": group_start})

    body_rows: list[dict] = []
    for i in range(n_r):
        if not row_keep[i]:
            continue
        vals = [matrix[i][c] for c in col_indices]
        cells = [{"val": vals[j], "group_start": column_specs[j]["group_start"]} for j in range(len(vals))]
        body_rows.append({"month_label": pivot_rows[i]["month_label"], "cells": cells})

    footer_vals_raw = [sum(matrix[i][c] for i in range(n_r) if row_keep[i]) for c in col_indices]
    footer_cells = [
        {"val": footer_vals_raw[j], "group_start": column_specs[j]["group_start"]}
        for j in range(len(column_specs))
    ]

    fy_groups: list[dict] = []
    for spec in column_specs:
        if fy_groups and fy_groups[-1]["fy"] == spec["fy"]:
            fy_groups[-1]["colspan"] += 1
        else:
            fy_groups.append({"fy": spec["fy"], "colspan": 1})

    return body_rows, column_specs, footer_cells, fy_groups


def _calendar_date_to_fy_month_index(d: date) -> int:
    """Map a calendar date inside an Indian FY to 0=April .. 11=March."""
    if d.month >= 4:
        return d.month - 4
    return d.month + 8


def _mis_apply_client_filters_to_qs(fees_q, rec_q, exp_q, *, client_id: str, client_name: str, pan: str, client_type: str, branch: str):
    if client_id:
        fees_q = fees_q.filter(client__client_id__icontains=client_id.strip().upper())
        rec_q = rec_q.filter(client__client_id__icontains=client_id.strip().upper())
        exp_q = exp_q.filter(client__client_id__icontains=client_id.strip().upper())
    if client_name:
        fees_q = fees_q.filter(client__client_name__icontains=client_name.strip().upper())
        rec_q = rec_q.filter(client__client_name__icontains=client_name.strip().upper())
        exp_q = exp_q.filter(client__client_name__icontains=client_name.strip().upper())
    if pan:
        fees_q = fees_q.filter(client__pan__icontains=pan.strip().upper())
        rec_q = rec_q.filter(client__pan__icontains=pan.strip().upper())
        exp_q = exp_q.filter(client__pan__icontains=pan.strip().upper())
    if client_type:
        fees_q = fees_q.filter(client__client_type=client_type)
        rec_q = rec_q.filter(client__client_type=client_type)
        exp_q = exp_q.filter(client__client_type=client_type)
    if branch:
        fees_q = fees_q.filter(client__branch=branch)
        rec_q = rec_q.filter(client__branch=branch)
        exp_q = exp_q.filter(client__branch=branch)
    return fees_q, rec_q, exp_q


def _mis_month_slots_for_fy(
    fy_label: str,
    *,
    client_id: str,
    client_name: str,
    pan: str,
    client_type: str,
    branch: str,
) -> list[dict] | None:
    bounds = fy_label_to_date_range(fy_label.strip())
    if not bounds:
        return None
    start, end = bounds

    fees_q = FeesDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=start, date__lte=end)
    rec_q = Receipt.objects.filter(client__approval_status=Client.APPROVED, date__gte=start, date__lte=end)
    exp_q = ExpenseDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=start, date__lte=end)
    fees_q, rec_q, exp_q = _mis_apply_client_filters_to_qs(
        fees_q,
        rec_q,
        exp_q,
        client_id=client_id,
        client_name=client_name,
        pan=pan,
        client_type=client_type,
        branch=branch,
    )

    slots: list[dict] = [{"fees": 0, "gst": 0, "receipts": 0, "expenses": 0} for _ in range(12)]

    fees_rows = fees_q.annotate(m=TruncMonth("date")).values("m").annotate(fees=Sum("fees_amount"), gst=Sum("gst_amount"))
    for r in fees_rows:
        dt = r["m"]
        if dt is None:
            continue
        d = dt.date() if hasattr(dt, "date") else dt
        idx = _calendar_date_to_fy_month_index(d)
        if 0 <= idx < 12:
            slots[idx]["fees"] = r["fees"] or 0
            slots[idx]["gst"] = r["gst"] or 0

    rec_rows = rec_q.annotate(m=TruncMonth("date")).values("m").annotate(receipts=Sum("amount_received"))
    for r in rec_rows:
        dt = r["m"]
        if dt is None:
            continue
        d = dt.date() if hasattr(dt, "date") else dt
        idx = _calendar_date_to_fy_month_index(d)
        if 0 <= idx < 12:
            slots[idx]["receipts"] = r["receipts"] or 0

    exp_rows = exp_q.annotate(m=TruncMonth("date")).values("m").annotate(expenses=Sum("expenses_paid"))
    for r in exp_rows:
        dt = r["m"]
        if dt is None:
            continue
        d = dt.date() if hasattr(dt, "date") else dt
        idx = _calendar_date_to_fy_month_index(d)
        if 0 <= idx < 12:
            slots[idx]["expenses"] = r["expenses"] or 0

    return slots


def _mis_merge_period(
    from_date,
    to_date,
    *,
    client_id: str = "",
    client_name: str = "",
    pan: str = "",
    client_type: str = "",
    branch: str = "",
):
    fees_q = (
        FeesDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=from_date, date__lte=to_date)
        .values(
            "date",
            "client__client_id",
            "client__client_name",
            "client__pan",
            "client__client_type",
            "client__branch",
        )
        .annotate(fees=Sum("fees_amount"), gst=Sum("gst_amount"))
    )
    rec_q = (
        Receipt.objects.filter(client__approval_status=Client.APPROVED, date__gte=from_date, date__lte=to_date)
        .values(
            "date",
            "client__client_id",
            "client__client_name",
            "client__pan",
            "client__client_type",
            "client__branch",
        )
        .annotate(receipts=Sum("amount_received"))
    )
    exp_q = (
        ExpenseDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=from_date, date__lte=to_date)
        .values(
            "date",
            "client__client_id",
            "client__client_name",
            "client__pan",
            "client__client_type",
            "client__branch",
        )
        .annotate(expenses=Sum("expenses_paid"))
    )

    fees_q, rec_q, exp_q = _mis_apply_client_filters_to_qs(
        fees_q,
        rec_q,
        exp_q,
        client_id=client_id,
        client_name=client_name,
        pan=pan,
        client_type=client_type,
        branch=branch,
    )

    merged = {}
    def _base(r):
        return {
            "date": r["date"],
            "client_id": r["client__client_id"],
            "client_name": r["client__client_name"],
            "pan": r.get("client__pan") or "",
            "client_type": r.get("client__client_type") or "",
            "branch": r.get("client__branch") or "",
            "fees": 0,
            "gst": 0,
            "receipts": 0,
            "expenses": 0,
        }

    for r in fees_q:
        k = (r["date"], r["client__client_id"])
        row = _base(r)
        row["fees"] = r["fees"] or 0
        row["gst"] = r["gst"] or 0
        merged[k] = row
    for r in rec_q:
        k = (r["date"], r["client__client_id"])
        merged.setdefault(k, _base(r))["receipts"] = r["receipts"] or 0
    for r in exp_q:
        k = (r["date"], r["client__client_id"])
        merged.setdefault(k, _base(r))["expenses"] = r["expenses"] or 0

    rows = sorted(merged.values(), key=lambda x: (x["date"], x["client_id"]))
    totals = {"fees": 0, "gst": 0, "receipts": 0, "expenses": 0}
    for r in rows:
        totals["fees"] += r["fees"]
        totals["gst"] += r["gst"]
        totals["receipts"] += r["receipts"]
        totals["expenses"] += r["expenses"]
    return rows, totals


@require_perm("reports.access_reports_menu")
def mis_report(request):
    """
    Single MIS report page with flexible details selection.
    Columns: Date, Client ID, Client Name, PAN, Type + selected details columns.
    """
    form = MISFlexibleReportForm(request.GET or None)
    rows = []
    totals = {"fees": 0, "gst": 0, "receipts": 0, "expenses": 0}
    details = ["FEES", "GST", "RECEIPTS", "EXPENSES"]

    report_view = MISFlexibleReportForm.VIEW_TRANSACTIONS
    mis_month_mode = False
    mis_month_multi_fy = False
    mis_month_rows: list[dict] = []
    mis_month_pivot_rows: list[dict] = []
    mis_fy_columns: list[str] = []
    mis_month_multi_footer: list[dict | None] = []
    mis_month_multi_body: list[dict] = []
    mis_multi_column_specs: list[dict] = []
    mis_multi_footer_cells: list[dict] = []
    mis_multi_fy_groups: list[dict] = []
    mis_metric_columns: list[str] = [k for k in MIS_DETAIL_ORDER if k in details]

    if request.GET and form.is_valid():
        details = form.selected_details()
        detail_order = [k for k in MIS_DETAIL_ORDER if k in details]
        mis_metric_columns = list(detail_order)
        report_view = form.cleaned_data.get("report_view") or MISFlexibleReportForm.VIEW_TRANSACTIONS

        if report_view == MISFlexibleReportForm.VIEW_MONTH_WISE:
            mis_month_mode = True
            fy_raw = form.cleaned_data.get("financial_years") or []
            fy_list = sorted(set(fy_raw), key=lambda s: int(s.split("-")[0]))
            cid_m = form.cleaned_data.get("client_id") or ""
            name_m = form.cleaned_data.get("client_name") or ""
            pan_m = form.cleaned_data.get("pan") or ""
            ct_m = form.cleaned_data.get("client_type") or ""
            br_m = form.cleaned_data.get("branch") or ""

            month_slots_by_fy: dict[str, list[dict]] = {}
            for fy in fy_list:
                slots = _mis_month_slots_for_fy(
                    fy,
                    client_id=cid_m,
                    client_name=name_m,
                    pan=pan_m,
                    client_type=ct_m,
                    branch=br_m,
                )
                if slots:
                    month_slots_by_fy[fy] = slots

            if len(fy_list) == 1 and fy_list:
                fy_one = fy_list[0]
                slots_one = month_slots_by_fy.get(fy_one)
                if slots_one:
                    mis_month_rows = [{**slots_one[i], "month_label": MIS_MONTH_LABELS[i]} for i in range(12)]
                    totals = {
                        "fees": sum(slots_one[i]["fees"] for i in range(12)),
                        "gst": sum(slots_one[i]["gst"] for i in range(12)),
                        "receipts": sum(slots_one[i]["receipts"] for i in range(12)),
                        "expenses": sum(slots_one[i]["expenses"] for i in range(12)),
                    }
                    mis_month_rows, mis_metric_columns, totals = _mis_sparse_metric_table(mis_month_rows, detail_order)
            elif len(fy_list) > 1:
                mis_month_multi_fy = True
                mis_fy_columns = fy_list
                pivot_rows = []
                for i in range(12):
                    blocks: list[dict | None] = []
                    for fy in fy_list:
                        s = month_slots_by_fy.get(fy)
                        if not s:
                            blocks.append(None)
                        else:
                            blocks.append(
                                {
                                    "fees": s[i]["fees"],
                                    "gst": s[i]["gst"],
                                    "receipts": s[i]["receipts"],
                                    "expenses": s[i]["expenses"],
                                }
                            )
                    pivot_rows.append({"month_label": MIS_MONTH_LABELS[i], "by_fy": blocks})
                mis_month_pivot_rows = pivot_rows
                (
                    mis_month_multi_body,
                    mis_multi_column_specs,
                    mis_multi_footer_cells,
                    mis_multi_fy_groups,
                ) = _mis_sparse_month_multi_pivot(pivot_rows, fy_list, detail_order)
                mis_metric_columns = list(dict.fromkeys(sp["dk"] for sp in mis_multi_column_specs))

        elif report_view == MISFlexibleReportForm.VIEW_TYPE_WISE:
            f, t = _dt_range(form)
            # consolidated type-wise totals for period (ignore client id/name/pan filters)
            ct = (form.cleaned_data.get("client_type") or "").strip()
            br = (form.cleaned_data.get("branch") or "").strip()
            fees_q = FeesDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
            rec_q = Receipt.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
            exp_q = ExpenseDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
            if ct:
                fees_q = fees_q.filter(client__client_type=ct)
                rec_q = rec_q.filter(client__client_type=ct)
                exp_q = exp_q.filter(client__client_type=ct)
            if br:
                fees_q = fees_q.filter(client__branch=br)
                rec_q = rec_q.filter(client__branch=br)
                exp_q = exp_q.filter(client__branch=br)

            fees_a = fees_q.values("client__client_type").annotate(fees=Sum("fees_amount"), gst=Sum("gst_amount"))
            rec_a = rec_q.values("client__client_type").annotate(receipts=Sum("amount_received"))
            exp_a = exp_q.values("client__client_type").annotate(expenses=Sum("expenses_paid"))

            rec_map = {r["client__client_type"] or "": r["receipts"] or 0 for r in rec_a}
            exp_map = {r["client__client_type"] or "": r["expenses"] or 0 for r in exp_a}

            rows = []
            for r in fees_a:
                k = r["client__client_type"] or ""
                rows.append(
                    {
                        "client_type": k,
                        "fees": r["fees"] or 0,
                        "gst": r["gst"] or 0,
                        "receipts": rec_map.get(k, 0),
                        "expenses": exp_map.get(k, 0),
                    }
                )
            existing = {r["client_type"] for r in rows}
            only_types = set(rec_map.keys()) | set(exp_map.keys())
            for k in sorted([x for x in only_types if x not in existing]):
                rows.append(
                    {"client_type": k, "fees": 0, "gst": 0, "receipts": rec_map.get(k, 0), "expenses": exp_map.get(k, 0)}
                )
            rows.sort(key=lambda x: x["client_type"])
            totals = {"fees": 0, "gst": 0, "receipts": 0, "expenses": 0}
            for r in rows:
                totals["fees"] += r["fees"]
                totals["gst"] += r["gst"]
                totals["receipts"] += r["receipts"]
                totals["expenses"] += r["expenses"]
            rows, mis_metric_columns, totals = _mis_sparse_metric_table(rows, detail_order)

        elif report_view == MISFlexibleReportForm.VIEW_CLIENT_WISE:
            f, t = _dt_range(form)
            # consolidated client-wise totals for period, with optional client filters
            cid_f = (form.cleaned_data.get("client_id") or "").strip().upper()
            name_f = (form.cleaned_data.get("client_name") or "").strip().upper()
            pan_f = (form.cleaned_data.get("pan") or "").strip().upper()
            ct_f = (form.cleaned_data.get("client_type") or "").strip()
            br_f = (form.cleaned_data.get("branch") or "").strip()

            fees_q = FeesDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
            rec_q = Receipt.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
            exp_q = ExpenseDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)

            if cid_f:
                fees_q = fees_q.filter(client__client_id__icontains=cid_f)
                rec_q = rec_q.filter(client__client_id__icontains=cid_f)
                exp_q = exp_q.filter(client__client_id__icontains=cid_f)
            if name_f:
                fees_q = fees_q.filter(client__client_name__icontains=name_f)
                rec_q = rec_q.filter(client__client_name__icontains=name_f)
                exp_q = exp_q.filter(client__client_name__icontains=name_f)
            if pan_f:
                fees_q = fees_q.filter(client__pan__icontains=pan_f)
                rec_q = rec_q.filter(client__pan__icontains=pan_f)
                exp_q = exp_q.filter(client__pan__icontains=pan_f)
            if ct_f:
                fees_q = fees_q.filter(client__client_type=ct_f)
                rec_q = rec_q.filter(client__client_type=ct_f)
                exp_q = exp_q.filter(client__client_type=ct_f)
            if br_f:
                fees_q = fees_q.filter(client__branch=br_f)
                rec_q = rec_q.filter(client__branch=br_f)
                exp_q = exp_q.filter(client__branch=br_f)

            fees_a = (
                fees_q.values(
                    "client__client_id",
                    "client__client_name",
                    "client__pan",
                    "client__client_type",
                    "client__branch",
                )
                .annotate(fees=Sum("fees_amount"), gst=Sum("gst_amount"))
                .order_by("client__client_name")
            )
            rec_a = rec_q.values("client__client_id").annotate(receipts=Sum("amount_received"))
            exp_a = exp_q.values("client__client_id").annotate(expenses=Sum("expenses_paid"))
            rec_map = {r["client__client_id"]: r["receipts"] or 0 for r in rec_a}
            exp_map = {r["client__client_id"]: r["expenses"] or 0 for r in exp_a}

            rows = []
            totals = {"fees": 0, "gst": 0, "receipts": 0, "expenses": 0}
            for r in fees_a:
                cid = r["client__client_id"]
                row = {
                    "client_id": cid,
                    "client_name": r["client__client_name"],
                    "pan": r.get("client__pan") or "",
                    "client_type": r.get("client__client_type") or "",
                    "branch": r.get("client__branch") or "",
                    "fees": r["fees"] or 0,
                    "gst": r["gst"] or 0,
                    "receipts": rec_map.get(cid, 0),
                    "expenses": exp_map.get(cid, 0),
                }
                rows.append(row)
                totals["fees"] += row["fees"]
                totals["gst"] += row["gst"]
                totals["receipts"] += row["receipts"]
                totals["expenses"] += row["expenses"]

            existing = {r["client_id"] for r in rows}
            only_ids = set(rec_map.keys()) | set(exp_map.keys())
            missing = sorted([x for x in only_ids if x not in existing])
            if missing:
                name_map = {
                    c.client_id: (c.client_name, c.pan, c.client_type, c.branch)
                    for c in Client.approved_objects().filter(client_id__in=missing)
                }
                for cid in missing:
                    nm, panv, ctv, brv = name_map.get(cid, (cid, "", "", ""))
                    row = {
                        "client_id": cid,
                        "client_name": nm,
                        "pan": panv or "",
                        "client_type": ctv or "",
                        "branch": brv or "",
                        "fees": 0,
                        "gst": 0,
                        "receipts": rec_map.get(cid, 0),
                        "expenses": exp_map.get(cid, 0),
                    }
                    rows.append(row)
                    totals["receipts"] += row["receipts"]
                    totals["expenses"] += row["expenses"]
                rows.sort(key=lambda x: x["client_name"])
            rows, mis_metric_columns, totals = _mis_sparse_metric_table(rows, detail_order)
        else:
            f, t = _dt_range(form)
            rows, totals = _mis_merge_period(
                f,
                t,
                client_id=form.cleaned_data.get("client_id") or "",
                client_name=form.cleaned_data.get("client_name") or "",
                pan=form.cleaned_data.get("pan") or "",
                client_type=form.cleaned_data.get("client_type") or "",
                branch=form.cleaned_data.get("branch") or "",
            )
            rows, mis_metric_columns, totals = _mis_sparse_metric_table(rows, detail_order)

    client_suggestions = list(
        Client.approved_objects().only("client_id", "client_name", "pan").order_by("client_name")[:3000]
    )
    return render(
        request,
        "reports/mis_report.html",
        {
            "form": form,
            "rows": rows,
            "totals": totals,
            "details": details,
            "report_view": report_view,
            "client_suggestions": client_suggestions,
            "mis_month_mode": mis_month_mode,
            "mis_month_multi_fy": mis_month_multi_fy,
            "mis_month_rows": mis_month_rows,
            "mis_month_pivot_rows": mis_month_pivot_rows,
            "mis_fy_columns": mis_fy_columns,
            "mis_month_multi_footer": mis_month_multi_footer,
            "mis_fy_selected": request.GET.getlist("financial_years"),
            "mis_detail_order": mis_metric_columns,
            "mis_metric_columns": mis_metric_columns,
            "mis_month_multi_body": mis_month_multi_body,
            "mis_multi_column_specs": mis_multi_column_specs,
            "mis_multi_footer_cells": mis_multi_footer_cells,
            "mis_multi_fy_groups": mis_multi_fy_groups,
        },
    )


@require_perm("reports.export_mis_report")
def mis_report_csv(request):
    form = MISFlexibleReportForm(request.GET or None)
    if not request.GET or not form.is_valid():
        return HttpResponse("Invalid filters.", status=400)
    details = form.selected_details()
    report_view = form.cleaned_data.get("report_view") or MISFlexibleReportForm.VIEW_TRANSACTIONS

    if report_view == MISFlexibleReportForm.VIEW_MONTH_WISE:
        detail_order = [k for k in MIS_DETAIL_ORDER if k in details]
        fy_raw = form.cleaned_data.get("financial_years") or []
        fy_list = sorted(set(fy_raw), key=lambda s: int(s.split("-")[0]))
        if not fy_list:
            return HttpResponse("Select at least one financial year.", status=400)
        cid_m = form.cleaned_data.get("client_id") or ""
        name_m = form.cleaned_data.get("client_name") or ""
        pan_m = form.cleaned_data.get("pan") or ""
        ct_m = form.cleaned_data.get("client_type") or ""
        br_m = form.cleaned_data.get("branch") or ""
        month_slots_by_fy: dict[str, list[dict]] = {}
        for fy in fy_list:
            slots = _mis_month_slots_for_fy(
                fy,
                client_id=cid_m,
                client_name=name_m,
                pan=pan_m,
                client_type=ct_m,
                branch=br_m,
            )
            if slots:
                month_slots_by_fy[fy] = slots

        buf = StringIO()
        w = csv.writer(buf)
        csv_hdr_detail = {"FEES": "FEES_AMOUNT", "GST": "GST_AMOUNT", "RECEIPTS": "RECEIPTS_AMOUNT", "EXPENSES": "EXPENSES_AMOUNT"}
        csv_lbl_detail = {"FEES": "Fees", "GST": "GST", "RECEIPTS": "Receipts", "EXPENSES": "Expenses"}

        if len(fy_list) == 1:
            fy_one = fy_list[0]
            slots_one = month_slots_by_fy.get(fy_one)
            if not slots_one:
                slots_one = [{"fees": 0, "gst": 0, "receipts": 0, "expenses": 0} for _ in range(12)]
            mis_month_rows = [{**slots_one[i], "month_label": MIS_MONTH_LABELS[i]} for i in range(12)]
            sparse_rows, vis_detail, tot_sparse = _mis_sparse_metric_table(mis_month_rows, detail_order)
            header = ["MONTH"] + [csv_hdr_detail[dk] for dk in vis_detail]
            w.writerow(header)
            for r in sparse_rows:
                row = [r["month_label"]] + [r[_MIS_DETAIL_FIELD[dk]] for dk in vis_detail]
                w.writerow(row)
            total_row = ["TOTAL"] + [tot_sparse[_MIS_DETAIL_FIELD[dk]] for dk in vis_detail]
            w.writerow(total_row)
        else:
            pivot_rows = []
            for i in range(12):
                blocks: list[dict | None] = []
                for fy in fy_list:
                    s = month_slots_by_fy.get(fy)
                    if not s:
                        blocks.append(None)
                    else:
                        blocks.append(
                            {
                                "fees": s[i]["fees"],
                                "gst": s[i]["gst"],
                                "receipts": s[i]["receipts"],
                                "expenses": s[i]["expenses"],
                            }
                        )
                pivot_rows.append({"month_label": MIS_MONTH_LABELS[i], "by_fy": blocks})
            body_rows, column_specs, footer_cells, _fy_g = _mis_sparse_month_multi_pivot(pivot_rows, fy_list, detail_order)
            header = ["MONTH"] + [f"{s['fy']} {csv_lbl_detail[s['dk']]}" for s in column_specs]
            w.writerow(header)
            for r in body_rows:
                w.writerow([r["month_label"]] + [c["val"] for c in r["cells"]])
            w.writerow(["TOTAL"] + [fc["val"] for fc in footer_cells])

        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="mis-month-wise-report.csv"'
        return resp

    f, t = _dt_range(form)

    if report_view == MISFlexibleReportForm.VIEW_TYPE_WISE:
        detail_order = [k for k in MIS_DETAIL_ORDER if k in details]
        ct = (form.cleaned_data.get("client_type") or "").strip()
        br = (form.cleaned_data.get("branch") or "").strip()
        fees_q = FeesDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
        rec_q = Receipt.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
        exp_q = ExpenseDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
        if ct:
            fees_q = fees_q.filter(client__client_type=ct)
            rec_q = rec_q.filter(client__client_type=ct)
            exp_q = exp_q.filter(client__client_type=ct)
        if br:
            fees_q = fees_q.filter(client__branch=br)
            rec_q = rec_q.filter(client__branch=br)
            exp_q = exp_q.filter(client__branch=br)

        fees_a = fees_q.values("client__client_type").annotate(fees=Sum("fees_amount"), gst=Sum("gst_amount"))
        rec_a = rec_q.values("client__client_type").annotate(receipts=Sum("amount_received"))
        exp_a = exp_q.values("client__client_type").annotate(expenses=Sum("expenses_paid"))
        rec_map = {r["client__client_type"] or "": r["receipts"] or 0 for r in rec_a}
        exp_map = {r["client__client_type"] or "": r["expenses"] or 0 for r in exp_a}

        rows = []
        totals = {"fees": 0, "gst": 0, "receipts": 0, "expenses": 0}
        for r in fees_a:
            k = r["client__client_type"] or ""
            row = {"client_type": k, "fees": r["fees"] or 0, "gst": r["gst"] or 0, "receipts": rec_map.get(k, 0), "expenses": exp_map.get(k, 0)}
            rows.append(row)
        existing = {r["client_type"] for r in rows}
        only_types = set(rec_map.keys()) | set(exp_map.keys())
        for k in sorted([x for x in only_types if x not in existing]):
            rows.append({"client_type": k, "fees": 0, "gst": 0, "receipts": rec_map.get(k, 0), "expenses": exp_map.get(k, 0)})
        rows.sort(key=lambda x: x["client_type"])
        for r in rows:
            totals["fees"] += r["fees"]
            totals["gst"] += r["gst"]
            totals["receipts"] += r["receipts"]
            totals["expenses"] += r["expenses"]

        rows, vis_detail, totals = _mis_sparse_metric_table(rows, detail_order)

        buf = StringIO()
        w = csv.writer(buf)
        header = ["CLIENT_TYPE"]
        hdr_map = {"FEES": "FEES_AMOUNT", "GST": "GST_AMOUNT", "RECEIPTS": "RECEIPTS_AMOUNT", "EXPENSES": "EXPENSES_AMOUNT"}
        header.extend(hdr_map[dk] for dk in vis_detail)
        w.writerow(header)
        for r in rows:
            row = [r["client_type"]] + [r[_MIS_DETAIL_FIELD[dk]] for dk in vis_detail]
            w.writerow(row)
        total_row = ["TOTAL"] + [totals[_MIS_DETAIL_FIELD[dk]] for dk in vis_detail]
        w.writerow(total_row)

        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="mis-type-wise-report.csv"'
        return resp

    if report_view == MISFlexibleReportForm.VIEW_CLIENT_WISE:
        detail_order = [k for k in MIS_DETAIL_ORDER if k in details]
        # export consolidated client-wise
        cid_f = (form.cleaned_data.get("client_id") or "").strip().upper()
        name_f = (form.cleaned_data.get("client_name") or "").strip().upper()
        pan_f = (form.cleaned_data.get("pan") or "").strip().upper()
        ct_f = (form.cleaned_data.get("client_type") or "").strip()
        br_f = (form.cleaned_data.get("branch") or "").strip()

        fees_q = FeesDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
        rec_q = Receipt.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
        exp_q = ExpenseDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
        if cid_f:
            fees_q = fees_q.filter(client__client_id__icontains=cid_f)
            rec_q = rec_q.filter(client__client_id__icontains=cid_f)
            exp_q = exp_q.filter(client__client_id__icontains=cid_f)
        if name_f:
            fees_q = fees_q.filter(client__client_name__icontains=name_f)
            rec_q = rec_q.filter(client__client_name__icontains=name_f)
            exp_q = exp_q.filter(client__client_name__icontains=name_f)
        if pan_f:
            fees_q = fees_q.filter(client__pan__icontains=pan_f)
            rec_q = rec_q.filter(client__pan__icontains=pan_f)
            exp_q = exp_q.filter(client__pan__icontains=pan_f)
        if ct_f:
            fees_q = fees_q.filter(client__client_type=ct_f)
            rec_q = rec_q.filter(client__client_type=ct_f)
            exp_q = exp_q.filter(client__client_type=ct_f)
        if br_f:
            fees_q = fees_q.filter(client__branch=br_f)
            rec_q = rec_q.filter(client__branch=br_f)
            exp_q = exp_q.filter(client__branch=br_f)

        fees_a = fees_q.values(
            "client__client_id",
            "client__client_name",
            "client__pan",
            "client__client_type",
            "client__branch",
        ).annotate(fees=Sum("fees_amount"), gst=Sum("gst_amount"))
        rec_a = rec_q.values("client__client_id").annotate(receipts=Sum("amount_received"))
        exp_a = exp_q.values("client__client_id").annotate(expenses=Sum("expenses_paid"))
        rec_map = {r["client__client_id"]: r["receipts"] or 0 for r in rec_a}
        exp_map = {r["client__client_id"]: r["expenses"] or 0 for r in exp_a}

        rows = []
        totals = {"fees": 0, "gst": 0, "receipts": 0, "expenses": 0}
        for r in fees_a:
            cid = r["client__client_id"]
            row = {
                "client_id": cid,
                "client_name": r["client__client_name"],
                "pan": r.get("client__pan") or "",
                "client_type": r.get("client__client_type") or "",
                "branch": r.get("client__branch") or "",
                "fees": r["fees"] or 0,
                "gst": r["gst"] or 0,
                "receipts": rec_map.get(cid, 0),
                "expenses": exp_map.get(cid, 0),
            }
            rows.append(row)
            totals["fees"] += row["fees"]
            totals["gst"] += row["gst"]
            totals["receipts"] += row["receipts"]
            totals["expenses"] += row["expenses"]

        rows, vis_detail, totals = _mis_sparse_metric_table(rows, detail_order)

        buf = StringIO()
        w = csv.writer(buf)
        header = ["CLIENT_ID", "CLIENT_NAME", "PAN_NO", "CLIENT_TYPE", "BRANCH"]
        hdr_map = {"FEES": "FEES_AMOUNT", "GST": "GST_AMOUNT", "RECEIPTS": "RECEIPTS_AMOUNT", "EXPENSES": "EXPENSES_AMOUNT"}
        header.extend(hdr_map[dk] for dk in vis_detail)
        w.writerow(header)
        for r in rows:
            row = [r["client_id"], r["client_name"], r["pan"], r["client_type"], r.get("branch") or ""]
            row.extend(r[_MIS_DETAIL_FIELD[dk]] for dk in vis_detail)
            w.writerow(row)
        total_row = ["TOTAL", "", "", "", ""] + [totals[_MIS_DETAIL_FIELD[dk]] for dk in vis_detail]
        w.writerow(total_row)
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="mis-client-wise-report.csv"'
        return resp

    detail_order = [k for k in MIS_DETAIL_ORDER if k in details]
    rows, totals = _mis_merge_period(
        f,
        t,
        client_id=form.cleaned_data.get("client_id") or "",
        client_name=form.cleaned_data.get("client_name") or "",
        pan=form.cleaned_data.get("pan") or "",
        client_type=form.cleaned_data.get("client_type") or "",
        branch=form.cleaned_data.get("branch") or "",
    )
    rows, vis_detail, totals = _mis_sparse_metric_table(rows, detail_order)

    buf = StringIO()
    w = csv.writer(buf)
    header = ["DATE", "CLIENT_ID", "CLIENT_NAME", "PAN_NO", "CLIENT_TYPE", "BRANCH"]
    hdr_map = {"FEES": "FEES_AMOUNT", "GST": "GST_AMOUNT", "RECEIPTS": "RECEIPTS_AMOUNT", "EXPENSES": "EXPENSES_AMOUNT"}
    header.extend(hdr_map[dk] for dk in vis_detail)
    w.writerow(header)

    for r in rows:
        row = [r["date"], r["client_id"], r["client_name"], r["pan"], r["client_type"], r.get("branch") or ""]
        row.extend(r[_MIS_DETAIL_FIELD[dk]] for dk in vis_detail)
        w.writerow(row)

    total_row = ["TOTAL", "", "", "", "", ""] + [totals[_MIS_DETAIL_FIELD[dk]] for dk in vis_detail]
    w.writerow(total_row)

    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="mis-report.csv"'
    return resp


@require_perm("reports.access_reports_menu")
def mis_client_wise_report(request):
    """
    Consolidated totals per client for a period.
    Select one/many clients or leave blank for all.
    """
    form = MISClientWiseFilterForm(request.GET or None)
    rows = []
    totals = {"fees": 0, "gst": 0, "receipts": 0, "expenses": 0}

    if request.GET and form.is_valid():
        f, t = _dt_range(form)
        clients = form.cleaned_data.get("clients")
        client_ids = list(clients.values_list("client_id", flat=True)) if clients is not None and len(clients) else []

        fees_q = FeesDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
        rec_q = Receipt.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
        exp_q = ExpenseDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
        if client_ids:
            fees_q = fees_q.filter(client__client_id__in=client_ids)
            rec_q = rec_q.filter(client__client_id__in=client_ids)
            exp_q = exp_q.filter(client__client_id__in=client_ids)

        fees_a = (
            fees_q.values("client__client_id", "client__client_name")
            .annotate(fees=Sum("fees_amount"), gst=Sum("gst_amount"))
            .order_by("client__client_name")
        )
        rec_a = rec_q.values("client__client_id").annotate(receipts=Sum("amount_received"))
        exp_a = exp_q.values("client__client_id").annotate(expenses=Sum("expenses_paid"))

        rec_map = {r["client__client_id"]: r["receipts"] or 0 for r in rec_a}
        exp_map = {r["client__client_id"]: r["expenses"] or 0 for r in exp_a}

        for r in fees_a:
            cid = r["client__client_id"]
            row = {
                "client_id": cid,
                "client_name": r["client__client_name"],
                "fees": r["fees"] or 0,
                "gst": r["gst"] or 0,
                "receipts": rec_map.get(cid, 0),
                "expenses": exp_map.get(cid, 0),
            }
            rows.append(row)
            totals["fees"] += row["fees"]
            totals["gst"] += row["gst"]
            totals["receipts"] += row["receipts"]
            totals["expenses"] += row["expenses"]

        # Include clients that only have receipts/expenses but no fees rows
        existing = {r["client_id"] for r in rows}
        only_ids = set(rec_map.keys()) | set(exp_map.keys())
        missing = sorted([cid for cid in only_ids if cid not in existing])
        if missing:
            name_map = {c.client_id: c.client_name for c in Client.approved_objects().filter(client_id__in=missing)}
            for cid in missing:
                row = {
                    "client_id": cid,
                    "client_name": name_map.get(cid, cid),
                    "fees": 0,
                    "gst": 0,
                    "receipts": rec_map.get(cid, 0),
                    "expenses": exp_map.get(cid, 0),
                }
                rows.append(row)
                totals["receipts"] += row["receipts"]
                totals["expenses"] += row["expenses"]

        rows.sort(key=lambda x: x["client_name"])

    return render(
        request,
        "reports/mis_client_wise_report.html",
        {"form": form, "rows": rows, "totals": totals},
    )


@require_perm("reports.export_mis_client_wise_report")
def mis_client_wise_report_csv(request):
    form = MISClientWiseFilterForm(request.GET or None)
    if not request.GET or not form.is_valid():
        return HttpResponse("Invalid filters.", status=400)

    f, t = _dt_range(form)
    clients = form.cleaned_data.get("clients")
    client_ids = list(clients.values_list("client_id", flat=True)) if clients is not None and len(clients) else []

    fees_q = FeesDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
    rec_q = Receipt.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
    exp_q = ExpenseDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
    if client_ids:
        fees_q = fees_q.filter(client__client_id__in=client_ids)
        rec_q = rec_q.filter(client__client_id__in=client_ids)
        exp_q = exp_q.filter(client__client_id__in=client_ids)

    fees_a = fees_q.values("client__client_id", "client__client_name").annotate(fees=Sum("fees_amount"), gst=Sum("gst_amount"))
    rec_a = rec_q.values("client__client_id").annotate(receipts=Sum("amount_received"))
    exp_a = exp_q.values("client__client_id").annotate(expenses=Sum("expenses_paid"))

    rec_map = {r["client__client_id"]: r["receipts"] or 0 for r in rec_a}
    exp_map = {r["client__client_id"]: r["expenses"] or 0 for r in exp_a}

    rows = []
    totals = {"fees": 0, "gst": 0, "receipts": 0, "expenses": 0}
    for r in fees_a:
        cid = r["client__client_id"]
        row = {
            "client_id": cid,
            "client_name": r["client__client_name"],
            "fees": r["fees"] or 0,
            "gst": r["gst"] or 0,
            "receipts": rec_map.get(cid, 0),
            "expenses": exp_map.get(cid, 0),
        }
        rows.append(row)
        totals["fees"] += row["fees"]
        totals["gst"] += row["gst"]
        totals["receipts"] += row["receipts"]
        totals["expenses"] += row["expenses"]

    existing = {r["client_id"] for r in rows}
    only_ids = set(rec_map.keys()) | set(exp_map.keys())
    missing = sorted([cid for cid in only_ids if cid not in existing])
    if missing:
        name_map = {c.client_id: c.client_name for c in Client.approved_objects().filter(client_id__in=missing)}
        for cid in missing:
            row = {
                "client_id": cid,
                "client_name": name_map.get(cid, cid),
                "fees": 0,
                "gst": 0,
                "receipts": rec_map.get(cid, 0),
                "expenses": exp_map.get(cid, 0),
            }
            rows.append(row)
            totals["receipts"] += row["receipts"]
            totals["expenses"] += row["expenses"]

    rows.sort(key=lambda x: x["client_name"])

    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["CLIENT_ID", "CLIENT_NAME", "FEES_AMOUNT", "GST_AMOUNT", "RECEIPTS_AMOUNT", "EXPENSES_AMOUNT"])
    for r in rows:
        w.writerow([r["client_id"], r["client_name"], r["fees"], r["gst"], r["receipts"], r["expenses"]])
    w.writerow(["TOTAL", "", totals["fees"], totals["gst"], totals["receipts"], totals["expenses"]])

    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="mis-client-wise-report.csv"'
    return resp


@require_perm("reports.access_reports_menu")
def mis_type_wise_report(request):
    """
    Consolidated totals by client type for a period.
    """
    form = MISTypeWiseFilterForm(request.GET or None)
    rows = []
    totals = {"fees": 0, "gst": 0, "receipts": 0, "expenses": 0}

    if request.GET and form.is_valid():
        f, t = _dt_range(form)
        tfilter = form.cleaned_data.get("client_type") or ""

        fees_q = FeesDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
        rec_q = Receipt.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
        exp_q = ExpenseDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
        if tfilter:
            fees_q = fees_q.filter(client__client_type=tfilter)
            rec_q = rec_q.filter(client__client_type=tfilter)
            exp_q = exp_q.filter(client__client_type=tfilter)

        fees_a = fees_q.values("client__client_type").annotate(fees=Sum("fees_amount"), gst=Sum("gst_amount"))
        rec_a = rec_q.values("client__client_type").annotate(receipts=Sum("amount_received"))
        exp_a = exp_q.values("client__client_type").annotate(expenses=Sum("expenses_paid"))

        rec_map = {r["client__client_type"]: r["receipts"] or 0 for r in rec_a}
        exp_map = {r["client__client_type"]: r["expenses"] or 0 for r in exp_a}

        for r in fees_a:
            ct = r["client__client_type"] or ""
            row = {
                "client_type": ct,
                "fees": r["fees"] or 0,
                "gst": r["gst"] or 0,
                "receipts": rec_map.get(ct, 0),
                "expenses": exp_map.get(ct, 0),
            }
            rows.append(row)
            totals["fees"] += row["fees"]
            totals["gst"] += row["gst"]
            totals["receipts"] += row["receipts"]
            totals["expenses"] += row["expenses"]

        # include types that only appear in receipts/expenses
        existing = {r["client_type"] for r in rows}
        only_types = set(rec_map.keys()) | set(exp_map.keys())
        missing = sorted([ct for ct in only_types if ct not in existing])
        for ct in missing:
            row = {
                "client_type": ct,
                "fees": 0,
                "gst": 0,
                "receipts": rec_map.get(ct, 0),
                "expenses": exp_map.get(ct, 0),
            }
            rows.append(row)
            totals["receipts"] += row["receipts"]
            totals["expenses"] += row["expenses"]

        rows.sort(key=lambda x: x["client_type"])

    return render(request, "reports/mis_type_wise_report.html", {"form": form, "rows": rows, "totals": totals})


@require_perm("reports.export_mis_type_wise_report")
def mis_type_wise_report_csv(request):
    form = MISTypeWiseFilterForm(request.GET or None)
    if not request.GET or not form.is_valid():
        return HttpResponse("Invalid filters.", status=400)

    f, t = _dt_range(form)
    tfilter = form.cleaned_data.get("client_type") or ""

    fees_q = FeesDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
    rec_q = Receipt.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
    exp_q = ExpenseDetail.objects.filter(client__approval_status=Client.APPROVED, date__gte=f, date__lte=t)
    if tfilter:
        fees_q = fees_q.filter(client__client_type=tfilter)
        rec_q = rec_q.filter(client__client_type=tfilter)
        exp_q = exp_q.filter(client__client_type=tfilter)

    fees_a = fees_q.values("client__client_type").annotate(fees=Sum("fees_amount"), gst=Sum("gst_amount"))
    rec_a = rec_q.values("client__client_type").annotate(receipts=Sum("amount_received"))
    exp_a = exp_q.values("client__client_type").annotate(expenses=Sum("expenses_paid"))

    rec_map = {r["client__client_type"] or "": r["receipts"] or 0 for r in rec_a}
    exp_map = {r["client__client_type"] or "": r["expenses"] or 0 for r in exp_a}

    rows = []
    totals = {"fees": 0, "gst": 0, "receipts": 0, "expenses": 0}
    for r in fees_a:
        ct = r["client__client_type"] or ""
        row = {
            "client_type": ct,
            "fees": r["fees"] or 0,
            "gst": r["gst"] or 0,
            "receipts": rec_map.get(ct, 0),
            "expenses": exp_map.get(ct, 0),
        }
        rows.append(row)
        totals["fees"] += row["fees"]
        totals["gst"] += row["gst"]
        totals["receipts"] += row["receipts"]
        totals["expenses"] += row["expenses"]

    existing = {r["client_type"] for r in rows}
    only_types = set(rec_map.keys()) | set(exp_map.keys())
    missing = sorted([ct for ct in only_types if ct not in existing])
    for ct in missing:
        row = {"client_type": ct, "fees": 0, "gst": 0, "receipts": rec_map.get(ct, 0), "expenses": exp_map.get(ct, 0)}
        rows.append(row)
        totals["receipts"] += row["receipts"]
        totals["expenses"] += row["expenses"]

    rows.sort(key=lambda x: x["client_type"])

    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["CLIENT_TYPE", "FEES_AMOUNT", "GST_AMOUNT", "RECEIPTS_AMOUNT", "EXPENSES_AMOUNT"])
    for r in rows:
        w.writerow([r["client_type"], r["fees"], r["gst"], r["receipts"], r["expenses"]])
    w.writerow(["TOTAL", totals["fees"], totals["gst"], totals["receipts"], totals["expenses"]])

    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="mis-type-wise-report.csv"'
    return resp


def _dm_active_appointment_q(as_of: date) -> Q:
    """Appointed on/before as_of and (no cessation or cessation strictly after as_of)."""
    return Q(Q(appointed_date__isnull=True) | Q(appointed_date__lte=as_of)) & Q(
        Q(cessation_date__isnull=True) | Q(cessation_date__gt=as_of)
    )


def _director_mapping_apply_director_text_filter(qs, form: DirectorMappingReportForm):
    if form.cleaned_data.get("director_scope") != DirectorMappingReportForm.SCOPE_FILTER:
        return qs
    din = (form.cleaned_data.get("director_din") or "").strip()
    if din:
        qs = qs.filter(director__din__icontains=din.upper())
    name = (form.cleaned_data.get("director_name") or "").strip()
    if name:
        qs = qs.filter(director__client_name__icontains=_normalize_upper(name))
    return qs


def _director_mapping_apply_company_text_filter(qs, form: DirectorMappingReportForm):
    if form.cleaned_data.get("company_scope") != DirectorMappingReportForm.SCOPE_FILTER:
        return qs
    cn = (form.cleaned_data.get("company_name") or "").strip()
    if cn:
        qs = qs.filter(company__client_name__icontains=_normalize_upper(cn))
    cin = (form.cleaned_data.get("company_cin") or "").strip()
    if cin:
        cu = _normalize_upper(cin)
        qs = qs.filter(Q(company__cin__icontains=cu) | Q(company__llpin__icontains=cu))
    return qs


def _director_mapping_report_qs(form: DirectorMappingReportForm):
    """One row per active appointment as on `as_of_date` (flat / detail layout)."""
    as_of = form.cleaned_data["as_of_date"]
    qs = DirectorMapping.objects.select_related("director", "company").filter(_dm_active_appointment_q(as_of))
    qs = _director_mapping_apply_director_text_filter(qs, form)
    qs = _director_mapping_apply_company_text_filter(qs, form)
    return qs.order_by("director__client_name", "company__client_name")


def director_mapping_report_layout(form: DirectorMappingReportForm) -> str:
    """How to present rows: flat detail, one row per director, or one row per company."""
    if not form.is_valid():
        return "flat"
    if form.cleaned_data.get("company_scope") == DirectorMappingReportForm.SCOPE_ALL:
        return "by_company"
    if form.cleaned_data.get("director_scope") == DirectorMappingReportForm.SCOPE_ALL:
        return "by_director"
    return "flat"


def _dm_seed_mappings_any_tenure(form: DirectorMappingReportForm):
    """Mappings used to decide which directors appear in the by-director report (company filters only)."""
    qs = DirectorMapping.objects.select_related("director", "company")
    return _director_mapping_apply_company_text_filter(qs, form)


def build_director_mapping_by_director_rows(form: DirectorMappingReportForm, *, limit: int | None):
    """
    Director-wise groups: each item has din, director_name, and lines[] (company_name,
    appointed_date, cessation_date) for rowspan layout. Full mapping history.
    """
    seed = _dm_seed_mappings_any_tenure(form)
    raw_ids = list(seed.values_list("director_id", flat=True).distinct())
    ordered_ids = list(
        Client.approved_objects().filter(pk__in=raw_ids)
        .order_by("din", "client_name")
        .values_list("pk", flat=True)
    )
    if not ordered_ids:
        return [], 0, False
    total_rows = DirectorMapping.objects.filter(director_id__in=ordered_ids).count()
    all_maps = (
        DirectorMapping.objects.filter(director_id__in=ordered_ids)
        .select_related("company", "director")
        .order_by("company__client_name", "company__client_id")
    )
    by_dir: dict[int, list] = defaultdict(list)
    for m in all_maps:
        by_dir[m.director_id].append(m)
    directors = Client.approved_objects().in_bulk(ordered_ids)
    groups: list[dict] = []
    row_budget = 500 if limit is not None else None
    displayed = 0

    for did in ordered_ids:
        d = directors[did]
        maps = sorted(
            by_dir.get(did, []),
            key=lambda m: (m.company.client_name.upper(), m.company.client_id),
        )
        if not maps:
            continue
        lines = [
            {
                "company_client_id": m.company.client_id,
                "company_name": m.company.client_name,
                "appointed_date": m.appointed_date,
                "cessation_date": m.cessation_date,
            }
            for m in maps
        ]
        if row_budget is not None:
            remaining = row_budget - displayed
            if remaining <= 0:
                return groups, total_rows, True
            if len(lines) > remaining:
                lines = lines[:remaining]
                groups.append(
                    {
                        "din": (d.din or "").strip(),
                        "director_name": d.client_name,
                        "lines": lines,
                    }
                )
                return groups, total_rows, True
        groups.append(
            {
                "din": (d.din or "").strip(),
                "director_name": d.client_name,
                "lines": lines,
            }
        )
        displayed += len(lines)

    truncated = bool(row_budget is not None and displayed < total_rows)
    return groups, total_rows, truncated


def build_director_mapping_by_company_rows(form: DirectorMappingReportForm, *, limit: int | None):
    """
    Company-wise groups: each item has company_client_id, company_name, and lines[]
    (director_name, din, appointed_date, cessation_date) for rowspan layout.
    Active appointments as on as_of_date only.
    """
    as_of = form.cleaned_data["as_of_date"]
    qs = (
        DirectorMapping.objects.select_related("director", "company")
        .filter(_dm_active_appointment_q(as_of))
        .order_by("company__client_name", "company__client_id")
    )
    qs = _director_mapping_apply_director_text_filter(qs, form)
    qs = _director_mapping_apply_company_text_filter(qs, form)
    by_company: dict[int, list] = defaultdict(list)
    for m in qs:
        by_company[m.company_id].append(m)
    ordered_cids = sorted(
        by_company.keys(),
        key=lambda cid: (
            by_company[cid][0].company.client_name.upper(),
            by_company[cid][0].company.client_id,
        ),
    )
    total_rows = qs.count()
    groups: list[dict] = []
    row_budget = 500 if limit is not None else None
    displayed = 0

    for cid in ordered_cids:
        maps = by_company[cid]
        co = maps[0].company
        lines = [
            {
                "director_name": m.director.client_name,
                "din": (m.director.din or "").strip(),
                "appointed_date": m.appointed_date,
                "cessation_date": m.cessation_date,
            }
            for m in sorted(
                maps,
                key=lambda x: (x.director.client_name.upper(), (x.director.din or "").strip()),
            )
        ]
        if row_budget is not None:
            remaining = row_budget - displayed
            if remaining <= 0:
                return groups, total_rows, True
            if len(lines) > remaining:
                lines = lines[:remaining]
                groups.append(
                    {
                        "company_client_id": co.client_id,
                        "company_name": co.client_name,
                        "lines": lines,
                    }
                )
                return groups, total_rows, True
        groups.append(
            {
                "company_client_id": co.client_id,
                "company_name": co.client_name,
                "lines": lines,
            }
        )
        displayed += len(lines)

    truncated = bool(row_budget is not None and displayed < total_rows)
    return groups, total_rows, truncated


def _dm_flat_focus_groups(qs) -> tuple[str | None, list[dict]]:
    """
    Single-company or single-director flat queryset → same grouped shape as
    company-wise / director-wise reports (for rowspan HTML).
    """
    if not qs.exists():
        return None, []
    qs = qs.select_related("director", "company")
    if qs.values("company_id").distinct().count() == 1:
        m0 = qs.first()
        lines = []
        for m in qs.order_by("director__client_name", "director__din"):
            lines.append(
                {
                    "director_name": m.director.client_name,
                    "din": (m.director.din or "").strip(),
                    "appointed_date": m.appointed_date,
                    "cessation_date": m.cessation_date,
                }
            )
        return "company_first", [
            {
                "company_client_id": m0.company.client_id,
                "company_name": m0.company.client_name,
                "lines": lines,
            }
        ]
    if qs.values("director_id").distinct().count() == 1:
        m0 = qs.first()
        lines = []
        for m in qs.order_by("company__client_name", "company__client_id"):
            lines.append(
                {
                    "company_client_id": m.company.client_id,
                    "company_name": m.company.client_name,
                    "appointed_date": m.appointed_date,
                    "cessation_date": m.cessation_date,
                }
            )
        return "director_first", [
            {
                "din": (m0.director.din or "").strip(),
                "director_name": m0.director.client_name,
                "lines": lines,
            }
        ]
    return None, []


def _dm_trim_groups_to_row_budget(groups: list[dict], row_budget: int) -> tuple[list[dict], bool]:
    """Trim group lines so total table rows ≤ row_budget; return (trimmed_groups, truncated)."""
    out: list[dict] = []
    used = 0
    total_in = sum(len(g["lines"]) for g in groups)
    for g in groups:
        lines = g["lines"]
        if used >= row_budget:
            break
        take = lines[: row_budget - used]
        used += len(take)
        if take:
            out.append({**g, "lines": take})
        if len(take) < len(lines):
            return out, True
    return out, total_in > sum(len(x["lines"]) for x in out)


DIRECTOR_MAPPING_CSV_COLUMNS = [
    "AS_ON_DATE",
    "DIRECTOR_CLIENT_ID",
    "DIRECTOR_NAME",
    "DIN",
    "COMPANY_CLIENT_ID",
    "COMPANY_NAME",
    "COMPANY_TYPE",
    "CIN",
    "LLPIN",
    "APPOINTED_DATE",
    "CESSATION_DATE",
    "CESSATION_REASON",
]

DIRECTOR_MAPPING_CSV_BY_DIRECTOR_COLUMNS = [
    "AS_ON_DATE",
    "DIN",
    "DIRECTOR_NAME",
    "COMPANY_CLIENT_ID",
    "COMPANY_NAME",
    "APPOINTED_DATE",
    "CESSATION_DATE",
]

DIRECTOR_MAPPING_CSV_BY_COMPANY_COLUMNS = [
    "AS_ON_DATE",
    "COMPANY_CLIENT_ID",
    "COMPANY_NAME",
    "DIRECTOR_NAME",
    "DIN",
    "APPOINTED_DATE",
    "CESSATION_DATE",
]


@require_perm("reports.view_director_mapping_report")
def director_mapping_report(request):
    form = DirectorMappingReportForm(request.GET or None)
    rows = []
    count = 0
    truncated = False
    layout = "flat"
    as_of = None
    dm_display_rows = 0

    if request.GET:
        if form.is_valid():
            as_of = form.cleaned_data["as_of_date"]
            layout = director_mapping_report_layout(form)
            if layout == "by_company":
                rows, count, truncated = build_director_mapping_by_company_rows(form, limit=500)
            elif layout == "by_director":
                rows, count, truncated = build_director_mapping_by_director_rows(form, limit=500)
            else:
                qs = _director_mapping_report_qs(form)
                total_qs = qs.count()
                focus, flat_groups = _dm_flat_focus_groups(qs)
                if focus:
                    layout = f"flat_{focus}"
                    rows, trim_trunc = _dm_trim_groups_to_row_budget(flat_groups, 500)
                    shown = sum(len(g["lines"]) for g in rows)
                    count = total_qs
                    truncated = trim_trunc or shown < total_qs
                else:
                    rows = list(qs[:500])
                    count = total_qs
                    truncated = total_qs > 500
            if layout in ("by_company", "by_director", "flat_company_first", "flat_director_first"):
                dm_display_rows = sum(len(g.get("lines", [])) for g in rows)
            else:
                dm_display_rows = len(rows)
    else:
        form = DirectorMappingReportForm()

    return render(
        request,
        "reports/director_mapping_report.html",
        {
            "form": form,
            "rows": rows,
            "count": count,
            "truncated": truncated,
            "layout": layout,
            "as_of": as_of,
            "dm_display_rows": dm_display_rows,
        },
    )


def _dm_mapping_date_csv(d) -> str:
    return d.isoformat() if d else ""


@require_perm("reports.export_director_mapping_report")
def director_mapping_report_csv(request):
    if not request.GET:
        return HttpResponse("Apply filters in the report page, then download CSV.", status=400)
    form = DirectorMappingReportForm(request.GET)
    if not form.is_valid():
        return HttpResponse("Invalid filters.", status=400)
    as_of = form.cleaned_data["as_of_date"]
    layout = director_mapping_report_layout(form)

    buf = StringIO()
    w = csv.writer(buf)

    if layout == "by_company":
        w.writerow(DIRECTOR_MAPPING_CSV_BY_COMPANY_COLUMNS)
        groups, _, _ = build_director_mapping_by_company_rows(form, limit=None)
        for g in groups:
            for line in g["lines"]:
                w.writerow(
                    [
                        as_of.isoformat(),
                        g["company_client_id"],
                        g["company_name"],
                        line["director_name"],
                        line["din"],
                        _dm_mapping_date_csv(line["appointed_date"]),
                        _dm_mapping_date_csv(line["cessation_date"]),
                    ]
                )
    elif layout == "by_director":
        w.writerow(DIRECTOR_MAPPING_CSV_BY_DIRECTOR_COLUMNS)
        groups, _, _ = build_director_mapping_by_director_rows(form, limit=None)
        for g in groups:
            for line in g["lines"]:
                w.writerow(
                    [
                        as_of.isoformat(),
                        g["din"],
                        g["director_name"],
                        line["company_client_id"],
                        line["company_name"],
                        _dm_mapping_date_csv(line["appointed_date"]),
                        _dm_mapping_date_csv(line["cessation_date"]),
                    ]
                )
    else:
        qs = _director_mapping_report_qs(form)
        focus, flat_groups = _dm_flat_focus_groups(qs)
        if focus == "company_first":
            w.writerow(DIRECTOR_MAPPING_CSV_BY_COMPANY_COLUMNS)
            for g in flat_groups:
                for line in g["lines"]:
                    w.writerow(
                        [
                            as_of.isoformat(),
                            g["company_client_id"],
                            g["company_name"],
                            line["director_name"],
                            line["din"],
                            _dm_mapping_date_csv(line["appointed_date"]),
                            _dm_mapping_date_csv(line["cessation_date"]),
                        ]
                    )
        elif focus == "director_first":
            w.writerow(DIRECTOR_MAPPING_CSV_BY_DIRECTOR_COLUMNS)
            for g in flat_groups:
                for line in g["lines"]:
                    w.writerow(
                        [
                            as_of.isoformat(),
                            g["din"],
                            g["director_name"],
                            line["company_client_id"],
                            line["company_name"],
                            _dm_mapping_date_csv(line["appointed_date"]),
                            _dm_mapping_date_csv(line["cessation_date"]),
                        ]
                    )
        else:
            w.writerow(DIRECTOR_MAPPING_CSV_COLUMNS)
            for m in qs.iterator(chunk_size=500):
                w.writerow(
                    [
                        as_of.isoformat(),
                        m.director.client_id,
                        m.director.client_name,
                        m.director.din,
                        m.company.client_id,
                        m.company.client_name,
                        m.company.client_type,
                        m.company.cin,
                        m.company.llpin,
                        m.appointed_date.isoformat() if m.appointed_date else "",
                        m.cessation_date.isoformat() if m.cessation_date else "",
                        m.get_reason_for_cessation_display() if m.reason_for_cessation else "",
                    ]
                )
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="director-mapping-report.csv"'
    return resp


def _dir3kyc_report_qs(form: Dir3KycReportForm):
    qs = Dir3Kyc.objects.select_related("director").all()
    if form.cleaned_data.get("director_scope") == DirectorMappingReportForm.SCOPE_FILTER:
        din = (form.cleaned_data.get("director_din") or "").strip()
        if din:
            qs = qs.filter(director__din__icontains=din.upper())
        name = (form.cleaned_data.get("director_name") or "").strip()
        if name:
            qs = qs.filter(director__client_name__icontains=_normalize_upper(name))
    df = form.cleaned_data.get("date_done_from")
    dt = form.cleaned_data.get("date_done_to")
    if df:
        qs = qs.filter(date_done__gte=df)
    if dt:
        qs = qs.filter(date_done__lte=dt)
    return qs.order_by("-date_done", "-id")


DIR3KYC_CSV_COLUMNS = [
    "DATE_DONE",
    "DIRECTOR_CLIENT_ID",
    "DIRECTOR_NAME",
    "DIN",
    "SRN",
    "FY_WHEN_DONE",
    "NEXT_ALLOWED_FY",
    "NEXT_ALLOWED_FROM",
]

DIR3_COMPLIANCE_CSV_COLUMNS = [
    "AS_ON_DATE",
    "DIRECTOR_CLIENT_ID",
    "DIRECTOR_NAME",
    "DIN",
    "DATE_LAST_KYC",
    "FY_LAST_KYC",
    "NEXT_ALLOWED_FROM",
    "NEXT_ALLOWED_FY",
    "FY_GAP_AS_ON",
    "FLAG_GE_3FY_SINCE_LAST_FILING_FY",
]


@require_perm("reports.view_dir3kyc_report")
def dir3kyc_report(request):
    form = Dir3KycReportForm(request.GET or None)
    rows = []
    compliance_rows = []
    count = 0
    truncated = False
    mode = Dir3KycReportForm.VIEW_FILINGS

    if request.GET:
        if form.is_valid():
            mode = form.cleaned_data.get("view_mode") or Dir3KycReportForm.VIEW_FILINGS
            if form.is_compliance_view():
                as_of = form.cleaned_data.get("as_of_date") or date.today()
                compliance_rows = build_director_dir3_compliance_rows(form.cleaned_data, as_of=as_of, limit=500)
                count = len(compliance_rows)
                truncated = count >= 500
            else:
                qs = _dir3kyc_report_qs(form)
                count = qs.count()
                rows = list(qs[:500])
                truncated = count > 500
    else:
        form = Dir3KycReportForm()

    return render(
        request,
        "reports/dir3kyc_report.html",
        {
            "form": form,
            "rows": rows,
            "compliance_rows": compliance_rows,
            "count": count,
            "truncated": truncated,
            "mode": mode,
        },
    )


@require_perm("reports.export_dir3kyc_report")
def dir3kyc_report_csv(request):
    if not request.GET:
        return HttpResponse("Apply filters in the report page, then download CSV.", status=400)
    form = Dir3KycReportForm(request.GET)
    if not form.is_valid():
        return HttpResponse("Invalid filters.", status=400)

    buf = StringIO()
    w = csv.writer(buf)

    if form.is_compliance_view():
        as_of = form.cleaned_data.get("as_of_date") or date.today()
        crow = build_director_dir3_compliance_rows(form.cleaned_data, as_of=as_of, limit=50_000)
        w.writerow(DIR3_COMPLIANCE_CSV_COLUMNS)
        for r in crow:
            w.writerow(
                [
                    as_of.isoformat(),
                    r.client_id,
                    r.director_name,
                    r.din,
                    r.last_kyc_date.isoformat() if r.last_kyc_date else "",
                    r.last_kyc_fy_label,
                    r.next_allowed_from.isoformat() if r.next_allowed_from else "",
                    r.next_allowed_fy_label,
                    r.fy_since_last,
                    "YES" if r.not_done_3fy else "NO",
                ]
            )
    else:
        qs = _dir3kyc_report_qs(form)
        w.writerow(DIR3KYC_CSV_COLUMNS)
        for r in qs.iterator(chunk_size=500):
            w.writerow(
                [
                    r.date_done.isoformat() if r.date_done else "",
                    r.director.client_id,
                    r.director.client_name,
                    r.director.din,
                    r.srn,
                    r.fy_when_done_label,
                    r.next_allowed_fy_label,
                    r.next_allowed_from_date.isoformat(),
                ]
            )

    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="dir3-kyc-report.csv"'
    return resp
