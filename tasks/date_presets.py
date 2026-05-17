"""Date range presets for task list / report filters."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from django.utils import timezone
from django.utils.dateparse import parse_date

from dirkyc.fy import fy_start_year

PRESET_ALL_TIME = "all_time"
PRESET_LAST_MONTH = "last_month"
PRESET_THIS_MONTH = "this_month"
PRESET_LAST_FY = "last_fy"
PRESET_THIS_FY = "this_fy"
PRESET_CUSTOM = "custom"

DATE_PRESET_CHOICES = [
    (PRESET_ALL_TIME, "All time"),
    (PRESET_LAST_MONTH, "Last month"),
    (PRESET_THIS_MONTH, "This month"),
    (PRESET_LAST_FY, "Last FY (Apr–Mar)"),
    (PRESET_THIS_FY, "This FY (Apr–today)"),
    (PRESET_CUSTOM, "Custom"),
]


def resolve_date_preset(
    preset: str,
    custom_from: str = "",
    custom_to: str = "",
    *,
    today: date | None = None,
) -> tuple[date | None, date | None]:
    """Return inclusive from/to dates for a preset. All time → (None, None)."""
    preset = (preset or PRESET_ALL_TIME).strip()
    today = today or timezone.localdate()

    if preset == PRESET_ALL_TIME:
        return None, None

    if preset == PRESET_LAST_MONTH:
        if today.month == 1:
            y, m = today.year - 1, 12
        else:
            y, m = today.year, today.month - 1
        last_day = monthrange(y, m)[1]
        return date(y, m, 1), date(y, m, last_day)

    if preset == PRESET_THIS_MONTH:
        last_day = monthrange(today.year, today.month)[1]
        return date(today.year, today.month, 1), min(today, date(today.year, today.month, last_day))

    if preset == PRESET_LAST_FY:
        fy = fy_start_year(today) - 1
        return date(fy, 4, 1), date(fy + 1, 3, 31)

    if preset == PRESET_THIS_FY:
        fy = fy_start_year(today)
        return date(fy, 4, 1), today

    return parse_date(custom_from or ""), parse_date(custom_to or "")


def preset_to_query_strings(
    preset: str,
    custom_from: str = "",
    custom_to: str = "",
    *,
    today: date | None = None,
) -> tuple[str, str, str]:
    """Return (preset, from_iso, to_iso) for templates and query strings."""
    d_from, d_to = resolve_date_preset(preset, custom_from, custom_to, today=today)
    if preset != PRESET_CUSTOM:
        return preset, d_from.isoformat() if d_from else "", d_to.isoformat() if d_to else ""
    return preset, (custom_from or "").strip(), (custom_to or "").strip()
