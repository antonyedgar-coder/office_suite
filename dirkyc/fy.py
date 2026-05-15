"""
Indian financial year (April–March) helpers for DIR-3 / DIR e-KYC cadence.

Cadence (by FY, not by rolling years from the calendar date):
- The FY of a date is determined by the April that starts that FY
  (e.g. 01-04-2026 and 30-06-2026 are both in FY 2026-27).
- After a filing in FY starting year Y, the **next** e-KYC may be recorded only from
  **01-April** of calendar year **Y + 3** (the opening day of the 4th FY after that FY).
  Example: any filing in FY 2026-27 → next allowed from **01-04-2029** (FY 2029-30).
"""

from __future__ import annotations

from datetime import date


def fy_start_year(d: date) -> int:
    """First calendar year of the Indian FY containing date `d` (April of that year)."""
    if d.month >= 4:
        return d.year
    return d.year - 1


def fy_label_for_date(d: date) -> str:
    y = fy_start_year(d)
    return f"{y}-{str(y + 1)[-2:]}"


def earliest_next_dirkyc_allowed_date(last_done_date: date) -> date:
    """
    First calendar date on which another DIR-3 e-KYC may be filed after `last_done_date`,
    based only on the FY of `last_done_date` (same rule for 01-04 and 30-06 in that FY).
    """
    y0 = fy_start_year(last_done_date)
    return date(y0 + 3, 4, 1)


def next_allowed_fy_label_for_done_date(done_date: date) -> str:
    """FY label for the FY in which the next filing is first allowed (starts 01-Apr)."""
    return fy_label_for_date(earliest_next_dirkyc_allowed_date(done_date))


def fy_label_to_date_range(fy_label: str) -> tuple[date, date] | None:
    """
    Parse an Indian FY label like '2026-27' to inclusive calendar bounds
    (01-Apr of first year through 31-Mar of next year).
    """
    s = (fy_label or "").strip()
    parts = s.split("-", 1)
    if len(parts) != 2 or len(parts[1]) != 2 or not parts[1].isdigit():
        return None
    try:
        y0 = int(parts[0])
    except ValueError:
        return None
    y1 = y0 + 1
    if parts[1] != str(y1)[-2:]:
        return None
    return date(y0, 4, 1), date(y1, 3, 31)


# MIS Report (month-wise): earliest FY in the picker. New FYs append each 1 April via fy_start_year().
MIS_REPORT_FIRST_FY_START_YEAR = 2026


def mis_report_financial_year_start_years(*, today: date) -> list[int]:
    """
    Indian FY start years shown in MIS Report month-wise multi-select.
    From MIS_REPORT_FIRST_FY_START_YEAR through the FY containing `today` (inclusive).
    """
    cur_start = fy_start_year(today)
    last = max(cur_start, MIS_REPORT_FIRST_FY_START_YEAR)
    return list(range(MIS_REPORT_FIRST_FY_START_YEAR, last + 1))


def mis_report_financial_year_choices(*, today: date) -> list[tuple[str, str]]:
    """(value, label) pairs like ('2026-27', '2026-27') for the MIS Report FY dropdown."""
    return [(f"{y}-{str(y + 1)[-2:]}", f"{y}-{str(y + 1)[-2:]}") for y in mis_report_financial_year_start_years(today=today)]
