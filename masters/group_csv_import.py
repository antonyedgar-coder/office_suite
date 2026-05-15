import csv
import io
from dataclasses import dataclass

from django.core.exceptions import ValidationError

from .models import ClientGroup

# Headers for bulk upload (case-insensitive match on import).
GROUP_CSV_COLUMNS = ["NAME", "NOTES", "IS_ACTIVE"]


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
class GroupParsedRow:
    row_num: int
    data: dict
    errors: list[str]


def parse_client_groups_csv(csv_bytes: bytes) -> tuple[list[GroupParsedRow], list[str]]:
    """Returns (rows, file_level_errors). Each row.data is suitable for ClientGroup(**data) before group_id is set."""
    file_errors: list[str] = []

    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = csv_bytes.decode("cp1252", errors="replace")

    f = io.StringIO(text, newline="")
    reader = csv.DictReader(f)

    if not reader.fieldnames:
        return [], ["CSV appears to have no header row."]

    header_map = {_upper(h): h for h in reader.fieldnames}
    if "NAME" not in header_map:
        return [], ["Missing required column: NAME"]

    rows: list[GroupParsedRow] = []
    names_in_file: set[str] = set()

    for i, raw in enumerate(reader, start=2):

        def gv(upper_key: str) -> str:
            orig = header_map.get(upper_key)
            return (raw.get(orig, "") or "").strip() if orig else ""

        errors: list[str] = []

        try:
            is_active = _bool_active(gv("IS_ACTIVE"))
        except ValueError as e:
            rows.append(GroupParsedRow(row_num=i, data={}, errors=[str(e)]))
            continue

        name = _upper(gv("NAME"))
        notes = (gv("NOTES") or "").strip()
        cleaned = {"name": name, "notes": notes, "is_active": is_active}

        if not name:
            errors.append("NAME is required.")
        elif name in names_in_file:
            errors.append(f"Duplicate NAME in file: {name}")
        elif ClientGroup.objects.filter(name__iexact=name).exists():
            errors.append(f"NAME already exists in Group Master: {name}")

        if not errors and name:
            try:
                obj = ClientGroup(name=name, notes=notes, is_active=is_active)
                obj.full_clean(exclude=["group_id"])
            except ValidationError as ve:
                if hasattr(ve, "message_dict"):
                    for field, msgs in ve.message_dict.items():
                        for m in msgs:
                            errors.append(f"{field}: {m}")
                else:
                    errors.extend(list(ve.messages))

        if not errors and name:
            names_in_file.add(name)

        rows.append(GroupParsedRow(row_num=i, data=cleaned, errors=errors))

    return rows, file_errors
