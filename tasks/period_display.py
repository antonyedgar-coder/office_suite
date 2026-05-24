"""Human-readable filing period for task lists (frequency + period)."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass

from .one_time_period import is_one_time_period_key, parse_one_time_period_key
from .period_keys import fy_choice_label
from .recurrence import next_period_key

_CYCLE_RE = re.compile(r"^cycle-(\d+)$")

# Compact labels for list / report / CSV columns
_FREQUENCY_LABEL = {
    "one_time": "One time",
    "monthly": "Monthly",
    "quarterly": "Qtr",
    "half_yearly": "Half yearly",
    "yearly": "Yearly",
    "every_3_years": "3 years",
    "every_5_years": "5 years",
    # Task master recurrence values
    "annually": "Yearly",
}


@dataclass
class PeriodColumns:
    frequency: str = ""
    period: str = ""
    next_period: str = ""


def _fy_label_from_start(y: int) -> str:
    return fy_choice_label(y)


def _infer_frequency_from_period_key(period_key: str) -> str:
    pk = (period_key or "").strip()
    if is_one_time_period_key(pk) or not pk or pk == "one-time":
        return _FREQUENCY_LABEL["one_time"]
    if re.match(r"^\d{4}-\d{2}$", pk):
        return "Monthly"
    if re.match(r"^\d{4}-Q[1-4]$", pk):
        return "Qtr"
    if re.match(r"^\d{4}-H[12]$", pk):
        return "Half yearly"
    if pk.startswith("FY"):
        return "Yearly"
    m = re.match(r"^(\d{4})-(\d{4})$", pk)
    if m:
        span = int(m.group(2)) - int(m.group(1)) + 1
        return "5 years" if span == 5 else "3 years"
    if _CYCLE_RE.match(pk):
        return "3 years"
    return ""


def _period_text_from_period_key(period_key: str) -> str:
    pk = (period_key or "").strip()
    parsed = parse_one_time_period_key(pk)
    if parsed:
        label = f"{parsed['month_abbr']} {parsed['ym'][:4]}"
        if parsed["sequence"] >= 2:
            return f"{label} ({parsed['sequence']})"
        return label
    if not pk or pk == "one-time":
        return "—"
    if re.match(r"^\d{4}-\d{2}$", pk):
        y, m = map(int, pk.split("-"))
        return f"{calendar.month_abbr[m]} {y}"
    m = re.match(r"^(\d{4})-Q([1-4])$", pk)
    if m:
        fy = int(m.group(1))
        q = int(m.group(2))
        qtr_names = {1: "Apr–Jun", 2: "Jul–Sep", 3: "Oct–Dec", 4: "Jan–Mar"}
        return f"Q{q} ({qtr_names[q]}) {_fy_label_from_start(fy)}"
    m = re.match(r"^(\d{4})-H([12])$", pk)
    if m:
        fy = int(m.group(1))
        h = int(m.group(2))
        half_name = "Apr–Sep" if h == 1 else "Oct–Mar"
        return f"H{h} ({half_name}) {_fy_label_from_start(fy)}"
    if pk.startswith("FY"):
        raw = pk[2:]
        return raw if re.match(r"^\d{4}-\d{2}$", raw) else pk
    m = re.match(r"^(\d{4})-(\d{4})$", pk)
    if m:
        y0, y1 = int(m.group(1)), int(m.group(2))
        return f"{_fy_label_from_start(y0)} to {_fy_label_from_start(y1)}"
    if _CYCLE_RE.match(pk):
        return pk
    return pk


def format_period_display(
    period_key: str,
    *,
    period_type: str = "",
    master=None,
) -> PeriodColumns:
    """Single frequency label + human-readable period for list/report columns."""
    pk = (period_key or "").strip()
    pt = (period_type or "").strip()
    freq = _FREQUENCY_LABEL.get(pt, "").strip()
    if not freq and master is not None and getattr(master, "frequency", None):
        freq = _FREQUENCY_LABEL.get((master.frequency or "").strip(), "") or (
            master.get_frequency_display() or ""
        )
    if not freq:
        freq = _infer_frequency_from_period_key(pk)
    period = _period_text_from_period_key(pk)
    return PeriodColumns(frequency=freq or "—", period=period)


def format_period_key(period_key: str) -> PeriodColumns:
    """Backward-compatible entry point (frequency inferred from period_key only)."""
    return format_period_display(period_key)


def format_next_period(task) -> str:
    master = task.task_master
    if not master.is_recurring or not task.enrollment_id:
        return ""
    try:
        nxt = next_period_key(master, task.period_key, task.enrollment.started_at)
    except Exception:
        return ""
    cols = format_period_display(nxt, period_type=task.period_type or "", master=master)
    return cols.period if cols.period and cols.period != "—" else nxt
