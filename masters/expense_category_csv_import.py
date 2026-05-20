"""Parse and validate bulk Expense Category CSV uploads."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from django.core.exceptions import ValidationError

from .models import ExpenseCategory

EXPENSE_CATEGORY_CSV_COLUMNS = ["NAME", "IS_ACTIVE"]


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
class ExpenseCategoryParsedRow:
    row_num: int
    data: dict
    errors: list[str]


def parse_expense_categories_csv(csv_bytes: bytes) -> tuple[list[ExpenseCategoryParsedRow], list[str]]:
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

    rows: list[ExpenseCategoryParsedRow] = []
    names_in_file: set[str] = set()

    for i, raw in enumerate(reader, start=2):

        def gv(key: str) -> str:
            orig = header_map.get(key)
            return (raw.get(orig, "") or "").strip() if orig else ""

        errors: list[str] = []
        try:
            is_active = _bool_active(gv("IS_ACTIVE"))
        except ValueError as e:
            rows.append(ExpenseCategoryParsedRow(row_num=i, data={}, errors=[str(e)]))
            continue

        name = (gv("NAME") or "").strip()
        cleaned = {"name": name, "is_active": is_active}

        if not name:
            errors.append("NAME is required.")
        elif name.lower() in names_in_file:
            errors.append(f"Duplicate NAME in file: {name}")
        elif ExpenseCategory.objects.filter(name__iexact=name).exists():
            errors.append(f"NAME already exists: {name}")

        if not errors and name:
            try:
                ExpenseCategory(name=name, is_active=is_active).full_clean()
            except ValidationError as ve:
                if hasattr(ve, "message_dict"):
                    for field, msgs in ve.message_dict.items():
                        for m in msgs:
                            errors.append(f"{field}: {m}")
                else:
                    errors.extend(list(ve.messages))

        if not errors and name:
            names_in_file.add(name.lower())

        rows.append(ExpenseCategoryParsedRow(row_num=i, data=cleaned, errors=errors))

    return rows, file_errors
