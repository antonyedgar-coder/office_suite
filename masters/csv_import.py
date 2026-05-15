import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, date

from django.core.exceptions import ValidationError

from .models import BRANCH_CHOICES, Client, ClientGroup, normalize_din_from_import_value

# Required headers for import (order used in downloadable template).
REQUIRED_CLIENT_CSV_COLUMNS = [
    "CLIENT_TYPE",
    "BRANCH",
    "CLIENT_NAME",
    "PAN",
    "GSTIN",
    "DOB",
    "LLPIN",
    "CIN",
    "IS_DIRECTOR",
    "DIN",
    "ADDRESS",
    "CONTACT_PERSON",
    "MOBILE",
    "EMAIL",
]
# Optional columns (older CSV files without these columns still import).
OPTIONAL_CLIENT_CSV_COLUMNS = [
    "PASSPORT_NO",
    "AADHAAR_NO",
]
# GROUP and FILE_NO appear after CLIENT_NAME in the downloadable template.
CSV_COLUMNS = (
    REQUIRED_CLIENT_CSV_COLUMNS[:3]
    + ["GROUP", "FILE_NO"]
    + REQUIRED_CLIENT_CSV_COLUMNS[3:]
    + OPTIONAL_CLIENT_CSV_COLUMNS
)


def _upper(v: str) -> str:
    return (v or "").strip().upper()


def _bool_yes(v: str) -> bool:
    return _upper(v) in {"YES", "Y", "TRUE", "1"}


def _canonical_branch(v: str) -> str:
    s = (v or "").strip().lower()
    for val, _label in BRANCH_CHOICES:
        if s == val.lower():
            return val
    return (v or "").strip()


def _parse_dob(v: str) -> date | None:
    s = (v or "").strip()
    if not s:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError("DOB must be DD-MM-YYYY.")


@dataclass
class ParsedRow:
    row_num: int
    data: dict
    errors: list[str]


def parse_clients_csv(csv_bytes: bytes) -> tuple[list[ParsedRow], list[str]]:
    """
    Returns: (rows, file_level_errors)
    Each row contains cleaned dict ready to construct Client(**data).
    """
    file_errors: list[str] = []

    # Try UTF-8, then fallback to CP1252 (common on Windows)
    text: str
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = csv_bytes.decode("cp1252", errors="replace")

    # IMPORTANT: newline="" is required for Python's csv module
    # to handle newlines correctly across Windows/macOS exports.
    f = io.StringIO(text, newline="")
    reader = csv.DictReader(f)

    if not reader.fieldnames:
        return [], ["CSV appears to have no header row."]

    header_map = {_upper(h): h for h in reader.fieldnames}
    missing = [c for c in REQUIRED_CLIENT_CSV_COLUMNS if c not in header_map]
    if missing:
        return [], [f"Missing columns: {', '.join(missing)}"]

    pan_in_file_non_branch: set[str] = set()
    allowed_branch = {c[0] for c in BRANCH_CHOICES}
    rows: list[ParsedRow] = []

    for i, raw in enumerate(reader, start=2):  # row 1 header, data starts at row 2
        def gv(upper_key: str) -> str:
            orig = header_map.get(upper_key)
            return (raw.get(orig, "") or "").strip() if orig else ""

        branch_val = _canonical_branch(gv("BRANCH"))

        cleaned = {
            "client_type": (gv("CLIENT_TYPE") or "").strip(),
            "branch": branch_val,
            "client_name": _upper(gv("CLIENT_NAME")),
            "client_group": None,
            "file_no": (gv("FILE_NO") or "").strip(),
            "pan": _upper(gv("PAN")),
            "gstin": _upper(gv("GSTIN")),
            "dob": None,
            "llpin": _upper(gv("LLPIN")),
            "cin": _upper(gv("CIN")),
            "is_director": _bool_yes(gv("IS_DIRECTOR")),
            "din": normalize_din_from_import_value(gv("DIN")),
            "address": (gv("ADDRESS") or "").strip(),
            "contact_person": (gv("CONTACT_PERSON") or "").strip(),
            "mobile": (gv("MOBILE") or "").strip(),
            "email": (gv("EMAIL") or "").strip(),
            "passport_no": gv("PASSPORT_NO"),
            "aadhaar_no": re.sub(r"\D", "", gv("AADHAAR_NO")),
        }

        errors: list[str] = []

        group_val = _upper(gv("GROUP"))
        if group_val:
            g = ClientGroup.objects.filter(name__iexact=group_val).first()
            if not g:
                errors.append(
                    f"Unknown GROUP (create it in Group Master first, name must match): {group_val}"
                )
            else:
                cleaned["client_group"] = g

        if branch_val not in allowed_branch:
            errors.append("BRANCH is required and must be Trivandrum or Nagercoil.")

        # In-file PAN duplicates: allowed only when CLIENT_TYPE is Branch
        if cleaned["pan"] and cleaned["client_type"] != "Branch":
            if cleaned["pan"] in pan_in_file_non_branch:
                errors.append(f"Duplicate PAN within file (non-Branch): {cleaned['pan']}")
            else:
                pan_in_file_non_branch.add(cleaned["pan"])

        # Parse DOB before model validation
        try:
            cleaned["dob"] = _parse_dob(gv("DOB"))
        except ValueError as e:
            errors.append(str(e))

        # Model validations (your rule set)
        try:
            c = Client(**cleaned)
            c.full_clean()
        except ValidationError as ve:
            if hasattr(ve, "message_dict"):
                for field, msgs in ve.message_dict.items():
                    for m in msgs:
                        errors.append(f"{field}: {m}")
            else:
                errors.extend(list(ve.messages))

        rows.append(ParsedRow(row_num=i, data=cleaned, errors=errors))

    # Existing DB PAN duplicates
    pans = sorted({r.data["pan"] for r in rows if r.data["pan"] and r.data.get("client_type") != "Branch"})
    if pans:
        existing = set(
            Client.objects.filter(pan__in=pans).exclude(client_type="Branch").values_list("pan", flat=True)
        )
        if existing:
            for r in rows:
                if r.data["pan"] and r.data.get("client_type") != "Branch" and r.data["pan"] in existing:
                    r.errors.append(f"PAN already exists in system: {r.data['pan']}")

    return rows, file_errors

