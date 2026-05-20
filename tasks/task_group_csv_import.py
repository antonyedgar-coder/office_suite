"""Parse and validate bulk Task Group CSV uploads."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from django.core.exceptions import ValidationError

from .models import TaskGroup

TASK_GROUP_CSV_COLUMNS = ["NAME", "SORT_ORDER", "IS_ACTIVE"]


def _upper(v: str) -> str:
    return (v or "").strip().upper()


def _bool_active(v: str) -> bool:
    s = _upper(v)
    if s in {"", "YES", "Y", "TRUE", "1"}:
        return True
    if s in {"NO", "N", "FALSE", "0"}:
        return False
    raise ValueError("IS_ACTIVE must be YES, NO, or blank (defaults to YES).")


@dataclass
class TaskGroupParsedRow:
    row_num: int
    data: dict
    errors: list[str]


def parse_task_groups_csv(csv_bytes: bytes) -> tuple[list[TaskGroupParsedRow], list[str]]:
    file_errors: list[str] = []
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = csv_bytes.decode("cp1252", errors="replace")

    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        return [], ["CSV appears to have no header row."]

    header_map = {_upper(h): h for h in reader.fieldnames}
    if "NAME" not in header_map:
        return [], ["Missing required column: NAME"]

    rows: list[TaskGroupParsedRow] = []
    names_in_file: set[str] = set()

    for i, raw in enumerate(reader, start=2):

        def gv(key: str) -> str:
            orig = header_map.get(key)
            return (raw.get(orig, "") or "").strip() if orig else ""

        errors: list[str] = []
        try:
            is_active = _bool_active(gv("IS_ACTIVE"))
        except ValueError as e:
            rows.append(TaskGroupParsedRow(row_num=i, data={}, errors=[str(e)]))
            continue

        name = (gv("NAME") or "").strip()
        sort_raw = gv("SORT_ORDER")
        sort_order = 0
        if sort_raw:
            try:
                sort_order = int(sort_raw)
                if sort_order < 0:
                    errors.append("SORT_ORDER must be 0 or greater.")
            except ValueError:
                errors.append("SORT_ORDER must be a whole number.")

        cleaned = {"name": name, "sort_order": sort_order, "is_active": is_active}

        if not name:
            errors.append("NAME is required.")
        elif name in names_in_file:
            errors.append(f"Duplicate NAME in file: {name}")
        elif TaskGroup.objects.filter(name__iexact=name).exists():
            errors.append(f"NAME already exists: {name}")

        if not errors and name:
            try:
                TaskGroup(name=name, sort_order=sort_order, is_active=is_active).full_clean()
            except ValidationError as ve:
                if hasattr(ve, "message_dict"):
                    for field, msgs in ve.message_dict.items():
                        for m in msgs:
                            errors.append(f"{field}: {m}")
                else:
                    errors.extend(list(ve.messages))

        if not errors and name:
            names_in_file.add(name)

        rows.append(TaskGroupParsedRow(row_num=i, data=cleaned, errors=errors))

    return rows, file_errors
