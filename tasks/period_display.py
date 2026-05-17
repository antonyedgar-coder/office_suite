"""Human-readable filing period columns from task period_key."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass

from .period_keys import fy_choice_label
from .recurrence import next_period_key

_CYCLE_RE = re.compile(r"^cycle-(\d+)$")


@dataclass
class PeriodColumns:
    month: str = ""
    quarter: str = ""
    half: str = ""
    yearly: str = ""
    span_3y: str = ""
    span_5y: str = ""
    next_period: str = ""


def _fy_label_from_start(y: int) -> str:
    return fy_choice_label(y)


def format_period_key(period_key: str) -> PeriodColumns:
    pk = (period_key or "").strip()
    cols = PeriodColumns()
    if not pk or pk == "one-time":
        return cols

    if re.match(r"^\d{4}-\d{2}$", pk):
        y, m = map(int, pk.split("-"))
        cols.month = f"{calendar.month_abbr[m]} {y}"
        return cols

    m = re.match(r"^(\d{4})-Q([1-4])$", pk)
    if m:
        fy = int(m.group(1))
        q = int(m.group(2))
        qtr_names = {1: "Apr–Jun", 2: "Jul–Sep", 3: "Oct–Dec", 4: "Jan–Mar"}
        cols.quarter = f"Q{q} ({qtr_names[q]}) {_fy_label_from_start(fy)}"
        return cols

    m = re.match(r"^(\d{4})-H([12])$", pk)
    if m:
        fy = int(m.group(1))
        h = int(m.group(2))
        half_name = "Apr–Sep" if h == 1 else "Oct–Mar"
        cols.half = f"H{h} ({half_name}) {_fy_label_from_start(fy)}"
        return cols

    if pk.startswith("FY"):
        raw = pk[2:]
        cols.yearly = raw if re.match(r"^\d{4}-\d{2}$", raw) else pk
        return cols

    m = re.match(r"^(\d{4})-(\d{4})$", pk)
    if m:
        y0, y1 = int(m.group(1)), int(m.group(2))
        span = y1 - y0 + 1
        label = f"{_fy_label_from_start(y0)} to {_fy_label_from_start(y1)}"
        if span == 5:
            cols.span_5y = label
        else:
            cols.span_3y = label
        return cols

    if _CYCLE_RE.match(pk):
        cols.span_3y = pk
        return cols

    cols.month = pk
    return cols


def format_next_period(task) -> str:
    master = task.task_master
    if not master.is_recurring or not task.enrollment_id:
        return ""
    try:
        nxt = next_period_key(master, task.period_key, task.enrollment.started_at)
    except Exception:
        return ""
    nxt_cols = format_period_key(nxt)
    for val in (
        nxt_cols.month,
        nxt_cols.quarter,
        nxt_cols.half,
        nxt_cols.yearly,
        nxt_cols.span_3y,
        nxt_cols.span_5y,
    ):
        if val:
            return val
    return nxt
