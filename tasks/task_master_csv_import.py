"""Parse and validate bulk Task Master CSV uploads."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from .models import TaskGroup, TaskMaster
from .recurrence_config import validate_recurrence_config

TASK_MASTER_CSV_COLUMNS = [
    "TASK_GROUP",
    "NAME",
    "DESCRIPTION",
    "DEFAULT_PRIORITY",
    "IS_ACTIVE",
    "IS_RECURRING",
    "FREQUENCY",
    "DEFAULT_FEES_AMOUNT",
    "CHECKLIST_ITEMS",
    "RECURRENCE_CONFIG_JSON",
]


def _upper(v: str) -> str:
    return (v or "").strip().upper()


def _bool_active(v: str) -> bool:
    s = _upper(v)
    if s in {"", "YES", "Y", "TRUE", "1"}:
        return True
    if s in {"NO", "N", "FALSE", "0"}:
        return False
    raise ValueError("IS_ACTIVE must be YES, NO, or blank (defaults to YES).")


def _bool_yes(v: str, *, field: str) -> bool:
    s = _upper(v)
    if s in {"", "NO", "N", "FALSE", "0"}:
        return False
    if s in {"YES", "Y", "TRUE", "1"}:
        return True
    raise ValueError(f"{field} must be YES, NO, or blank (defaults to NO).")


@dataclass
class TaskMasterParsedRow:
    row_num: int
    data: dict
    errors: list[str]


def _resolve_task_group(name: str) -> TaskGroup | None:
    return TaskGroup.objects.filter(name__iexact=(name or "").strip()).first()


def parse_task_masters_csv(csv_bytes: bytes) -> tuple[list[TaskMasterParsedRow], list[str]]:
    file_errors: list[str] = []
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = csv_bytes.decode("cp1252", errors="replace")

    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        return [], ["CSV appears to have no header row."]

    header_map = {_upper(h): h for h in reader.fieldnames}
    for req in ("TASK_GROUP", "NAME"):
        if req not in header_map:
            return [], [f"Missing required column: {req}"]

    valid_priorities = {c[0] for c in TaskMaster.PRIORITY_CHOICES}
    valid_frequencies = {c[0] for c in TaskMaster.FREQUENCY_CHOICES}
    rows: list[TaskMasterParsedRow] = []
    keys_in_file: set[tuple[int, str]] = set()

    for i, raw in enumerate(reader, start=2):

        def gv(key: str) -> str:
            orig = header_map.get(key)
            return (raw.get(orig, "") or "").strip() if orig else ""

        errors: list[str] = []
        try:
            is_active = _bool_active(gv("IS_ACTIVE"))
            is_recurring = _bool_yes(gv("IS_RECURRING"), field="IS_RECURRING")
        except ValueError as e:
            rows.append(TaskMasterParsedRow(row_num=i, data={}, errors=[str(e)]))
            continue

        group_name = gv("TASK_GROUP")
        name = gv("NAME")
        description = gv("DESCRIPTION")
        priority = (gv("DEFAULT_PRIORITY") or TaskMaster.PRIORITY_NORMAL).lower()
        frequency = (gv("FREQUENCY") or "").lower().replace(" ", "_")
        checklist_raw = gv("CHECKLIST_ITEMS")
        recurrence_json_raw = gv("RECURRENCE_CONFIG_JSON")

        group = _resolve_task_group(group_name) if group_name else None
        if not group_name:
            errors.append("TASK_GROUP is required.")
        elif not group:
            errors.append(f"TASK_GROUP not found: {group_name}")

        if not name:
            errors.append("NAME is required.")

        if priority not in valid_priorities:
            errors.append(f"DEFAULT_PRIORITY must be one of: {', '.join(sorted(valid_priorities))}.")

        default_fees = None
        if fees_raw:
            try:
                default_fees = Decimal(fees_raw.replace(",", ""))
                if default_fees < 0:
                    errors.append("DEFAULT_FEES_AMOUNT cannot be negative.")
            except InvalidOperation:
                errors.append("DEFAULT_FEES_AMOUNT must be a number.")

        checklist_items: list[str] = []
        if checklist_raw:
            checklist_items = [p.strip() for p in checklist_raw.replace(";", "|").split("|") if p.strip()]

        recurrence_config: dict = {}
        if is_recurring:
            if not frequency:
                errors.append("FREQUENCY is required when IS_RECURRING is YES.")
            elif frequency not in valid_frequencies:
                errors.append(f"FREQUENCY must be one of: {', '.join(sorted(valid_frequencies))}.")
            if recurrence_json_raw:
                try:
                    recurrence_config = json.loads(recurrence_json_raw)
                    if not isinstance(recurrence_config, dict):
                        errors.append("RECURRENCE_CONFIG_JSON must be a JSON object.")
                except json.JSONDecodeError:
                    errors.append("RECURRENCE_CONFIG_JSON is not valid JSON.")
            else:
                errors.append(
                    "RECURRENCE_CONFIG_JSON is required when IS_RECURRING is YES "
                    "(copy structure from an existing recurring master in the UI)."
                )
            if frequency and recurrence_config and not errors:
                try:
                    validate_recurrence_config(frequency, recurrence_config)
                except ValidationError as ve:
                    if hasattr(ve, "message_dict"):
                        for msgs in ve.message_dict.values():
                            for m in msgs:
                                errors.append(str(m))
                    else:
                        errors.extend(list(ve.messages))
        else:
            frequency = ""
            recurrence_config = {}

        if group and name:
            file_key = (group.pk, name.lower())
            if file_key in keys_in_file:
                errors.append(f"Duplicate TASK_GROUP + NAME in file: {group_name} | {name}")
            elif TaskMaster.objects.filter(task_group=group, name__iexact=name).exists():
                errors.append(f"Task master already exists: {group_name} | {name}")

        cleaned = {
            "task_group": group,
            "name": name,
            "description": description,
            "default_priority": priority,
            "is_active": is_active,
            "is_recurring": is_recurring,
            "frequency": frequency,
            "checklist_items": checklist_items,
            "recurrence_config": recurrence_config,
        }

        if not errors and group and name:
            try:
                obj = TaskMaster(
                    task_group=group,
                    name=name,
                    description=description,
                    default_priority=priority,
                    is_active=is_active,
                    is_recurring=is_recurring,
                    frequency=frequency,
                    recurrence_config=recurrence_config if is_recurring else {},
                )
                obj.full_clean()
            except ValidationError as ve:
                if hasattr(ve, "message_dict"):
                    for field, msgs in ve.message_dict.items():
                        for m in msgs:
                            errors.append(f"{field}: {m}")
                else:
                    errors.extend(list(ve.messages))

        if not errors and group and name:
            keys_in_file.add((group.pk, name.lower()))

        rows.append(TaskMasterParsedRow(row_num=i, data=cleaned, errors=errors))

    return rows, file_errors
