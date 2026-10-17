"""Trial Balance Excel and PDF export."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .services import TB_FORMAT_CHOICES, TB_REPORT_CHOICES, money


def tb_column_headers(data: dict) -> list[str]:
    headers = ["Particulars"]
    if data.get("show_group_column"):
        headers.append("Group")
    if data.get("show_opening"):
        headers.extend(["Opening Debit", "Opening Credit"])
    if data.get("show_transactions"):
        headers.extend(["Debit", "Credit"])
    if data.get("show_opening"):
        headers.extend(["Closing Debit", "Closing Credit"])
    else:
        headers.extend(["Debit", "Credit"])
    return headers


def _amount_or_blank(value) -> Decimal | None:
    amount = money(value)
    return amount if amount else None


def tb_row_cells(row: dict, data: dict) -> list:
    indent = int(row.get("indent") or 0)
    name = f'{"  " * indent}{row.get("name") or ""}'
    cells = [name]
    if data.get("show_group_column"):
        group = row.get("group")
        cells.append(getattr(group, "name", "") or "")
    if data.get("show_opening"):
        cells.append(_amount_or_blank(row.get("opening_debit")))
        cells.append(_amount_or_blank(row.get("opening_credit")))
    if data.get("show_transactions"):
        cells.append(_amount_or_blank(row.get("period_debit")))
        cells.append(_amount_or_blank(row.get("period_credit")))
    cells.append(_amount_or_blank(row.get("closing_debit")))
    cells.append(_amount_or_blank(row.get("closing_credit")))
    return cells


def tb_export_title(data: dict) -> str:
    report = dict(TB_REPORT_CHOICES).get(data.get("report"), "Trial Balance")
    fmt = dict(TB_FORMAT_CHOICES).get(data.get("fmt"), "Trial Balance")
    return f"{fmt} — {report}"


def tb_filename(data: dict, date_from, date_to, ext: str) -> str:
    start = date_from.isoformat() if date_from else "start"
    end = date_to.isoformat() if date_to else "end"
    kind = "group" if data.get("report") == "group" else "ledger"
    fmt = data.get("fmt") or "tb"
    return f"trial-balance-{kind}-{fmt}-{start}-to-{end}.{ext}"


def trial_balance_xlsx_bytes(
    data: dict,
    *,
    date_from=None,
    date_to=None,
    company_name: str = "",
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Trial Balance"
    headers = tb_column_headers(data)
    title_font = Font(bold=True, size=14)
    subtitle_font = Font(bold=True, size=11)
    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="D1D5DB")
    parent_fill = PatternFill("solid", fgColor="E9ECEF")
    group_fill = PatternFill("solid", fgColor="F3F4F6")
    thin = Border(
        left=Side(style="thin", color="C5C9D0"),
        right=Side(style="thin", color="C5C9D0"),
        top=Side(style="thin", color="C5C9D0"),
        bottom=Side(style="thin", color="C5C9D0"),
    )
    right = Alignment(horizontal="right")
    wrap = Alignment(wrap_text=True, vertical="center")

    row_no = 1
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    ws.cell(row_no, 1, company_name or "Trial Balance").font = title_font
    row_no += 1
    ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=len(headers))
    ws.cell(row_no, 1, tb_export_title(data)).font = subtitle_font
    row_no += 1
    period = " to ".join(part for part in (_fmt_date(date_from), _fmt_date(date_to)) if part)
    ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=len(headers))
    ws.cell(row_no, 1, period)
    row_no += 2

    header_row = row_no
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(header_row, col, header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin
        if col > 1:
            cell.alignment = right
    row_no += 1

    amount_cols = list(range(2 if not data.get("show_group_column") else 3, len(headers) + 1))

    def write_data_row(values, *, bold=False, fill=None):
        nonlocal row_no
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row_no, col, value if value is not None else None)
            cell.border = thin
            cell.alignment = wrap if col == 1 else right
            if bold:
                cell.font = header_font
            if fill:
                cell.fill = fill
            if col in amount_cols and isinstance(value, Decimal):
                cell.number_format = "#,##0.00"
        row_no += 1

    for item in data.get("rows") or []:
        fill = None
        if item.get("kind") == "parent":
            fill = parent_fill
        elif item.get("kind") == "account_group":
            fill = group_fill
        write_data_row(tb_row_cells(item, data), bold=bool(item.get("is_header")), fill=fill)

    if data.get("rows"):
        total_row = {"name": "Total", "indent": 0, **(data.get("totals") or {})}
        write_data_row(tb_row_cells(total_row, data), bold=True, fill=header_fill)

    ws.column_dimensions["A"].width = 42
    start = 2
    if data.get("show_group_column"):
        ws.column_dimensions["B"].width = 28
        start = 3
    for col in range(start, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def trial_balance_pdf_bytes(
    data: dict,
    *,
    date_from=None,
    date_to=None,
    company_name: str = "",
) -> bytes:
    headers = tb_column_headers(data)
    rows = [tb_row_cells(item, data) for item in data.get("rows") or []]
    if data.get("rows"):
        total_row = {"name": "Total", "indent": 0, **(data.get("totals") or {})}
        rows.append(tb_row_cells(total_row, data))
        bold_last = True
    else:
        bold_last = False
    header_kinds = [item.get("kind") for item in data.get("rows") or []]
    if bold_last:
        header_kinds.append("total")

    page_w, page_h = 842.0, 595.0
    margin = 36.0
    title = company_name or "Trial Balance"
    subtitle = tb_export_title(data)
    period = " to ".join(part for part in (_fmt_date(date_from), _fmt_date(date_to)) if part)
    inner_w = page_w - 2 * margin
    name_w = 220.0 if data.get("show_group_column") else 260.0
    group_w = 110.0 if data.get("show_group_column") else 0.0
    amount_count = len(headers) - (2 if data.get("show_group_column") else 1)
    amount_w = (inner_w - name_w - group_w) / max(amount_count, 1)
    col_widths = [name_w]
    if data.get("show_group_column"):
        col_widths.append(group_w)
    col_widths.extend([amount_w] * amount_count)

    row_h = 14.0
    top_y = page_h - margin
    pages: list[list[str]] = []
    ops: list[str] = []
    y = top_y

    def new_page():
        nonlocal ops, y
        if ops:
            pages.append(ops)
        ops = []
        y = top_y
        ops.append(_pdf_text(margin, y - 2, title, size=13, bold=True))
        y -= 16
        ops.append(_pdf_text(margin, y, subtitle, size=10, bold=True))
        y -= 13
        if period:
            ops.append(_pdf_text(margin, y, period, size=9))
            y -= 14
        y = _draw_table_row(ops, margin, y, headers, col_widths, row_h, bold=True, fill=True)
        y -= 2

    new_page()
    for index, values in enumerate(rows):
        if y - row_h < margin + 20:
            new_page()
        kind = header_kinds[index] if index < len(header_kinds) else ""
        fill = kind in ("parent", "account_group", "total")
        bold = kind in ("parent", "account_group", "total")
        display = [_pdf_cell_text(value) for value in values]
        y = _draw_table_row(ops, margin, y, display, col_widths, row_h, bold=bold, fill=fill, amounts_from=1)
    pages.append(ops)
    return _build_pdf(pages, page_w, page_h)


def tb_excel_response(data, *, date_from=None, date_to=None, company_name: str = "") -> HttpResponse:
    payload = trial_balance_xlsx_bytes(
        data, date_from=date_from, date_to=date_to, company_name=company_name
    )
    filename = tb_filename(data, date_from, date_to, "xlsx")
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def tb_pdf_response(data, *, date_from=None, date_to=None, company_name: str = "") -> HttpResponse:
    payload = trial_balance_pdf_bytes(
        data, date_from=date_from, date_to=date_to, company_name=company_name
    )
    filename = tb_filename(data, date_from, date_to, "pdf")
    response = HttpResponse(payload, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _fmt_date(value) -> str:
    if isinstance(value, date):
        return value.strftime("%d-%m-%Y")
    return ""


def _pdf_cell_text(value) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    return str(value)


def _pdf_escape(text: str) -> str:
    raw = (text or "").encode("latin-1", "replace").decode("latin-1")
    return raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_text(x: float, y: float, text: str, *, size=8, bold=False) -> str:
    font = "F2" if bold else "F1"
    return f"BT /{font} {size:.1f} Tf {x:.2f} {y:.2f} Td ({_pdf_escape(text)}) Tj ET"


def _draw_table_row(ops, left, y, values, widths, height, *, bold=False, fill=False, amounts_from=1):
    x = left
    if fill:
        total_w = sum(widths)
        ops.append(f"0.91 0.92 0.93 rg {x:.2f} {y - height + 3:.2f} {total_w:.2f} {height:.2f} re f 0 0 0 rg")
    ops.append("0.75 0.76 0.78 RG")
    ops.append(
        f"{left:.2f} {y + 3:.2f} m {left + sum(widths):.2f} {y + 3:.2f} l "
        f"{left:.2f} {y - height + 3:.2f} m {left + sum(widths):.2f} {y - height + 3:.2f} l S"
    )
    text_y = y - 7
    for index, (value, width) in enumerate(zip(values, widths)):
        text = str(value or "")
        max_chars = max(int(width / 4.6), 8)
        if len(text) > max_chars:
            text = text[: max_chars - 1] + "..."
        if index >= amounts_from:
            approx = min(len(text) * 4.2, width - 4)
            ops.append(_pdf_text(x + width - 4 - approx, text_y, text, size=8, bold=bold))
        else:
            ops.append(_pdf_text(x + 3, text_y, text, size=8, bold=bold))
        x += width
    return y - height


def _build_pdf(pages: list[list[str]], width: float, height: float) -> bytes:
    objects = ["", "<< /Type /Catalog /Pages 2 0 R >>"]
    objects.append("")  # placeholder for pages tree
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    page_obj_nums = []
    for ops in pages:
        stream = "\n".join(ops).encode("latin-1", "replace")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"endstream")
        content_no = len(objects) - 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.0f} {height:.0f}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {content_no} 0 R >>"
        )
        page_obj_nums.append(len(objects) - 1)
    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>"
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects[1:], start=1):
        offsets.append(len(out))
        if isinstance(obj, bytes):
            out.extend(f"{i} 0 obj\n".encode("ascii"))
            out.extend(obj)
            out.extend(b"\nendobj\n")
        else:
            out.extend(f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1"))
    xref_at = len(out)
    out.extend(f"xref\n0 {len(objects)}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer << /Size {len(objects)} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


PNL_HEADERS = ["Particulars", "Amount", "Amount", "Particulars", "Amount", "Amount"]
BS_HEADERS = ["Liabilities", "Amount", "Amount", "Assets", "Amount", "Amount"]
AMOUNT_FORMAT = "#,##0.00"
BS_AMOUNT_FORMAT = "#,##0.00;(#,##0.00)"


def _pnl_side_cells(side: dict) -> list:
    side = side or {}
    return [
        side.get("name") or "",
        _amount_or_blank(side.get("inner")),
        _amount_or_blank(side.get("outer")),
    ]


def _pnl_export_lines(data: dict) -> list[tuple[list, str]]:
    lines = []
    for item in data.get("trading_rows") or []:
        kind = "trading-total" if item.get("left", {}).get("kind") == "total" else item.get("left", {}).get("kind") or ""
        lines.append((_pnl_side_cells(item.get("left")) + _pnl_side_cells(item.get("right")), kind))
    lines.append((["", None, None, "", None, None], "spacer"))
    for item in data.get("pnl_rows") or []:
        kind = "final-total" if item.get("left", {}).get("kind") == "total" else item.get("left", {}).get("kind") or ""
        lines.append((_pnl_side_cells(item.get("left")) + _pnl_side_cells(item.get("right")), kind))
    return lines


def _bs_side_cells(side: dict) -> list:
    side = side or {}
    indent = int(side.get("indent") or 0)
    name = f'{"  " * indent}{side.get("name") or ""}'
    return [
        name,
        _amount_or_blank(side.get("inner")),
        _amount_or_blank(side.get("outer")),
    ]


def _bs_export_lines(data: dict) -> list[tuple[list, str]]:
    lines = []
    for item in data.get("statement_rows") or []:
        kind = item.get("left", {}).get("kind") or ""
        if kind == "total":
            kind = "final-total"
        lines.append((_bs_side_cells(item.get("left")) + _bs_side_cells(item.get("right")), kind))
    return lines


def _bs_title(date_to) -> str:
    as_on = _fmt_date(date_to) or "date"
    return f"Balance Sheet as on {as_on}"


def _bs_filename(date_to, ext: str) -> str:
    as_on = date_to.isoformat() if date_to else "date"
    return f"balance-sheet-{as_on}.{ext}"


def _pnl_title(date_from, date_to) -> str:
    start = _fmt_date(date_from) or "start"
    end = _fmt_date(date_to) or "end"
    return f"Profit and Loss Account from {start} to {end}"


def _pnl_filename(date_from, date_to, ext: str) -> str:
    start = date_from.isoformat() if date_from else "start"
    end = date_to.isoformat() if date_to else "end"
    return f"profit-and-loss-{start}-to-{end}.{ext}"


def _statement_xlsx_bytes(
    lines: list[tuple[list, str]],
    *,
    headers: list[str],
    sheet_title: str,
    report_title: str,
    company_name: str = "",
    company_address: str = "",
    amount_format: str = AMOUNT_FORMAT,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title[:31]
    title_font = Font(bold=True, size=14)
    subtitle_font = Font(bold=True, size=11)
    header_font = Font(bold=True)
    thin = Side(style="thin", color="000000")
    header_border = Border(top=thin, bottom=thin)
    split_header_border = Border(top=thin, bottom=thin, left=thin)
    split_border = Border(left=thin)
    outer_total_border = Border(top=thin, bottom=thin)
    final_border = Border(top=thin, bottom=thin)
    final_split_border = Border(top=thin, bottom=thin, left=thin)
    center = Alignment(horizontal="center", wrap_text=True)
    right = Alignment(horizontal="right")
    wrap = Alignment(wrap_text=True, vertical="center")

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)
    cell = ws.cell(1, 1, company_name or sheet_title)
    cell.font = title_font
    cell.alignment = center
    row_no = 2
    if company_address:
        ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=6)
        cell = ws.cell(row_no, 1, company_address)
        cell.alignment = center
        row_no += 1
    ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=6)
    cell = ws.cell(row_no, 1, report_title)
    cell.font = subtitle_font
    cell.alignment = center
    row_no += 2

    header_row = row_no
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(header_row, col, header)
        cell.font = header_font
        cell.alignment = center
        cell.border = split_header_border if col == 4 else header_border
    row_no += 1

    name_cols = {1, 4}
    amount_cols = {2, 3, 5, 6}
    outer_cols = {3, 6}

    for values, kind in lines:
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row_no, col, value if value not in (None, "") else None)
            if col in amount_cols:
                cell.alignment = right
                if isinstance(value, Decimal):
                    cell.number_format = amount_format
            else:
                cell.alignment = wrap
            bold = kind in ("header", "subheader", "balancing", "total", "trading-total", "final-total")
            if bold and col in name_cols:
                cell.font = header_font
            elif bold and kind in ("trading-total", "final-total"):
                cell.font = header_font
            if col == 4:
                if kind == "final-total":
                    cell.border = final_split_border
                else:
                    cell.border = split_border
            elif kind == "final-total":
                cell.border = final_border
            elif kind == "trading-total" and col in outer_cols:
                cell.border = outer_total_border
        row_no += 1

    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 32
    ws.column_dimensions["E"].width = 14
    ws.column_dimensions["F"].width = 14
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def profit_and_loss_xlsx_bytes(
    data: dict,
    *,
    date_from=None,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
) -> bytes:
    return _statement_xlsx_bytes(
        _pnl_export_lines(data),
        headers=PNL_HEADERS,
        sheet_title="Profit and Loss",
        report_title=_pnl_title(date_from, date_to),
        company_name=company_name,
        company_address=company_address,
    )


def _pdf_amount_text(value, *, parentheses=False) -> str:
    if isinstance(value, Decimal):
        if parentheses and value < 0:
            return f"({abs(value):,.2f})"
        return f"{value:,.2f}"
    return str(value or "")


def _statement_pdf_bytes(
    lines: list[tuple[list, str]],
    *,
    headers: list[str],
    report_title: str,
    company_name: str = "",
    company_address: str = "",
    parentheses=False,
) -> bytes:
    page_w, page_h = 842.0, 595.0
    margin = 36.0
    inner_w = page_w - 2 * margin
    name_w = 160.0
    amt_w = (inner_w - name_w * 2) / 4
    widths = [name_w, amt_w, amt_w, name_w, amt_w, amt_w]
    split_x = margin + name_w + amt_w + amt_w
    row_h = 14.0
    pages: list[list[str]] = []
    ops: list[str] = []
    y = page_h - margin

    def hline(x1, x2, at):
        ops.append("0 0 0 RG")
        ops.append(f"{x1:.2f} {at:.2f} m {x2:.2f} {at:.2f} l S")

    def vline(top, bottom):
        ops.append("0 0 0 RG")
        ops.append(f"{split_x:.2f} {top:.2f} m {split_x:.2f} {bottom:.2f} l S")

    def draw_text_row(values, *, bold=False):
        nonlocal y
        x = margin
        text_y = y - 10
        for index, (value, width) in enumerate(zip(values, widths)):
            text = _pdf_amount_text(value, parentheses=parentheses) if index in (1, 2, 4, 5) else str(value or "")
            max_chars = max(int(width / 4.6), 8)
            if len(text) > max_chars:
                text = text[: max_chars - 1] + "..."
            if index in (1, 2, 4, 5):
                approx = min(len(text) * 4.2, width - 4)
                ops.append(_pdf_text(x + width - 4 - approx, text_y, text, size=8, bold=bold))
            else:
                ops.append(_pdf_text(x + 3, text_y, text, size=8, bold=bold))
            x += width
        y -= row_h

    def new_page():
        nonlocal ops, y
        if ops:
            pages.append(ops)
        ops = []
        y = page_h - margin
        if company_name:
            ops.append(_pdf_text(margin, y - 2, company_name, size=13, bold=True))
            y -= 16
        if company_address:
            ops.append(_pdf_text(margin, y, company_address, size=9))
            y -= 13
        ops.append(_pdf_text(margin, y, report_title, size=10, bold=True))
        y -= 16
        top = y + 4
        hline(margin, margin + inner_w, top)
        draw_text_row(headers, bold=True)
        hline(margin, margin + inner_w, y + 3)
        vline(top, y + 3)

    new_page()
    section_top = y + 3
    for values, kind in lines:
        if y - row_h < margin + 24:
            vline(section_top, y + 3)
            new_page()
            section_top = y + 3
        before = y + 3
        bold = kind in ("header", "subheader", "balancing", "trading-total", "final-total")
        if kind == "spacer":
            y -= 10
            vline(section_top, y + 3)
            section_top = y + 3
            continue
        if kind == "trading-total":
            hline(margin + name_w + amt_w, margin + name_w + amt_w * 2, before)
            hline(margin + inner_w - amt_w, margin + inner_w, before)
        elif kind == "final-total":
            hline(margin, margin + inner_w, before)
        draw_text_row(values, bold=bold)
        after = y + 3
        if kind == "trading-total":
            hline(margin + name_w + amt_w, margin + name_w + amt_w * 2, after)
            hline(margin + inner_w - amt_w, margin + inner_w, after)
        elif kind == "final-total":
            hline(margin, margin + inner_w, after)
        vline(before, after)
    vline(section_top, y + 3)
    pages.append(ops)
    return _build_pdf(pages, page_w, page_h)


def profit_and_loss_pdf_bytes(
    data: dict,
    *,
    date_from=None,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
) -> bytes:
    return _statement_pdf_bytes(
        _pnl_export_lines(data),
        headers=PNL_HEADERS,
        report_title=_pnl_title(date_from, date_to),
        company_name=company_name,
        company_address=company_address,
    )


def pnl_excel_response(
    data,
    *,
    date_from=None,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
) -> HttpResponse:
    payload = profit_and_loss_xlsx_bytes(
        data,
        date_from=date_from,
        date_to=date_to,
        company_name=company_name,
        company_address=company_address,
    )
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{_pnl_filename(date_from, date_to, "xlsx")}"'
    return response


def pnl_pdf_response(
    data,
    *,
    date_from=None,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
) -> HttpResponse:
    payload = profit_and_loss_pdf_bytes(
        data,
        date_from=date_from,
        date_to=date_to,
        company_name=company_name,
        company_address=company_address,
    )
    response = HttpResponse(payload, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{_pnl_filename(date_from, date_to, "pdf")}"'
    return response


def balance_sheet_xlsx_bytes(
    data: dict,
    *,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
) -> bytes:
    return _statement_xlsx_bytes(
        _bs_export_lines(data),
        headers=BS_HEADERS,
        sheet_title="Balance Sheet",
        report_title=_bs_title(date_to),
        company_name=company_name,
        company_address=company_address,
        amount_format=BS_AMOUNT_FORMAT,
    )


def balance_sheet_pdf_bytes(
    data: dict,
    *,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
) -> bytes:
    return _statement_pdf_bytes(
        _bs_export_lines(data),
        headers=BS_HEADERS,
        report_title=_bs_title(date_to),
        company_name=company_name,
        company_address=company_address,
        parentheses=True,
    )


def bs_excel_response(
    data,
    *,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
) -> HttpResponse:
    payload = balance_sheet_xlsx_bytes(
        data,
        date_to=date_to,
        company_name=company_name,
        company_address=company_address,
    )
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{_bs_filename(date_to, "xlsx")}"'
    return response


def bs_pdf_response(
    data,
    *,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
) -> HttpResponse:
    payload = balance_sheet_pdf_bytes(
        data,
        date_to=date_to,
        company_name=company_name,
        company_address=company_address,
    )
    response = HttpResponse(payload, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{_bs_filename(date_to, "pdf")}"'
    return response


LEDGER_HEADERS = ["Date", "Voucher No", "Ledger account", "Narration", "Debit", "Credit"]


def _ledger_filename(account, date_from, date_to, ext: str, *, all_ledgers=False) -> str:
    if all_ledgers or not account:
        slug = "all"
    else:
        raw = "".join(ch.lower() if ch.isalnum() else "-" for ch in (getattr(account, "name", "") or "ledger"))
        slug = "-".join(part for part in raw.split("-") if part)[:40] or "ledger"
    start = date_from.isoformat() if date_from else "start"
    end = date_to.isoformat() if date_to else "end"
    return f"ledger-{slug}-{start}-to-{end}.{ext}"


def _ledger_row_cells(row: dict) -> list:
    return [
        _fmt_date(row.get("date")),
        row.get("number") or "",
        row.get("ledger_account") or "",
        row.get("narration") or "",
        _amount_or_blank(row.get("debit")),
        _amount_or_blank(row.get("credit")),
    ]


def ledger_xlsx_bytes(
    rows: list[dict],
    *,
    account_name: str = "",
    date_from=None,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
    sections: list[dict] | None = None,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Ledger"
    title_font = Font(bold=True, size=14)
    subtitle_font = Font(bold=True, size=11)
    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="D1D5DB")
    thin = Border(
        left=Side(style="thin", color="C5C9D0"),
        right=Side(style="thin", color="C5C9D0"),
        top=Side(style="thin", color="C5C9D0"),
        bottom=Side(style="thin", color="C5C9D0"),
    )
    center = Alignment(horizontal="center", wrap_text=True)
    right = Alignment(horizontal="right")
    wrap = Alignment(wrap_text=True, vertical="center")

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)
    cell = ws.cell(1, 1, company_name or "Ledger")
    cell.font = title_font
    cell.alignment = center
    row_no = 2
    if company_address:
        ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=6)
        cell = ws.cell(row_no, 1, company_address)
        cell.alignment = center
        row_no += 1
    title = "All Ledger" if sections else account_name
    ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=6)
    cell = ws.cell(row_no, 1, title)
    cell.font = subtitle_font
    cell.alignment = center
    row_no += 1
    period = " to ".join(part for part in (_fmt_date(date_from), _fmt_date(date_to)) if part)
    if period:
        ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=6)
        cell = ws.cell(row_no, 1, period)
        cell.alignment = center
        row_no += 1
    row_no += 1

    def write_headers():
        nonlocal row_no
        for col, header in enumerate(LEDGER_HEADERS, start=1):
            cell = ws.cell(row_no, col, header)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = thin
            cell.alignment = center
        row_no += 1

    def write_rows(items):
        nonlocal row_no
        for item in items:
            values = _ledger_row_cells(item)
            bold = item.get("kind") in ("closing", "total")
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row_no, col, value if value not in (None, "") else None)
                cell.border = thin
                if col in (5, 6):
                    cell.alignment = right
                    if isinstance(value, Decimal):
                        cell.number_format = "#,##0.00"
                else:
                    cell.alignment = wrap
                if bold:
                    cell.font = header_font
            row_no += 1

    def write_banner(text, *, size=11):
        nonlocal row_no
        ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=6)
        cell = ws.cell(row_no, 1, text)
        cell.font = Font(bold=True, size=size)
        row_no += 1

    if sections:
        last_parent = None
        last_group = None
        for section in sections:
            parent = section.get("parent_group") or ""
            group = section.get("account_group") or ""
            if parent != last_parent:
                write_banner(parent, size=12)
                last_parent = parent
                last_group = None
            if group and group != last_group:
                write_banner(group, size=11)
                last_group = group
            write_banner(section["account"].name, size=11)
            write_headers()
            write_rows(section.get("rows") or [])
            row_no += 1
    else:
        write_headers()
        write_rows(rows)

    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 28
    ws.column_dimensions["D"].width = 32
    ws.column_dimensions["E"].width = 14
    ws.column_dimensions["F"].width = 14
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def ledger_pdf_bytes(
    rows: list[dict],
    *,
    account_name: str = "",
    date_from=None,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
    sections: list[dict] | None = None,
) -> bytes:
    page_w, page_h = 842.0, 595.0
    margin = 36.0
    inner_w = page_w - 2 * margin
    col_widths = [70.0, 110.0, 150.0, inner_w - 70.0 - 110.0 - 150.0 - 160.0, 80.0, 80.0]
    row_h = 14.0
    pages: list[list[str]] = []
    ops: list[str] = []
    y = page_h - margin
    period = " to ".join(part for part in (_fmt_date(date_from), _fmt_date(date_to)) if part)

    def new_page():
        nonlocal ops, y
        if ops:
            pages.append(ops)
        ops = []
        y = page_h - margin
        if company_name:
            ops.append(_pdf_text(margin, y - 2, company_name, size=13, bold=True))
            y -= 16
        if company_address:
            ops.append(_pdf_text(margin, y, company_address, size=9))
            y -= 13
        heading = "All Ledger" if sections else account_name
        if heading:
            ops.append(_pdf_text(margin, y, heading, size=10, bold=True))
            y -= 13
        if period:
            ops.append(_pdf_text(margin, y, period, size=9))
            y -= 14
        y = _draw_table_row(ops, margin, y, LEDGER_HEADERS, col_widths, row_h, bold=True, fill=True, amounts_from=4)
        y -= 2

    def write_items(items):
        nonlocal y
        for item in items:
            if y - row_h < margin + 20:
                new_page()
            values = _ledger_row_cells(item)
            display = [_pdf_cell_text(value) for value in values]
            bold = item.get("kind") in ("closing", "total")
            y = _draw_table_row(
                ops,
                margin,
                y,
                display,
                col_widths,
                row_h,
                bold=bold,
                fill=item.get("kind") == "total",
                amounts_from=4,
            )

    new_page()
    if sections:
        for index, section in enumerate(sections):
            if index:
                new_page()
            parent = section.get("parent_group") or ""
            group = section.get("account_group") or ""
            if parent:
                ops.append(_pdf_text(margin, y, parent, size=11, bold=True))
                y -= 14
            if group:
                ops.append(_pdf_text(margin, y, group, size=10, bold=True))
                y -= 13
            ops.append(_pdf_text(margin, y, section["account"].name, size=10, bold=True))
            y -= 14
            write_items(section.get("rows") or [])
    else:
        write_items(rows)
    pages.append(ops)
    return _build_pdf(pages, page_w, page_h)


def ledger_excel_response(
    rows,
    *,
    account=None,
    date_from=None,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
    sections: list[dict] | None = None,
) -> HttpResponse:
    payload = ledger_xlsx_bytes(
        rows,
        account_name=getattr(account, "name", "") or "",
        date_from=date_from,
        date_to=date_to,
        company_name=company_name,
        company_address=company_address,
        sections=sections,
    )
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{_ledger_filename(account, date_from, date_to, "xlsx", all_ledgers=bool(sections))}"'
    )
    return response


def ledger_pdf_response(
    rows,
    *,
    account=None,
    date_from=None,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
    sections: list[dict] | None = None,
) -> HttpResponse:
    payload = ledger_pdf_bytes(
        rows,
        account_name=getattr(account, "name", "") or "",
        date_from=date_from,
        date_to=date_to,
        company_name=company_name,
        company_address=company_address,
        sections=sections,
    )
    response = HttpResponse(payload, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{_ledger_filename(account, date_from, date_to, "pdf", all_ledgers=bool(sections))}"'
    )
    return response


VOUCHER_LIST_HEADERS = ["Date", "Voucher No", "Narration", "Amount"]


def _voucher_list_filename(voucher_type: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in (voucher_type or "voucher"))
    slug = "-".join(part for part in slug.split("-") if part) or "voucher"
    return f"vouchers-{slug}.pdf"


def _voucher_list_amount(voucher) -> Decimal:
    amount = getattr(voucher, "amount", None)
    if amount is None:
        amount = voucher.debit_total()
    return money(amount)


def voucher_register_pdf_bytes(
    vouchers,
    *,
    title: str = "Vouchers",
    company_name: str = "",
    company_address: str = "",
) -> bytes:
    page_w, page_h = 595.0, 842.0
    margin = 36.0
    inner_w = page_w - 2 * margin
    col_widths = [72.0, 110.0, inner_w - 72.0 - 110.0 - 80.0, 80.0]
    row_h = 14.0
    pages: list[list[str]] = []
    ops: list[str] = []
    y = page_h - margin

    def new_page():
        nonlocal ops, y
        if ops:
            pages.append(ops)
        ops = []
        y = page_h - margin
        if company_name:
            ops.append(_pdf_text(margin, y - 2, company_name, size=13, bold=True))
            y -= 16
        if company_address:
            ops.append(_pdf_text(margin, y, company_address, size=9))
            y -= 13
        if title:
            ops.append(_pdf_text(margin, y, title, size=11, bold=True))
            y -= 16
        y = _draw_table_row(
            ops, margin, y, VOUCHER_LIST_HEADERS, col_widths, row_h, bold=True, fill=True, amounts_from=3
        )
        y -= 2

    new_page()
    for voucher in vouchers:
        if y - row_h < margin + 20:
            new_page()
        values = [
            _fmt_date(getattr(voucher, "date", None)),
            getattr(voucher, "number", "") or "",
            getattr(voucher, "narration", "") or "",
            _voucher_list_amount(voucher),
        ]
        display = [_pdf_cell_text(value) for value in values]
        y = _draw_table_row(ops, margin, y, display, col_widths, row_h, amounts_from=3)
    pages.append(ops)
    return _build_pdf(pages, page_w, page_h)


def voucher_register_pdf_response(
    vouchers,
    *,
    title: str = "Vouchers",
    voucher_type: str = "",
    company_name: str = "",
    company_address: str = "",
) -> HttpResponse:
    payload = voucher_register_pdf_bytes(
        vouchers,
        title=title,
        company_name=company_name,
        company_address=company_address,
    )
    response = HttpResponse(payload, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{_voucher_list_filename(voucher_type)}"'
    return response


BOOK_REGISTER_HEADERS = ["Date", "Voucher No", "Particulars", "Narration", "Amount"]
SALES_GST_HEADERS = [
    "Date",
    "Voucher No",
    "Customer Name",
    "GSTIN NO",
    "B2B Sales",
    "B2C Sales",
    "Pure Agent",
    "IGST",
    "CGST",
    "SGST",
    "Total",
]
SALES_NGST_HEADERS = ["Date", "Voucher No", "Customer Name", "Sales", "Total"]


def _book_register_filename(title: str, date_from, date_to, ext: str) -> str:
    raw = "".join(ch.lower() if ch.isalnum() else "-" for ch in (title or "register"))
    slug = "-".join(part for part in raw.split("-") if part) or "register"
    start = date_from.isoformat() if date_from else "start"
    end = date_to.isoformat() if date_to else "end"
    return f"{slug}-{start}-to-{end}.{ext}"


def _book_register_row_cells(row: dict) -> list:
    return [
        _fmt_date(row.get("date")),
        row.get("number") or "",
        row.get("particulars") or "",
        row.get("narration") or "",
        _amount_or_blank(row.get("amount")),
    ]


def _sales_gst_row_cells(row: dict) -> list:
    return [
        _fmt_date(row.get("date")),
        row.get("number") or "",
        row.get("customer") or "",
        row.get("gstin") or "",
        _amount_or_blank(row.get("b2b_sales")),
        _amount_or_blank(row.get("b2c_sales")),
        _amount_or_blank(row.get("pure_agent")),
        _amount_or_blank(row.get("igst")),
        _amount_or_blank(row.get("cgst")),
        _amount_or_blank(row.get("sgst")),
        _amount_or_blank(row.get("total")),
    ]


def _sales_ngst_row_cells(row: dict) -> list:
    return [
        _fmt_date(row.get("date")),
        row.get("number") or "",
        row.get("customer") or "",
        _amount_or_blank(row.get("sales")),
        _amount_or_blank(row.get("total")),
    ]


def _register_layout(invoice_kind: str = "") -> dict:
    if invoice_kind == "gst":
        return {
            "headers": SALES_GST_HEADERS,
            "cells": _sales_gst_row_cells,
            "amount_from": 4,
            "total_prefix": ["Total", "", "", ""],
            "total_keys": ["b2b_sales", "b2c_sales", "pure_agent", "igst", "cgst", "sgst", "total"],
            "xlsx_widths": [14, 20, 26, 18, 13, 13, 13, 11, 11, 11, 13],
        }
    if invoice_kind == "ngst":
        return {
            "headers": SALES_NGST_HEADERS,
            "cells": _sales_ngst_row_cells,
            "amount_from": 3,
            "total_prefix": ["Total", "", ""],
            "total_keys": ["sales", "total"],
            "xlsx_widths": [14, 22, 28, 14, 14],
        }
    return {
        "headers": BOOK_REGISTER_HEADERS,
        "cells": _book_register_row_cells,
        "amount_from": 4,
        "total_prefix": ["Total", "", "", ""],
        "total_keys": ["amount"],
        "xlsx_widths": [14, 22, 28, 32, 14],
    }


def _register_pdf_col_widths(headers: list[str], inner_w: float) -> list[float]:
    count = len(headers)
    if count == 11:
        widths = [54.0, 86.0, 96.0, 78.0, 58.0, 58.0, 56.0, 50.0, 50.0, 50.0, 62.0]
    elif count == 5 and headers[3] == "Sales":
        widths = [70.0, 110.0, 220.0, 90.0, 90.0]
    else:
        widths = [70.0, 110.0, 160.0, inner_w - 70.0 - 110.0 - 160.0 - 80.0, 80.0]
    total = sum(widths)
    if total != inner_w and total > 0:
        scale = inner_w / total
        widths = [round(w * scale, 2) for w in widths]
        widths[-1] = round(inner_w - sum(widths[:-1]), 2)
    return widths


def book_register_xlsx_bytes(
    rows: list[dict],
    *,
    title: str = "Register",
    date_from=None,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
    invoice_kind: str = "",
) -> bytes:
    layout = _register_layout(invoice_kind)
    headers = layout["headers"]
    ncol = len(headers)
    amount_from = layout["amount_from"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Register"
    title_font = Font(bold=True, size=14)
    subtitle_font = Font(bold=True, size=11)
    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="D1D5DB")
    thin = Border(
        left=Side(style="thin", color="C5C9D0"),
        right=Side(style="thin", color="C5C9D0"),
        top=Side(style="thin", color="C5C9D0"),
        bottom=Side(style="thin", color="C5C9D0"),
    )
    center = Alignment(horizontal="center", wrap_text=True)
    right = Alignment(horizontal="right")
    wrap = Alignment(wrap_text=True, vertical="center")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    cell = ws.cell(1, 1, company_name or title)
    cell.font = title_font
    cell.alignment = center
    row_no = 2
    if company_address:
        ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=ncol)
        cell = ws.cell(row_no, 1, company_address)
        cell.alignment = center
        row_no += 1
    ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=ncol)
    cell = ws.cell(row_no, 1, title)
    cell.font = subtitle_font
    cell.alignment = center
    row_no += 1
    period = " to ".join(part for part in (_fmt_date(date_from), _fmt_date(date_to)) if part)
    if period:
        ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=ncol)
        cell = ws.cell(row_no, 1, period)
        cell.alignment = center
        row_no += 1
    row_no += 1
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row_no, col, header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin
        cell.alignment = center
    row_no += 1
    totals = {key: Decimal("0.00") for key in layout["total_keys"]}
    for item in rows:
        values = layout["cells"](item)
        for key in totals:
            totals[key] += money(item.get(key))
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row_no, col, value if value not in (None, "") else None)
            cell.border = thin
            if col > amount_from:
                cell.alignment = right
                if isinstance(value, Decimal):
                    cell.number_format = "#,##0.00"
            else:
                cell.alignment = wrap
        row_no += 1
    prefix = layout["total_prefix"]
    ws.cell(row_no, 1, "Total").font = header_font
    for col, key in enumerate(layout["total_keys"], start=len(prefix) + 1):
        cell = ws.cell(row_no, col, totals[key])
        cell.font = header_font
        cell.alignment = right
        cell.number_format = "#,##0.00"
    for index, width in enumerate(layout["xlsx_widths"], start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def book_register_pdf_bytes(
    rows: list[dict],
    *,
    title: str = "Register",
    date_from=None,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
    invoice_kind: str = "",
) -> bytes:
    layout = _register_layout(invoice_kind)
    headers = layout["headers"]
    amount_from = layout["amount_from"]
    page_w, page_h = 842.0, 595.0
    margin = 28.0 if invoice_kind == "gst" else 36.0
    inner_w = page_w - 2 * margin
    col_widths = _register_pdf_col_widths(headers, inner_w)
    row_h = 14.0
    pages: list[list[str]] = []
    ops: list[str] = []
    y = page_h - margin
    period = " to ".join(part for part in (_fmt_date(date_from), _fmt_date(date_to)) if part)

    def new_page():
        nonlocal ops, y
        if ops:
            pages.append(ops)
        ops = []
        y = page_h - margin
        if company_name:
            ops.append(_pdf_text(margin, y - 2, company_name, size=13, bold=True))
            y -= 16
        if company_address:
            ops.append(_pdf_text(margin, y, company_address, size=9))
            y -= 13
        if title:
            ops.append(_pdf_text(margin, y, title, size=11, bold=True))
            y -= 14
        if period:
            ops.append(_pdf_text(margin, y, period, size=9))
            y -= 14
        y = _draw_table_row(
            ops, margin, y, headers, col_widths, row_h, bold=True, fill=True, amounts_from=amount_from
        )
        y -= 2

    new_page()
    totals = {key: Decimal("0.00") for key in layout["total_keys"]}
    for item in rows:
        if y - row_h < margin + 24:
            new_page()
        for key in totals:
            totals[key] += money(item.get(key))
        display = [_pdf_cell_text(value) for value in layout["cells"](item)]
        y = _draw_table_row(ops, margin, y, display, col_widths, row_h, amounts_from=amount_from)
    if y - row_h < margin + 20:
        new_page()
    footer = list(layout["total_prefix"]) + [_pdf_cell_text(totals[key]) for key in layout["total_keys"]]
    y = _draw_table_row(
        ops,
        margin,
        y,
        footer,
        col_widths,
        row_h,
        bold=True,
        fill=True,
        amounts_from=amount_from,
    )
    pages.append(ops)
    return _build_pdf(pages, page_w, page_h)


def book_register_excel_response(
    rows,
    *,
    title: str = "Register",
    date_from=None,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
    invoice_kind: str = "",
) -> HttpResponse:
    payload = book_register_xlsx_bytes(
        rows,
        title=title,
        date_from=date_from,
        date_to=date_to,
        company_name=company_name,
        company_address=company_address,
        invoice_kind=invoice_kind,
    )
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{_book_register_filename(title, date_from, date_to, "xlsx")}"'
    )
    return response


def book_register_pdf_response(
    rows,
    *,
    title: str = "Register",
    date_from=None,
    date_to=None,
    company_name: str = "",
    company_address: str = "",
    invoice_kind: str = "",
) -> HttpResponse:
    payload = book_register_pdf_bytes(
        rows,
        title=title,
        date_from=date_from,
        date_to=date_to,
        company_name=company_name,
        company_address=company_address,
        invoice_kind=invoice_kind,
    )
    response = HttpResponse(payload, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{_book_register_filename(title, date_from, date_to, "pdf")}"'
    )
    return response


BILLWISE_HEADERS = ["Sl.no", "Date", "Invoice No", "Total Outstanding", "Due For"]


def billwise_outstanding_xlsx_bytes(
    data: dict,
    *,
    title: str = "Bill wise outstanding",
    company_name: str = "",
    company_address: str = "",
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Outstanding"
    title_font = Font(bold=True, size=14)
    subtitle_font = Font(bold=True, size=11)
    header_font = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="D1D5DB")
    thin = Border(
        left=Side(style="thin", color="C5C9D0"),
        right=Side(style="thin", color="C5C9D0"),
        top=Side(style="thin", color="C5C9D0"),
        bottom=Side(style="thin", color="C5C9D0"),
    )
    center = Alignment(horizontal="center", wrap_text=True)
    right = Alignment(horizontal="right")
    wrap = Alignment(wrap_text=True, vertical="center")
    ncol = 5
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
    cell = ws.cell(1, 1, company_name or title)
    cell.font = title_font
    cell.alignment = center
    row_no = 2
    if company_address:
        ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=ncol)
        cell = ws.cell(row_no, 1, company_address)
        cell.alignment = center
        row_no += 1
    ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=ncol)
    cell = ws.cell(row_no, 1, title)
    cell.font = subtitle_font
    cell.alignment = center
    row_no += 1
    as_on = data.get("as_on")
    if as_on:
        ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=ncol)
        cell = ws.cell(row_no, 1, f"As on {_fmt_date(as_on)}")
        cell.alignment = center
        row_no += 1
    row_no += 1
    for section in data.get("sections") or []:
        ws.merge_cells(start_row=row_no, start_column=1, end_row=row_no, end_column=ncol)
        cell = ws.cell(row_no, 1, section.get("name") or "")
        cell.font = header_font
        row_no += 1
        for col, header in enumerate(BILLWISE_HEADERS, start=1):
            cell = ws.cell(row_no, col, header)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = thin
            cell.alignment = center
        row_no += 1
        for item in section.get("rows") or []:
            values = [
                item.get("sl_no"),
                _fmt_date(item.get("date")),
                item.get("number") or "",
                _amount_or_blank(item.get("outstanding")),
                item.get("due_for") or "",
            ]
            for col, value in enumerate(values, start=1):
                cell = ws.cell(row_no, col, value if value not in (None, "") else None)
                cell.border = thin
                if col == 4:
                    cell.alignment = right
                    if isinstance(value, Decimal):
                        cell.number_format = "#,##0.00"
                else:
                    cell.alignment = wrap
            row_no += 1
        ws.cell(row_no, 1, "Total").font = header_font
        cell = ws.cell(row_no, 4, money(section.get("total")))
        cell.font = header_font
        cell.alignment = right
        cell.number_format = "#,##0.00"
        row_no += 2
    if data.get("sections"):
        ws.cell(row_no, 1, "Grand total").font = header_font
        cell = ws.cell(row_no, 4, money(data.get("grand_total")))
        cell.font = header_font
        cell.alignment = right
        cell.number_format = "#,##0.00"
    ws.column_dimensions["A"].width = 10
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 24
    ws.column_dimensions["D"].width = 18
    ws.column_dimensions["E"].width = 14
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def billwise_outstanding_pdf_bytes(
    data: dict,
    *,
    title: str = "Bill wise outstanding",
    company_name: str = "",
    company_address: str = "",
) -> bytes:
    page_w, page_h = 595.0, 842.0
    margin = 36.0
    inner_w = page_w - 2 * margin
    col_widths = [46.0, 72.0, inner_w - 46.0 - 72.0 - 90.0 - 80.0, 90.0, 80.0]
    row_h = 14.0
    pages: list[list[str]] = []
    ops: list[str] = []
    y = page_h - margin
    as_on = data.get("as_on")
    as_on_text = f"As on {_fmt_date(as_on)}" if as_on else ""

    def new_page():
        nonlocal ops, y
        if ops:
            pages.append(ops)
        ops = []
        y = page_h - margin
        if company_name:
            ops.append(_pdf_text(margin, y - 2, company_name, size=13, bold=True))
            y -= 16
        if company_address:
            ops.append(_pdf_text(margin, y, company_address, size=9))
            y -= 13
        if title:
            ops.append(_pdf_text(margin, y, title, size=11, bold=True))
            y -= 14
        if as_on_text:
            ops.append(_pdf_text(margin, y, as_on_text, size=9))
            y -= 14

    def ensure_space(needed):
        nonlocal y
        if y - needed < margin + 24:
            new_page()

    new_page()
    for section in data.get("sections") or []:
        ensure_space(row_h * 4)
        ops.append(_pdf_text(margin, y, section.get("name") or "", size=10, bold=True))
        y -= 16
        y = _draw_table_row(
            ops, margin, y, BILLWISE_HEADERS, col_widths, row_h, bold=True, fill=True, amounts_from=3
        )
        for item in section.get("rows") or []:
            ensure_space(row_h)
            display = [
                str(item.get("sl_no") or ""),
                _fmt_date(item.get("date")),
                item.get("number") or "",
                _pdf_cell_text(item.get("outstanding")),
                item.get("due_for") or "",
            ]
            y = _draw_table_row(ops, margin, y, display, col_widths, row_h, amounts_from=3)
        ensure_space(row_h + 8)
        y = _draw_table_row(
            ops,
            margin,
            y,
            ["Total", "", "", _pdf_cell_text(section.get("total")), ""],
            col_widths,
            row_h,
            bold=True,
            fill=True,
            amounts_from=3,
        )
        y -= 10
    if data.get("sections"):
        ensure_space(row_h)
        y = _draw_table_row(
            ops,
            margin,
            y,
            ["Grand total", "", "", _pdf_cell_text(data.get("grand_total")), ""],
            col_widths,
            row_h,
            bold=True,
            fill=True,
            amounts_from=3,
        )
    pages.append(ops)
    return _build_pdf(pages, page_w, page_h)


def billwise_outstanding_excel_response(
    data: dict,
    *,
    title: str = "Bill wise outstanding",
    company_name: str = "",
    company_address: str = "",
) -> HttpResponse:
    payload = billwise_outstanding_xlsx_bytes(
        data, title=title, company_name=company_name, company_address=company_address
    )
    as_on = data.get("as_on")
    response = HttpResponse(
        payload,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{_book_register_filename(title, as_on, as_on, "xlsx")}"'
    )
    return response


def billwise_outstanding_pdf_response(
    data: dict,
    *,
    title: str = "Bill wise outstanding",
    company_name: str = "",
    company_address: str = "",
) -> HttpResponse:
    payload = billwise_outstanding_pdf_bytes(
        data, title=title, company_name=company_name, company_address=company_address
    )
    as_on = data.get("as_on")
    response = HttpResponse(payload, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{_book_register_filename(title, as_on, as_on, "pdf")}"'
    )
    return response
