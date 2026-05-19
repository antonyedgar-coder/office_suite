"""Build period_key values from user-selected filing period on task create."""

from __future__ import annotations

import re
from datetime import date

from django.core.exceptions import ValidationError
from django.utils import timezone

from dirkyc.fy import fy_start_year

# Earliest FY in New Task period pickers (value = FY start year, label = e.g. 2024-25).
TASK_FIRST_FY_START_YEAR = 2024
# How many FYs ahead of the current FY to show in To FY / period pickers (rolls on each 1 Apr).
TASK_FY_CHOICES_YEARS_AHEAD = 4

PERIOD_ONE_TIME = "one_time"
PERIOD_MONTHLY = "monthly"
PERIOD_QUARTERLY = "quarterly"
PERIOD_HALF_YEARLY = "half_yearly"
PERIOD_YEARLY = "yearly"
PERIOD_EVERY_3_YEARS = "every_3_years"
PERIOD_EVERY_5_YEARS = "every_5_years"

PERIOD_TYPE_CHOICES = [
    (PERIOD_ONE_TIME, "One time"),
    (PERIOD_MONTHLY, "Monthly"),
    (PERIOD_QUARTERLY, "Quarterly"),
    (PERIOD_HALF_YEARLY, "Half yearly"),
    (PERIOD_YEARLY, "Yearly"),
    (PERIOD_EVERY_3_YEARS, "3 years"),
    (PERIOD_EVERY_5_YEARS, "5 years"),
]

# TaskMaster.frequency (recurring) → filing period on new task
MASTER_FREQUENCY_TO_PERIOD_TYPE = {
    "monthly": PERIOD_MONTHLY,
    "quarterly": PERIOD_QUARTERLY,
    "half_yearly": PERIOD_HALF_YEARLY,
    "annually": PERIOD_YEARLY,
    "every_3_years": PERIOD_EVERY_3_YEARS,
    "every_5_years": PERIOD_EVERY_5_YEARS,
}


def period_type_for_task_master(master) -> str | None:
    """Return fixed filing period type when master is recurring with a frequency."""
    if master is None or not getattr(master, "is_recurring", False):
        return None
    freq = (getattr(master, "frequency", None) or "").strip()
    return MASTER_FREQUENCY_TO_PERIOD_TYPE.get(freq)

QUARTER_CHOICES = [
    ("Q1", "Apr–Jun"),
    ("Q2", "Jul–Sep"),
    ("Q3", "Oct–Dec"),
    ("Q4", "Jan–Mar"),
]

HALF_CHOICES = [
    ("H1", "Apr–Sep"),
    ("H2", "Oct–Mar"),
]

_QUARTER_NUM = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}
_HALF_NUM = {"H1": 1, "H2": 2}

import calendar

MONTH_CHOICES = [(i, calendar.month_name[i]) for i in range(1, 13)]


def current_fy_start(*, today: date | None = None) -> int:
    """Indian FY start year containing `today` (rolls forward each 1 April)."""
    return fy_start_year(today or timezone.localdate())


def fy_choice_label(fy_start: int) -> str:
    return f"{fy_start}-{str(fy_start + 1)[-2:]}"


def task_fy_choices_last_start_year(*, today: date | None = None) -> int:
    """Last FY start year in task period dropdowns (current FY + fixed horizon)."""
    today = today or timezone.localdate()
    cur = current_fy_start(today=today)
    return max(cur + TASK_FY_CHOICES_YEARS_AHEAD, TASK_FIRST_FY_START_YEAR)


def task_fy_choices(*, today: date | None = None) -> list[tuple[str, str]]:
    """(value, label) for task create — value is FY start year as string, label e.g. 2026-27."""
    last = task_fy_choices_last_start_year(today=today)
    return [(str(y), fy_choice_label(y)) for y in range(TASK_FIRST_FY_START_YEAR, last + 1)]


def calendar_year_for_fy_month(fy_start: int, month: int) -> int:
    """Map Indian FY + calendar month to the calendar year for YYYY-MM period keys."""
    if month >= 4:
        return fy_start
    return fy_start + 1


def build_period_key(
    period_type: str,
    *,
    month: int | None = None,
    year: int | None = None,
    quarter: str | None = None,
    fy_start: int | None = None,
    half: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> str:
    if period_type == PERIOD_ONE_TIME:
        return "one-time"
    if period_type == PERIOD_MONTHLY:
        if not month:
            raise ValidationError("Month is required for monthly period.")
        if fy_start is not None:
            cal_year = calendar_year_for_fy_month(fy_start, month)
        elif year is not None:
            cal_year = year
        else:
            raise ValidationError("Financial year is required for monthly period.")
        return f"{cal_year}-{month:02d}"
    if period_type == PERIOD_QUARTERLY:
        if not quarter or fy_start is None:
            raise ValidationError("Quarter and FY are required for quarterly period.")
        return f"{fy_start}-Q{_QUARTER_NUM[quarter]}"
    if period_type == PERIOD_HALF_YEARLY:
        if not half or fy_start is None:
            raise ValidationError("Half and FY are required for half-yearly period.")
        return f"{fy_start}-H{_HALF_NUM[half]}"
    if period_type == PERIOD_YEARLY:
        if fy_start is None:
            raise ValidationError("FY is required for yearly period.")
        y2 = (fy_start + 1) % 100
        return f"FY{fy_start}-{y2:02d}"
    if period_type == PERIOD_EVERY_3_YEARS:
        _validate_year_span(year_from, year_to, exact_years=3)
        return f"{year_from}-{year_to}"
    if period_type == PERIOD_EVERY_5_YEARS:
        _validate_year_span(year_from, year_to, max_years=5)
        return f"{year_from}-{year_to}"
    raise ValidationError(f"Unknown period type: {period_type}")


def _validate_year_span(
    year_from: int | None,
    year_to: int | None,
    *,
    exact_years: int | None = None,
    max_years: int | None = None,
) -> None:
    label = exact_years or max_years or 0
    if year_from is None or year_to is None:
        raise ValidationError(f"From year and to year are required for {label}-year period.")
    if year_to < year_from:
        raise ValidationError("To year cannot be before from year.")
    count = year_to - year_from + 1
    if exact_years is not None and count != exact_years:
        raise ValidationError(
            f"Select exactly {exact_years} consecutive financial years (from year through to year)."
        )
    if max_years is not None and (count < 1 or count > max_years):
        raise ValidationError(
            f"Select between 1 and {max_years} consecutive financial years (from year through to year)."
        )


def multi_year_span_key(enrollment_started: date, ref: date, years: int) -> str:
    """FY start years for the multi-year block containing ref (Indian FY)."""
    fy_s = current_fy_start(today=enrollment_started)
    fy_r = current_fy_start(today=ref)
    cycle_index = max(0, (fy_r - fy_s) // years)
    block_start = fy_s + cycle_index * years
    block_end = block_start + years - 1
    return f"{block_start}-{block_end}"


def next_multi_year_span_after_last(
    *,
    client,
    master,
    years: int,
    enrollment_started: date,
    ref: date,
) -> str:
    """Next block after the latest task, or the block containing ref if none."""
    from .models import Task

    last = (
        Task.objects.filter(client=client, task_master=master)
        .exclude(status=Task.STATUS_CANCELLED)
        .order_by("-created_at")
        .first()
    )
    if last and last.period_key:
        pk = last.period_key.strip()
        m = re.match(r"^(\d{4})-(\d{4})$", pk)
        if m:
            next_start = int(m.group(2)) + 1
            return f"{next_start}-{next_start + years - 1}"
        m = re.match(r"^cycle-(\d+)$", pk)
        if m:
            cycle = int(m.group(1))
            fy_s = current_fy_start(today=enrollment_started)
            block_end = fy_s + cycle * years - 1
            next_start = block_end + 1
            return f"{next_start}-{next_start + years - 1}"
    return multi_year_span_key(enrollment_started, ref, years)
