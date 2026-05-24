"""Period kinds for document uploads (no subfolders)."""

from __future__ import annotations

import re
from calendar import month_name
from datetime import date

from django.core.exceptions import ValidationError

from dirkyc.fy import fy_label_for_date, mis_report_financial_year_choices

PERIOD_NONE = "none"
PERIOD_MONTH = "month"
PERIOD_QUARTER = "quarter"
PERIOD_HALF_YEAR = "half_year"
PERIOD_INDIAN_FY = "indian_fy"

PERIOD_KIND_CHOICES = [
    (PERIOD_NONE, "One-time (no period)"),
    (PERIOD_MONTH, "Monthly (calendar month)"),
    (PERIOD_QUARTER, "Quarterly (within Indian FY)"),
    (PERIOD_HALF_YEAR, "Half-yearly (within Indian FY)"),
    (PERIOD_INDIAN_FY, "Indian financial year"),
]

QUARTER_CHOICES = [("Q1", "Q1 (Apr–Jun)"), ("Q2", "Q2 (Jul–Sep)"), ("Q3", "Q3 (Oct–Dec)"), ("Q4", "Q4 (Jan–Mar)")]
HALF_YEAR_CHOICES = [("H1", "H1 (Apr–Sep)"), ("H2", "H2 (Oct–Mar)")]

QUARTER_FILENAME_SUFFIX = {
    "Q1": "Apr-Jun",
    "Q2": "Jul-Sep",
    "Q3": "Oct-Dec",
    "Q4": "Jan-Mar",
}
HALF_YEAR_FILENAME_SUFFIX = {
    "H1": "Apr-Sep",
    "H2": "Oct-Mar",
}
_MONTH_ABBR = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def month_value_choices(*, today: date | None = None) -> list[tuple[str, str]]:
    """YYYY-MM values for roughly 3 years back and 1 year forward."""
    today = today or date.today()
    y, m = today.year, today.month
    out: list[tuple[str, str]] = []
    for offset in range(-36, 13):
        mm = m + offset
        yy = y
        while mm < 1:
            mm += 12
            yy -= 1
        while mm > 12:
            mm -= 12
            yy += 1
        val = f"{yy:04d}-{mm:02d}"
        label = f"{month_name[mm]} {yy}"
        if val not in dict(out):
            out.append((val, label))
    return sorted(out, key=lambda x: x[0], reverse=True)


def fy_choices(*, today: date | None = None) -> list[tuple[str, str]]:
    return mis_report_financial_year_choices(today=today or date.today())


def period_kind_label(kind: str) -> str:
    return dict(PERIOD_KIND_CHOICES).get(kind, kind)


_FY_MONTH_KEY_RE = re.compile(r"^(\d{4}-\d{2})-(\d{4}-\d{2})(?:-\d+)?$")
_ONE_TIME_DOC_KEY_RE = re.compile(r"^FY(\d{4}-\d{2})-(\d{4}-\d{2})(?:-(\d+))?$")


def extract_fy_from_period_key(period_key: str) -> str:
    """Indian FY label (e.g. 2024-25) parsed from period_key."""
    pk = (period_key or "").strip()
    m = _ONE_TIME_DOC_KEY_RE.match(pk)
    if m:
        return m.group(1)
    if not pk.startswith("FY"):
        if len(pk) == 7 and pk[4] == "-":
            try:
                y, m = int(pk[:4]), int(pk[5:7])
                return fy_label_for_date(date(y, m, 1))
            except ValueError:
                return ""
        return ""
    rest = pk[2:]
    if "-Q" in rest:
        return rest.split("-Q", 1)[0]
    if "-H" in rest:
        return rest.split("-H", 1)[0]
    m = _FY_MONTH_KEY_RE.match(rest)
    if m:
        return m.group(1)
    return rest


def period_fy_display(
    period_key: str,
    *,
    financial_year: str = "",
    period_label: str = "",
) -> str:
    """Value for the FY table column (FY label only, e.g. 2024-25)."""
    pk = (period_key or "").strip()
    if pk == "once":
        return "—"
    m = _ONE_TIME_DOC_KEY_RE.match(pk)
    if m:
        return m.group(1)
    fy = (financial_year or "").strip() or extract_fy_from_period_key(pk)
    if fy:
        return fy
    if pk.startswith("FY"):
        return pk[2:]
    return "—"


def _month_abbr_from_ym(ym: str) -> str:
    parts = (ym or "").split("-")
    if len(parts) != 2:
        return ""
    try:
        m = int(parts[1])
        if 1 <= m <= 12:
            return _MONTH_ABBR[m]
    except ValueError:
        pass
    return ""


def _month_name_from_ym(ym: str) -> str:
    parts = (ym or "").split("-")
    if len(parts) != 2:
        return ym
    try:
        y, m = int(parts[0]), int(parts[1])
        return month_name[m]
    except (ValueError, IndexError):
        return ym


def _parse_period_key_parts(period_key: str) -> dict[str, str]:
    """Extract fy, month ym, quarter, half, and optional one-time sequence from period_key."""
    pk = (period_key or "").strip()
    out = {"fy": "", "ym": "", "quarter": "", "half": "", "sequence": ""}
    m = _ONE_TIME_DOC_KEY_RE.match(pk)
    if m:
        out["fy"] = m.group(1)
        out["ym"] = m.group(2)
        if m.group(3):
            out["sequence"] = m.group(3)
        return out
    if not pk.startswith("FY"):
        if len(pk) == 7 and pk[4] == "-":
            out["ym"] = pk
            out["fy"] = fy_label_for_date(date(int(pk[:4]), int(pk[5:7]), 1))
        return out
    rest = pk[2:]
    m = _FY_MONTH_KEY_RE.match(rest)
    if m:
        out["fy"] = m.group(1)
        out["ym"] = m.group(2)
        return out
    for q in ("Q1", "Q2", "Q3", "Q4"):
        if rest.endswith(f"-{q}"):
            out["fy"] = rest[: -(len(q) + 1)]
            out["quarter"] = q
            return out
    for h in ("H1", "H2"):
        if rest.endswith(f"-{h}"):
            out["fy"] = rest[: -(len(h) + 1)]
            out["half"] = h
            return out
    out["fy"] = rest
    return out


def period_detail_display(period_kind: str, period_key: str, *, period_label: str = "") -> str:
    """Value for the Period column: month name, Q1–Q4, H1/H2, Yearly, or —."""
    kind = (period_kind or PERIOD_NONE).strip()
    pk = (period_key or "").strip()
    if pk == "once" or (kind == PERIOD_NONE and not _ONE_TIME_DOC_KEY_RE.match(pk)):
        return "—"
    if _ONE_TIME_DOC_KEY_RE.match(pk):
        parts = _parse_period_key_parts(pk)
        label = _month_name_from_ym(parts["ym"]) if parts["ym"] else "—"
        if parts.get("sequence"):
            return f"{label} ({parts['sequence']})"
        return label
    if kind == PERIOD_INDIAN_FY:
        return "Yearly"
    parts = _parse_period_key_parts(pk)
    if kind == PERIOD_MONTH:
        if parts["ym"]:
            return _month_name_from_ym(parts["ym"])
        if period_label:
            return period_label.split(" FY ")[0].strip()
        return "—"
    if kind == PERIOD_QUARTER:
        return parts["quarter"] or "—"
    if kind == PERIOD_HALF_YEAR:
        return parts["half"] or "—"
    return "—"


def build_standard_filename(
    *,
    document_type_name: str,
    client_name: str,
    period_kind: str,
    period_key: str,
    extension: str,
    sanitize,
) -> str:
    """
    Auto filename: Type_Client for one-time; Type_Client_FY_Apr (monthly);
    Type_Client_FY_Apr-Jun (quarterly); Type_Client_FY_Apr-Sep (half-yearly);
    Type_Client_FY (yearly).
    """
    type_part = sanitize(document_type_name)
    client_part = sanitize(client_name)
    kind = (period_kind or PERIOD_NONE).strip()
    pk = (period_key or "").strip()
    ext = (extension or "").lower().lstrip(".")

    if kind == PERIOD_NONE or pk == "once":
        base = f"{type_part}_{client_part}"
    else:
        parts = _parse_period_key_parts(pk)
        fy = parts["fy"] or extract_fy_from_period_key(pk)
        if not fy:
            base = f"{type_part}_{client_part}"
        elif kind == PERIOD_INDIAN_FY:
            base = f"{type_part}_{client_part}_{fy}"
        elif kind == PERIOD_MONTH:
            abbr = _month_abbr_from_ym(parts["ym"]) if parts["ym"] else ""
            base = f"{type_part}_{client_part}_{fy}_{abbr}" if abbr else f"{type_part}_{client_part}_{fy}"
        elif kind == PERIOD_QUARTER:
            q = parts["quarter"]
            span = QUARTER_FILENAME_SUFFIX.get(q, q)
            base = f"{type_part}_{client_part}_{fy}_{span}"
        elif kind == PERIOD_HALF_YEAR:
            h = parts["half"]
            span = HALF_YEAR_FILENAME_SUFFIX.get(h, h)
            base = f"{type_part}_{client_part}_{fy}_{span}"
        else:
            base = f"{type_part}_{client_part}_{fy}"

    return f"{base}.{ext}" if ext else base


def build_one_time_task_filename(
    *,
    task_master_name: str,
    client_name: str,
    period_key: str,
    extension: str,
    sanitize,
) -> str:
    """
    One-time task upload filename:
    TaskType-ClientName_FY2024-25_Mar (first in month);
    TaskType-ClientName_FY2024-25_Mar_2 when multiple in the same month.
    """
    type_part = sanitize(task_master_name)
    client_part = sanitize(client_name)
    ext = (extension or "").lower().lstrip(".")
    parts = _parse_period_key_parts(period_key)
    fy = parts["fy"] or extract_fy_from_period_key(period_key)
    abbr = _month_abbr_from_ym(parts["ym"]) if parts["ym"] else ""
    if fy and abbr:
        base = f"{type_part}-{client_part}_FY{fy}_{abbr}"
    elif fy:
        base = f"{type_part}-{client_part}_FY{fy}"
    else:
        base = f"{type_part}-{client_part}"
    seq = (parts.get("sequence") or "").strip()
    if seq and seq != "1":
        base = f"{base}_{seq}"
    return f"{base}.{ext}" if ext else base


def build_custom_user_filename(
    *,
    user_label: str,
    period_key: str,
    period_label: str,
    extension: str,
    sanitize,
) -> str:
    """User-chosen label with FY and period appended (Supporting Documents)."""
    name_part = sanitize(user_label)
    pk = (period_key or "").strip()
    ext = (extension or "").lower().lstrip(".")
    ot = _ONE_TIME_DOC_KEY_RE.match(pk)
    if ot:
        fy = ot.group(1)
        abbr = _month_abbr_from_ym(ot.group(2))
        seq = ot.group(3)
        base = f"{name_part}_FY{fy}_{abbr}" if abbr else f"{name_part}_FY{fy}"
        if seq and seq != "1":
            base = f"{base}_{seq}"
        return f"{base}.{ext}" if ext else base

    fy = extract_fy_from_period_key(period_key)
    period_part = sanitize((period_label or "").strip() or "Once")
    ext = (extension or "").lower().lstrip(".")

    if fy and period_part and period_part != "Once" and period_part != "—":
        base = f"{name_part}_FY{fy}_{period_part}"
    elif fy:
        base = f"{name_part}_FY{fy}"
    elif period_part and period_part not in ("Once", "—"):
        base = f"{name_part}_{period_part}"
    else:
        base = name_part
    return f"{base}.{ext}" if ext else base


def _month_display(ym: str) -> str:
    parts = ym.split("-")
    if len(parts) != 2:
        return ym
    try:
        y, m = int(parts[0]), int(parts[1])
        return f"{month_name[m]} {y}"
    except (ValueError, IndexError):
        return ym


def resolve_period(
    period_kind: str,
    *,
    period_month: str = "",
    period_fy: str = "",
    period_quarter: str = "",
    period_half: str = "",
) -> tuple[str, str]:
    """
    Return (period_key, period_label) for storage and display.
    """
    kind = (period_kind or PERIOD_NONE).strip()

    if kind == PERIOD_NONE:
        return "once", "—"

    fy = (period_fy or "").strip()
    if kind in (PERIOD_MONTH, PERIOD_QUARTER, PERIOD_HALF_YEAR, PERIOD_INDIAN_FY) and not fy:
        raise ValidationError("Select the financial year.")

    if kind == PERIOD_MONTH:
        ym = (period_month or "").strip()
        if not ym or len(ym) != 7:
            raise ValidationError("Select the calendar month for this file.")
        return f"FY{fy}-{ym}", _month_name_from_ym(ym)

    if kind == PERIOD_INDIAN_FY:
        return f"FY{fy}", "Yearly"

    if kind == PERIOD_QUARTER:
        q = (period_quarter or "").strip().upper()
        if q not in ("Q1", "Q2", "Q3", "Q4"):
            raise ValidationError("Select the quarter (Q1–Q4).")
        return f"FY{fy}-{q}", q

    if kind == PERIOD_HALF_YEAR:
        h = (period_half or "").strip().upper()
        if h not in ("H1", "H2"):
            raise ValidationError("Select half-year (H1 or H2).")
        return f"FY{fy}-{h}", h

    raise ValidationError("Unknown period kind for this file type.")


def filename_period_context(period_key: str, period_label: str) -> dict[str, str]:
    """Placeholders for name_template.format()."""
    pk = period_key or ""
    pl = period_label or ""
    ctx = {
        "period_key": pk,
        "period_label": pl.replace(" ", "_"),
        "fy": "",
        "month_label": "",
        "quarter_label": "",
        "half_label": "",
    }
    if pk == "once":
        return ctx
    if pk.startswith("FY"):
        rest = pk[2:]
        m = _FY_MONTH_KEY_RE.match(rest)
        if m:
            ctx["fy"] = f"FY{m.group(1)}"
            ctx["month_label"] = m.group(2).replace("-", "")
            return ctx
    if len(pk) == 7 and pk[4] == "-":
        ctx["month_label"] = pk.replace("-", "")
        return ctx
    if pk.startswith("FY") and "-Q" in pk:
        bits = pk.split("-", 1)
        ctx["fy"] = bits[0]
        ctx["quarter_label"] = bits[1] if len(bits) > 1 else ""
        return ctx
    if pk.startswith("FY") and "-H" in pk:
        bits = pk.split("-", 1)
        ctx["fy"] = bits[0]
        ctx["half_label"] = bits[1] if len(bits) > 1 else ""
        return ctx
    if pk.startswith("FY"):
        ctx["fy"] = pk
        return ctx
    return ctx
