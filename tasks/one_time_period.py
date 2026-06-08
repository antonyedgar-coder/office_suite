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


def is_one_time_task(task) -> bool:
    """Whether a task row represents one-time work (used for period numbering)."""
    pt = (getattr(task, "period_type", None) or "").strip()
    pk = (getattr(task, "period_key", None) or "").strip()
    if pt == PERIOD_ONE_TIME:
        return True
    if is_one_time_period_key(pk):
        return True
    if pk in LEGACY_ONE_TIME_PERIOD_KEYS:
        return True
    master = getattr(task, "task_master", None)
    if master is not None and not getattr(master, "is_recurring", False):
        return True
    return False


def _month_prefix_for_due_date(due_date: date) -> tuple[str, str]:
    fy = fy_label_for_date(due_date)
    ym = due_date.strftime("%Y-%m")
    return f"FY{fy}-{ym}", ym


def _existing_one_time_slots_for_client_master_month(client, master, due_date: date) -> list[str]:
    """
    Period keys already used for this client + task master in the due-date month.
    GST Notice and Digital Signature each have their own sequence in the same month.
    """
    from tasks.models import Task

    if master is None:
        return []

    prefix, ym = _month_prefix_for_due_date(due_date)
    year, month = map(int, ym.split("-"))
    slots: list[str] = []
    qs = (
        Task.objects.filter(
            client=client,
            task_master=master,
            due_date__year=year,
            due_date__month=month,
        )
        .exclude(status=Task.STATUS_CANCELLED)
        .select_related("task_master")
    )
    for task in qs.only("period_key", "period_type", "due_date", "task_master__is_recurring"):
        if not is_one_time_task(task):
            continue
        pk = (task.period_key or "").strip()
        if pk == prefix or pk.startswith(f"{prefix}-"):
            slots.append(pk)
        elif pk in LEGACY_ONE_TIME_PERIOD_KEYS or not is_one_time_period_key(pk):
            slots.append(prefix)
    return slots


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


def allocate_one_time_period_key(
    client,
    master,
    due_date: date,
    *,
    pending_period_keys: set[str] | None = None,
) -> str:
    """
    Next unique one-time period_key for this client, task master, and due-date month.

    Numbering is per client and per task type (task master), then per calendar month.
    First GST Notice in April → April 2026; second GST Notice in April → April 2026 (2).
    First Digital Signature in the same April → April 2026 (separate sequence).
    """
    prefix, _ym = _month_prefix_for_due_date(due_date)
    in_month = _existing_one_time_slots_for_client_master_month(client, master, due_date)
    if pending_period_keys:
        in_month.extend(pk for pk in pending_period_keys if pk == prefix or pk.startswith(f"{prefix}-"))
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


def backfill_one_time_period_keys_for_client(client, *, dry_run: bool = False) -> int:
    """
    Renumber existing one-time tasks for a client: per task master and calendar month.
    Returns number of tasks updated.
    """
    from tasks.models import Task

    tasks = list(
        Task.objects.filter(client=client)
        .exclude(status=Task.STATUS_CANCELLED)
        .select_related("task_master")
        .order_by("due_date", "created_at", "pk")
    )
    one_time = [t for t in tasks if is_one_time_task(t)]
    groups: dict[tuple[int, int, int], list] = {}
    for task in one_time:
        key = (task.task_master_id, task.due_date.year, task.due_date.month)
        groups.setdefault(key, []).append(task)

    updated = 0
    for (_master_id, _year, _month), group in groups.items():
        for seq, task in enumerate(group, start=1):
            new_key = build_one_time_period_key(task.due_date, sequence=seq)
            changes = []
            if task.period_key != new_key:
                changes.append("period_key")
                if not dry_run:
                    task.period_key = new_key
            if task.period_type != PERIOD_ONE_TIME:
                changes.append("period_type")
                if not dry_run:
                    task.period_type = PERIOD_ONE_TIME
            if changes and not dry_run:
                task.save(update_fields=changes)
            if changes:
                updated += 1
    return updated


def one_time_period_from_due_date(due_date: date, *, period_key: str = "") -> tuple[str, str]:
    """Document period tuple for a one-time task."""
    parsed = parse_one_time_period_key(period_key) if period_key else None
    if parsed:
        return period_key.strip(), str(parsed["month_label"])
    pk = build_one_time_period_key(due_date)
    return pk, calendar.month_name[due_date.month]
