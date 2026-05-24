"""One-time task period keys and filenames derived from due date."""

from __future__ import annotations

import calendar
import re
from datetime import date

from dirkyc.fy import fy_label_for_date

PERIOD_ONE_TIME = "one_time"
LEGACY_ONE_TIME_PERIOD_KEYS = frozenset({"one-time", "once", ""})

_ONE_TIME_PERIOD_KEY_RE = re.compile(
    r"^FY(?P<fy>\d{4}-\d{2})-(?P<ym>\d{4}-\d{2})(?:-(?P<seq>\d+))?$"
)


def is_one_time_period_key(period_key: str) -> bool:
    pk = (period_key or "").strip()
    if pk in LEGACY_ONE_TIME_PERIOD_KEYS:
        return False
    return bool(_ONE_TIME_PERIOD_KEY_RE.match(pk))


def build_one_time_period_key(due_date: date, *, sequence: int = 1) -> str:
    """Build stored period_key for a one-time task from its due date."""
    fy = fy_label_for_date(due_date)
    ym = due_date.strftime("%Y-%m")
    base = f"FY{fy}-{ym}"
    if sequence <= 1:
        return base
    return f"{base}-{sequence}"


def parse_one_time_period_key(period_key: str) -> dict[str, str | int] | None:
    pk = (period_key or "").strip()
    m = _ONE_TIME_PERIOD_KEY_RE.match(pk)
    if not m:
        return None
    ym = m.group("ym")
    y, mo = map(int, ym.split("-"))
    seq = int(m.group("seq") or 1)
    return {
        "fy": m.group("fy"),
        "ym": ym,
        "sequence": seq,
        "month_label": calendar.month_name[mo],
        "month_abbr": calendar.month_abbr[mo],
    }


def allocate_one_time_period_key(client, master, due_date: date) -> str:
    """
    Next unique one-time period_key for client + task master + due-date month.
    First task in a month has no suffix; further tasks use -2, -3, …
    """
    from tasks.models import Task

    fy = fy_label_for_date(due_date)
    ym = due_date.strftime("%Y-%m")
    prefix = f"FY{fy}-{ym}"
    existing = list(
        Task.objects.filter(client=client, task_master=master)
        .exclude(status=Task.STATUS_CANCELLED)
        .values_list("period_key", flat=True)
    )
    in_month = [pk for pk in existing if pk == prefix or pk.startswith(f"{prefix}-")]
    if not in_month:
        return prefix
    max_seq = 1
    for pk in in_month:
        if pk == prefix:
            max_seq = max(max_seq, 1)
            continue
        m = re.match(rf"^{re.escape(prefix)}-(\d+)$", pk)
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    return build_one_time_period_key(due_date, sequence=max_seq + 1)


def one_time_period_from_due_date(due_date: date, *, period_key: str = "") -> tuple[str, str]:
    """Document period tuple for a one-time task."""
    parsed = parse_one_time_period_key(period_key) if period_key else None
    if parsed:
        return period_key.strip(), str(parsed["month_label"])
    pk = build_one_time_period_key(due_date)
    return pk, calendar.month_name[due_date.month]
