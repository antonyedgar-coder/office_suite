"""CSV bulk import for Director Mapping."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from io import StringIO
from typing import Any

from .models import (
    CESSATION_REASON_CHOICES,
    CLIENT_NAME_TEXT_RE,
    DIRECTOR_COMPANY_TYPES,
    DIRECTOR_ELIGIBLE_CLIENT_TYPES,
    DIN_RE,
    normalize_din_from_import_value,
)

# Canonical values match model choices (display labels).
_REASON_BY_TOKEN = {
    "RESIGNED": "Resigned",
    "DISQUALIFIED": "Disqualified",
    "TERMINATED": "Terminated",
    "DEATH": "Death",
}
_ALLOWED_REASONS = {c[0] for c in CESSATION_REASON_CHOICES}

DIRECTOR_MAPPING_CSV_HEADERS = [
    "DIRECTOR_CLIENT_ID",
    "DIN_NO",
    "DIRECTOR_NAME",
    "COMPANY_CLIENT_ID",
    "COMPANY_NAME",
    "DATE_OF_APPOINTMENT",
    "DATE_OF_CESSION",
    "REASON_FOR_CESSION",
]


@dataclass
class DirectorMappingImportRow:
    row_num: int
    data: dict[str, Any]
    errors: list[str]


def _as_date(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        s = v.strip()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
    return None


def _read_csv_bytes(csv_bytes: bytes, *, expected_headers: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = csv_bytes.decode("cp1252", errors="replace")

    file_errors: list[str] = []
    exp = [h.strip().upper() for h in expected_headers]

    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        file_errors.append("Invalid header. File appears to be empty.")
        return [], file_errors

    found = [str(h or "").strip().upper() for h in reader.fieldnames]
    if found != exp:
        file_errors.append(
            f"Invalid header. Expected: {', '.join(exp)}. Found: {', '.join(found) if found else '(blank)'}.",
        )
        return [], file_errors

    rows: list[dict[str, Any]] = []
    for r in reader:
        if all((str(v or "").strip() == "") for v in r.values()):
            continue
        rows.append({(k or "").strip().upper(): v for k, v in r.items()})
    return rows, []


def _normalize_reason(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    key = s.upper().replace(" ", "_")
    if key in _REASON_BY_TOKEN:
        return _REASON_BY_TOKEN[key]
    if s in _ALLOWED_REASONS:
        return s
    return None


def parse_director_mappings_csv(csv_bytes: bytes) -> tuple[list[DirectorMappingImportRow], list[str]]:
    raw_rows, file_errors = _read_csv_bytes(csv_bytes, expected_headers=DIRECTOR_MAPPING_CSV_HEADERS)
    out: list[DirectorMappingImportRow] = []
    if file_errors:
        return out, file_errors

    for idx, r in enumerate(raw_rows, start=2):
        errors: list[str] = []
        dir_id = (str(r.get("DIRECTOR_CLIENT_ID") or "").strip().upper())
        din_raw = normalize_din_from_import_value(r.get("DIN_NO"))
        dir_name = (str(r.get("DIRECTOR_NAME") or "").strip())
        comp_id = (str(r.get("COMPANY_CLIENT_ID") or "").strip().upper())
        comp_name = (str(r.get("COMPANY_NAME") or "").strip())
        ad = _as_date(r.get("DATE_OF_APPOINTMENT"))
        cd = _as_date(r.get("DATE_OF_CESSION"))
        reason_raw = str(r.get("REASON_FOR_CESSION") or "").strip()
        reason = _normalize_reason(reason_raw)

        if not dir_id:
            errors.append("DIRECTOR_CLIENT_ID is required.")
        if not din_raw:
            errors.append("DIN_NO is required.")
        elif not DIN_RE.match(din_raw.strip()):
            errors.append("DIN_NO must be exactly 8 digits.")
        if not dir_name:
            errors.append("DIRECTOR_NAME is required.")
        if not comp_id:
            errors.append("COMPANY_CLIENT_ID is required.")
        if not comp_name:
            errors.append("COMPANY_NAME is required.")
        if dir_name and not CLIENT_NAME_TEXT_RE.match(dir_name.upper()):
            errors.append(
                "DIRECTOR_NAME may only contain letters, numbers, spaces, and common punctuation "
                "(. , ' & ( ) / : + * # % = -)."
            )
        if comp_name and not CLIENT_NAME_TEXT_RE.match(comp_name.upper()):
            errors.append(
                "COMPANY_NAME may only contain letters, numbers, spaces, and common punctuation "
                "(. , ' & ( ) / : + * # % = -)."
            )
        if cd and not ad:
            errors.append("DATE_OF_CESSION cannot be entered without DATE_OF_APPOINTMENT.")
        if cd and ad and cd < ad:
            errors.append("DATE_OF_CESSION cannot be before DATE_OF_APPOINTMENT.")
        if cd and not reason:
            if not reason_raw:
                errors.append("REASON_FOR_CESSION is required when DATE_OF_CESSION is set.")
            else:
                errors.append(
                    "REASON_FOR_CESSION must be one of: Resigned, Disqualified, Terminated, Death.",
                )
        if reason and not cd:
            errors.append("REASON_FOR_CESSION must be blank when DATE_OF_CESSION is blank.")
        if reason_raw and not reason and not cd:
            errors.append(
                "REASON_FOR_CESSION must be blank when DATE_OF_CESSION is blank, or use a valid reason value.",
            )

        din_norm = din_raw.strip()
        out.append(
            DirectorMappingImportRow(
                row_num=idx,
                data={
                    "director_client_id": dir_id,
                    "din_no": din_norm,
                    "director_name": dir_name,
                    "company_client_id": comp_id,
                    "company_name": comp_name,
                    "appointed_date": ad,
                    "cessation_date": cd,
                    "reason_for_cessation": reason or "",
                },
                errors=errors,
            )
        )
    return out, []


def attach_client_master_validation(rows: list[DirectorMappingImportRow]) -> None:
    """Cross-check IDs, names, DIN, and company type against Client Master."""
    from .models import Client, DirectorMapping

    for row in rows:
        if row.errors:
            continue
        d = row.data
        dir_client = Client.approved_objects().filter(client_id__iexact=d["director_client_id"]).first()
        if not dir_client:
            row.errors.append("DIRECTOR_CLIENT_ID not found in approved Client Master (pending clients cannot be used).")
        else:
            if (dir_client.client_name or "").strip().upper() != (d["director_name"] or "").strip().upper():
                row.errors.append("DIRECTOR_NAME does not match Client Master for DIRECTOR_CLIENT_ID.")
            if (dir_client.din or "").strip() != d["din_no"]:
                row.errors.append("DIN_NO does not match Client Master for DIRECTOR_CLIENT_ID.")
            if dir_client.client_type not in DIRECTOR_ELIGIBLE_CLIENT_TYPES:
                row.errors.append("Director record must be Client Type Individual or Foreign Citizen.")
            if not dir_client.is_director:
                row.errors.append("Director client is not marked as Director in Client Master.")
            if not (dir_client.din or "").strip():
                row.errors.append("Director DIN is missing in Client Master.")

        comp_client = Client.approved_objects().filter(client_id__iexact=d["company_client_id"]).first()
        if not comp_client:
            row.errors.append("COMPANY_CLIENT_ID not found in approved Client Master (pending clients cannot be used).")
        else:
            if (comp_client.client_name or "").strip().upper() != (d["company_name"] or "").strip().upper():
                row.errors.append("COMPANY_NAME does not match Client Master for COMPANY_CLIENT_ID.")
            if comp_client.client_type not in DIRECTOR_COMPANY_TYPES:
                row.errors.append(
                    "Company client type must be Private Limited, Public Limited, Nidhi Co, FPO, Sec 8 Co or LLP.",
                )

        if row.errors:
            continue

        if dir_client and comp_client:
            if DirectorMapping.objects.filter(
                director=dir_client,
                company=comp_client,
                cessation_date__isnull=True,
            ).exists():
                row.errors.append(
                    "An active director mapping already exists for this director and company. "
                    "Enter the cessation on that record before importing a new appointment."
                )
            elif d.get("appointed_date") is not None and DirectorMapping.objects.filter(
                director=dir_client,
                company=comp_client,
                appointed_date=d["appointed_date"],
            ).exists():
                row.errors.append(
                    "A mapping with this director, company and appointment date already exists."
                )


def validate_director_mapping_import_active_uniqueness_in_file(rows: list[DirectorMappingImportRow]) -> None:
    """At most one row per director+company may omit cessation date within the same import file."""
    seen_active_pair: set[tuple[str, str]] = set()
    for row in rows:
        if row.errors:
            continue
        d = row.data
        if d.get("cessation_date") is not None:
            continue
        key = (
            (d["director_client_id"] or "").strip().upper(),
            (d["company_client_id"] or "").strip().upper(),
        )
        if key in seen_active_pair:
            row.errors.append(
                "Only one active appointment (no cessation date) per director and company is allowed in the file."
            )
        else:
            seen_active_pair.add(key)
