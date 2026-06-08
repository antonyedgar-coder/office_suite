"""Filing-period intervals and overlap checks for duplicate task prevention."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

from django.core.exceptions import ValidationError

from .models import Task, TaskMaster
from .one_time_period import is_one_time_period_key
from .period_keys import (
    PERIOD_EVERY_3_YEARS,
    PERIOD_EVERY_5_YEARS,
    PERIOD_HALF_YEARLY,
    PERIOD_MONTHLY,
    PERIOD_ONE_TIME,
    PERIOD_QUARTERLY,
    PERIOD_YEARLY,
    fy_choice_label,
)

_CYCLE_RE = re.compile(r"^cycle-(\d+)$")
_YEAR_SPAN_RE = re.compile(r"^(\d{4})-(\d{4})$")


@dataclass(frozen=True)
class PeriodInterval:
    start: date
    end: date

    def overlaps(self, other: PeriodInterval) -> bool:
        return self.start <= other.end and other.start <= self.end


def _month_bounds(year: int, month: int) -> PeriodInterval:
    last = calendar.monthrange(year, month)[1]
    return PeriodInterval(date(year, month, 1), date(year, month, last))


def _quarter_bounds(fy_start: int, quarter: int) -> PeriodInterval:
    if quarter == 1:
        return PeriodInterval(date(fy_start, 4, 1), date(fy_start, 6, 30))
    if quarter == 2:
        return PeriodInterval(date(fy_start, 7, 1), date(fy_start, 9, 30))
    if quarter == 3:
        return PeriodInterval(date(fy_start, 10, 1), date(fy_start, 12, 31))
    return PeriodInterval(date(fy_start + 1, 1, 1), date(fy_start + 1, 3, 31))


def _half_bounds(fy_start: int, half: int) -> PeriodInterval:
    if half == 1:
        return PeriodInterval(date(fy_start, 4, 1), date(fy_start, 9, 30))
    return PeriodInterval(date(fy_start, 10, 1), date(fy_start + 1, 3, 31))


def _fy_bounds(fy_start: int) -> PeriodInterval:
    return PeriodInterval(date(fy_start, 4, 1), date(fy_start + 1, 3, 31))


def _fy_span_bounds(year_from: int, year_to: int) -> PeriodInterval:
    """Inclusive Indian FY start years (year_from … year_to) → Apr year_from through Mar year_to+1."""
    return PeriodInterval(date(year_from, 4, 1), date(year_to + 1, 3, 31))


def _cycle_to_fy_span(
    cycle: int,
    years: int,
    enrollment_started: date,
) -> tuple[int, int]:
    from .period_keys import current_fy_start

    fy_s = current_fy_start(today=enrollment_started)
    block_start = fy_s + (cycle - 1) * years
    block_end = block_start + years - 1
    return block_start, block_end


def period_interval(
    period_type: str,
    period_key: str,
    *,
    enrollment_started: date | None = None,
    master: TaskMaster | None = None,
) -> PeriodInterval | None:
    pk = (period_key or "").strip()
    pt = (period_type or "").strip()
    if not pk or pt == PERIOD_ONE_TIME or pk == "one-time" or is_one_time_period_key(pk):
        return None

    if pt == PERIOD_MONTHLY and len(pk) == 7 and pk[4] == "-":
        y, m = int(pk[:4]), int(pk[5:7])
        return _month_bounds(y, m)

    if pt == PERIOD_QUARTERLY and "Q" in pk:
        fy = int(pk.split("-")[0])
        q = int(pk.split("Q")[1])
        return _quarter_bounds(fy, q)

    if pt == PERIOD_HALF_YEARLY and "H" in pk:
        fy = int(pk.split("-")[0])
        h = int(pk.split("H")[1])
        return _half_bounds(fy, h)

    if pt == PERIOD_YEARLY:
        if pk.startswith("FY"):
            y = int(pk[2:].split("-")[0])
            return _fy_bounds(y)
        if pk.isdigit():
            return _fy_bounds(int(pk))

    m = _YEAR_SPAN_RE.match(pk)
    if m and pt in (PERIOD_EVERY_3_YEARS, PERIOD_EVERY_5_YEARS):
        return _fy_span_bounds(int(m.group(1)), int(m.group(2)))

    m = _CYCLE_RE.match(pk)
    if m and master and enrollment_started:
        cycle = int(m.group(1))
        years = 3 if master.frequency == TaskMaster.FREQ_EVERY_3_YEARS else 5
        y_from, y_to = _cycle_to_fy_span(cycle, years, enrollment_started)
        return _fy_span_bounds(y_from, y_to)

    return None


def find_overlapping_task(
    *,
    client,
    master: TaskMaster,
    period_type: str,
    period_key: str,
    enrollment_started: date | None = None,
    exclude_task_id: int | None = None,
) -> Task | None:
    pt = (period_type or "").strip()
    if pt == PERIOD_ONE_TIME or is_one_time_period_key(period_key):
        return None

    new_iv = period_interval(
        period_type,
        period_key,
        enrollment_started=enrollment_started,
        master=master,
    )
    if new_iv is None:
        qs = Task.objects.filter(
            client=client,
            task_master=master,
            period_key=period_key,
        ).exclude(status=Task.STATUS_CANCELLED)
        if exclude_task_id:
            qs = qs.exclude(pk=exclude_task_id)
        return qs.first()

    qs = Task.objects.filter(client=client, task_master=master).exclude(
        status=Task.STATUS_CANCELLED
    )
    if exclude_task_id:
        qs = qs.exclude(pk=exclude_task_id)

    for task in qs.only("pk", "period_key", "period_type", "enrollment_id"):
        enr_started = enrollment_started
        if task.enrollment_id and enr_started is None:
            from .models import TaskRecurrenceEnrollment

            enr = TaskRecurrenceEnrollment.objects.filter(pk=task.enrollment_id).first()
            if enr:
                enr_started = enr.started_at
        other_iv = period_interval(
            task.period_type or period_type,
            task.period_key,
            enrollment_started=enr_started,
            master=master,
        )
        if other_iv and new_iv.overlaps(other_iv):
            return task
    return None


def overlap_error_message(
    *,
    period_type: str,
    period_key: str,
    existing: Task,
) -> str:
    iv = period_interval(period_type, period_key)
    if iv and period_type == PERIOD_MONTHLY:
        return (
            f"A task for this client and task master already exists for "
            f"{calendar.month_name[iv.start.month]} {iv.start.year}."
        )
    if iv and period_type == PERIOD_QUARTERLY:
        return (
            "A task for this client and task master already exists for that quarter "
            f"({existing.period_key})."
        )
    if iv and period_type == PERIOD_HALF_YEARLY:
        return (
            "A task for this client and task master already exists for that half-year "
            f"({existing.period_key})."
        )
    if iv and period_type == PERIOD_YEARLY:
        return (
            f"A task for this client and task master already exists for FY "
            f"{fy_choice_label(iv.start.year if iv.start.month >= 4 else iv.start.year - 1)}."
        )
    if iv and period_type in (PERIOD_EVERY_3_YEARS, PERIOD_EVERY_5_YEARS):
        next_eligible = iv.end + timedelta(days=1)
        return (
            "A task for this client and task master already exists for an overlapping "
            f"multi-year period ({existing.period_key}). "
            f"The next period can start on {next_eligible:%d-%m-%Y} or later."
        )
    return (
        "A task for this client, task master, and filing period already exists "
        f"({existing.period_key})."
    )


def validate_no_overlapping_task(
    *,
    client,
    master: TaskMaster,
    period_type: str,
    period_key: str,
    enrollment_started: date | None = None,
) -> None:
    existing = find_overlapping_task(
        client=client,
        master=master,
        period_type=period_type,
        period_key=period_key,
        enrollment_started=enrollment_started,
    )
    if existing:
        raise ValidationError(
            overlap_error_message(
                period_type=period_type,
                period_key=period_key,
                existing=existing,
            )
        )
