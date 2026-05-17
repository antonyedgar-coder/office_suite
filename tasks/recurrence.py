"""
Recurrence period keys and create/due date calculation (Indian FY: Apr–Mar).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tasks.models import TaskMaster

# Indian FY quarters within calendar year mapping
# Q1 Apr-Jun, Q2 Jul-Sep, Q3 Oct-Dec, Q4 Jan-Mar
_QUARTER_MONTHS = {
    1: 4,  # Q1 starts April
    2: 7,
    3: 10,
    4: 1,  # Q4 starts January (next calendar year in FY)
}


def fy_start_year(d: date) -> int:
    """FY label year: FY 2025-26 → 2025 (April 2025 – March 2026)."""
    return d.year if d.month >= 4 else d.year - 1


def fy_label(d: date) -> str:
    y = fy_start_year(d)
    return f"FY{y}-{str(y + 1)[-2:]}"


def _clamp_day(year: int, month: int, day: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def quarter_for_date(d: date) -> tuple[int, int]:
    """Return (fy_start_year, quarter 1-4) for Indian FY."""
    if d.month >= 4:
        q = (d.month - 4) // 3 + 1
        return fy_start_year(d), q
    return fy_start_year(d), 4


def half_for_date(d: date) -> tuple[int, int]:
    """Return (fy_start_year, half 1 or 2). H1 Apr-Sep, H2 Oct-Mar."""
    if d.month >= 4:
        return fy_start_year(d), 1 if d.month <= 9 else 2
    return fy_start_year(d), 2


def period_key_for_date(master: TaskMaster, d: date, enrollment_started: date) -> str:
    freq = master.frequency
    if freq == master.FREQ_MONTHLY:
        return d.strftime("%Y-%m")
    if freq == master.FREQ_QUARTERLY:
        fy, q = quarter_for_date(d)
        return f"{fy}-Q{q}"
    if freq == master.FREQ_HALF_YEARLY:
        fy, h = half_for_date(d)
        return f"{fy}-H{h}"
    if freq == master.FREQ_ANNUALLY:
        return fy_label(d)
    years = 3 if freq == master.FREQ_EVERY_3_YEARS else 5
    cycle = _multi_year_cycle(enrollment_started, d, years)
    return f"cycle-{cycle}"


def _multi_year_cycle(started: date, ref: date, years: int) -> int:
    """1-based cycle number from enrollment start."""
    fy_s = fy_start_year(started)
    fy_r = fy_start_year(ref)
    elapsed = fy_r - fy_s
    return max(1, elapsed // years + 1)


def _anchor_month_quarter(fy: int, q: int, anchor: str) -> tuple[int, int]:
    """Return (year, month) for create anchor in quarter q of FY starting fy."""
    if q == 4:
        months = [1, 2, 3]
        base_year = fy + 1
    else:
        months = [_QUARTER_MONTHS[q] + i for i in range(3)]
        base_year = fy if q > 1 or months[0] >= 4 else fy
        if q == 1:
            base_year = fy
    if anchor == "first_month_same_qtr":
        m = months[0]
        y = fy + 1 if m < 4 else fy
        if q == 1:
            y = fy
        elif q == 2:
            y = fy
        elif q == 3:
            y = fy
        else:
            y = fy + 1
        return y, m
    if anchor == "last_month_same_qtr":
        m = months[-1]
        y = fy + 1 if m < 4 else fy
        return y, m
    # first_month_next_qtr
    nq = q + 1 if q < 4 else 1
    return _anchor_month_quarter(fy, nq, "first_month_same_qtr")


def _anchor_month_half(fy: int, half: int, anchor: str) -> tuple[int, int]:
    if half == 1:
        months = [4, 5, 6, 7, 8, 9]
        base_y = fy
    else:
        months = [10, 11, 12, 1, 2, 3]
        base_y = fy
    if anchor == "first_month_same_half":
        m = months[0]
        y = fy if m >= 4 else fy + 1
        return y, m
    if anchor == "last_month_same_half":
        m = months[-1]
        y = fy if m >= 4 else fy + 1
        return y, m
    nh = 2 if half == 1 else 1
    return _anchor_month_half(fy, nh, "first_month_same_half")


def _parse_period_key(master: TaskMaster, period_key: str, enrollment_started: date) -> date:
    """Reference date inside the period (mid-period) for date calculations."""
    freq = master.frequency
    if freq == master.FREQ_MONTHLY:
        y, m = map(int, period_key.split("-"))
        return date(y, m, 15)
    if freq == master.FREQ_QUARTERLY:
        fy = int(period_key.split("-")[0])
        q = int(period_key.split("Q")[1])
        y, m = _anchor_month_quarter(fy, q, "first_month_same_qtr")
        return date(y, m, 15)
    if freq == master.FREQ_HALF_YEARLY:
        fy = int(period_key.split("-")[0])
        h = int(period_key.split("H")[1])
        y, m = _anchor_month_half(fy, h, "first_month_same_half")
        return date(y, m, 15)
    if freq == master.FREQ_ANNUALLY:
        if period_key.startswith("FY"):
            y = int(period_key[2:].split("-")[0])
            return date(y, 6, 15)
        return date(int(period_key), 6, 15)
    cycle = int(period_key.replace("cycle-", ""))
    years = 3 if freq == master.FREQ_EVERY_3_YEARS else 5
    fy = fy_start_year(enrollment_started) + (cycle - 1) * years
    return date(fy, 4, 15)


def compute_create_due_dates(
    master: TaskMaster,
    period_key: str,
    enrollment_started: date,
) -> tuple[date, date]:
    cfg = master.recurrence_config or {}
    ref = _parse_period_key(master, period_key, enrollment_started)
    freq = master.frequency

    if freq == master.FREQ_MONTHLY:
        y, m = ref.year, ref.month
        create_d = _clamp_day(y, m, cfg["create_day"])
        if cfg["month_anchor"] == "subsequent_month":
            due_m = m + 1
            due_y = y
            if due_m > 12:
                due_m = 1
                due_y += 1
            due_d = _clamp_day(due_y, due_m, cfg["due_day"])
        else:
            due_d = _clamp_day(y, m, cfg["due_day"])
        return create_d, due_d

    if freq == master.FREQ_QUARTERLY:
        fy, q = quarter_for_date(ref)
        cy, cm = _anchor_month_quarter(fy, q, cfg["quarter_anchor"])
        create_d = _clamp_day(cy, cm, cfg["create_day"])
        due_d = _clamp_day(cy, cm, cfg["due_day"])
        return create_d, due_d

    if freq == master.FREQ_HALF_YEARLY:
        fy, h = half_for_date(ref)
        cy, cm = _anchor_month_half(fy, h, cfg["half_anchor"])
        create_d = _clamp_day(cy, cm, cfg["create_day"])
        due_d = _clamp_day(cy, cm, cfg["due_day"])
        return create_d, due_d

    if freq == master.FREQ_ANNUALLY:
        month = cfg["month"]
        fy = fy_start_year(ref)
        if cfg["fy_anchor"] == "next_fy":
            anchor_fy = fy + 1
        else:
            anchor_fy = fy
        y = anchor_fy if month >= 4 else anchor_fy + 1
        create_d = _clamp_day(y, month, cfg["create_day"])
        due_d = _clamp_day(y, month, cfg["due_day"])
        return create_d, due_d

    years = 3 if freq == master.FREQ_EVERY_3_YEARS else 5
    cycle = _multi_year_cycle(enrollment_started, ref, years)
    completion_fy = fy_start_year(enrollment_started) + cycle * years
    create_y = completion_fy + 1 if cfg["create_month"] < 4 else completion_fy
    due_y = completion_fy + 1 if cfg["due_month"] < 4 else completion_fy
    create_d = _clamp_day(create_y, cfg["create_month"], cfg["create_day"])
    due_d = _clamp_day(due_y, cfg["due_month"], cfg["due_day"])
    return create_d, due_d


def should_create_today(master: TaskMaster, today: date, enrollment_started: date) -> tuple[bool, str]:
    """Return (should_create, period_key) if today is the scheduled create date."""
    pk = period_key_for_date(master, today, enrollment_started)
    create_d, _ = compute_create_due_dates(master, pk, enrollment_started)
    if create_d == today:
        return True, pk
    return False, pk


def next_period_key(master: TaskMaster, current_period_key: str, enrollment_started: date) -> str:
    ref = _parse_period_key(master, current_period_key, enrollment_started)
    freq = master.frequency
    if freq == master.FREQ_MONTHLY:
        y, m = ref.year, ref.month
        m += 1
        if m > 12:
            m = 1
            y += 1
        return date(y, m, 1).strftime("%Y-%m")
    if freq == master.FREQ_QUARTERLY:
        fy, q = quarter_for_date(ref)
        if q == 4:
            return f"{fy + 1}-Q1"
        return f"{fy}-Q{q + 1}"
    if freq == master.FREQ_HALF_YEARLY:
        fy, h = half_for_date(ref)
        if h == 2:
            return f"{fy + 1}-H1"
        return f"{fy}-H2"
    if freq == master.FREQ_ANNUALLY:
        y = fy_start_year(ref) + 1
        return f"FY{y}-{str(y + 1)[-2:]}"
    years = 3 if freq == master.FREQ_EVERY_3_YEARS else 5
    cycle = _multi_year_cycle(enrollment_started, ref, years)
    return f"cycle-{cycle + 1}"


def first_period_key(master: TaskMaster, enrollment_started: date) -> str:
    return period_key_for_date(master, enrollment_started, enrollment_started)
