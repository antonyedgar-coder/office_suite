"""Validate recurrence_config JSON per TaskMaster frequency."""

from __future__ import annotations

from django.core.exceptions import ValidationError


def _require_keys(data: dict, keys: tuple[str, ...], label: str) -> None:
    missing = [k for k in keys if k not in data]
    if missing:
        raise ValidationError({label: f"Missing keys: {', '.join(missing)}"})


def _day_field(value, field: str) -> None:
    if not isinstance(value, int) or value < 1 or value > 31:
        raise ValidationError({field: "Must be an integer day between 1 and 31."})


def _month_field(value, field: str) -> None:
    if not isinstance(value, int) or value < 1 or value > 12:
        raise ValidationError({field: "Must be an integer month between 1 and 12."})


def validate_recurrence_config(frequency: str, data: dict) -> None:
    if not isinstance(data, dict):
        raise ValidationError("recurrence_config must be a JSON object.")

    if frequency == "monthly":
        _require_keys(data, ("month_anchor", "create_day", "due_day"), "recurrence_config")
        if data["month_anchor"] not in ("same_month", "subsequent_month"):
            raise ValidationError({"month_anchor": "Must be same_month or subsequent_month."})
        _day_field(data["create_day"], "create_day")
        _day_field(data["due_day"], "due_day")

    elif frequency == "quarterly":
        _require_keys(data, ("quarter_anchor", "create_day", "due_day"), "recurrence_config")
        if data["quarter_anchor"] not in (
            "first_month_same_qtr",
            "last_month_same_qtr",
            "first_month_next_qtr",
        ):
            raise ValidationError({"quarter_anchor": "Invalid quarter anchor."})
        _day_field(data["create_day"], "create_day")
        _day_field(data["due_day"], "due_day")

    elif frequency == "half_yearly":
        _require_keys(data, ("half_anchor", "create_day", "due_day"), "recurrence_config")
        if data["half_anchor"] not in (
            "first_month_same_half",
            "last_month_same_half",
            "first_month_next_half",
        ):
            raise ValidationError({"half_anchor": "Invalid half-year anchor."})
        _day_field(data["create_day"], "create_day")
        _day_field(data["due_day"], "due_day")

    elif frequency == "annually":
        _require_keys(data, ("fy_anchor", "month", "create_day", "due_day"), "recurrence_config")
        if data["fy_anchor"] not in ("same_fy", "next_fy"):
            raise ValidationError({"fy_anchor": "Must be same_fy or next_fy."})
        _month_field(data["month"], "month")
        _day_field(data["create_day"], "create_day")
        _day_field(data["due_day"], "due_day")

    elif frequency in ("every_3_years", "every_5_years"):
        _require_keys(
            data,
            ("create_month", "create_day", "due_month", "due_day"),
            "recurrence_config",
        )
        _month_field(data["create_month"], "create_month")
        _day_field(data["create_day"], "create_day")
        _month_field(data["due_month"], "due_month")
        _day_field(data["due_day"], "due_day")
    else:
        raise ValidationError({"frequency": f"Unknown frequency: {frequency}"})
