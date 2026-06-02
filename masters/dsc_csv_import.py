"""Parse and validate bulk DSC (ClientDSC) CSV uploads."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_date

from core.branch_access import client_allowed_for_user

from .forms import individual_clients_for_user
from .models import Client, ClientDSC

DSC_CSV_COLUMNS = [
    "CLIENT_ID",
    "CLIENT_NAME",
    "ISSUE_DATE",
    "EXPIRY_DATE",
    "EXPIRY_NOTIFICATION",
    "DSC_PASSWORD",
    "REMARKS",
]


def _upper(v: str) -> str:
    return (v or "").strip().upper()


def _bool_notification(v: str) -> bool:
    s = _upper(v)
    if s in {"YES", "Y", "TRUE", "1"}:
        return True
    if s in {"NO", "N", "FALSE", "0", ""}:
        return False
    raise ValueError("EXPIRY_NOTIFICATION must be YES or NO.")


def _parse_date_field(raw: str, field: str) -> date | None:
    s = (raw or "").strip()
    if not s:
        return None
    d = parse_date(s)
    if d:
        return d
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"{field} must be YYYY-MM-DD or DD-MM-YYYY.")


@dataclass
class DscParsedRow:
    row_num: int
    data: dict
    errors: list[str]


def parse_dsc_csv(csv_bytes: bytes, *, user) -> tuple[list[DscParsedRow], list[str]]:
    file_errors: list[str] = []
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = csv_bytes.decode("cp1252", errors="replace")

    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        return [], ["CSV appears to have no header row."]

    header_map = {_upper(h): h for h in reader.fieldnames}
    for req in DSC_CSV_COLUMNS:
        if req not in header_map:
            return [], [f"Missing required column: {req}"]

    client_qs = individual_clients_for_user(user)
    clients_by_id = {c.client_id.upper(): c for c in client_qs}

    rows: list[DscParsedRow] = []

    for i, raw in enumerate(reader, start=2):

        def gv(key: str) -> str:
            orig = header_map.get(key)
            return (raw.get(orig, "") or "").strip() if orig else ""

        errors: list[str] = []
        client_id = _upper(gv("CLIENT_ID"))
        client_name = (gv("CLIENT_NAME") or "").strip()
        client = clients_by_id.get(client_id)

        try:
            expiry_notification = _bool_notification(gv("EXPIRY_NOTIFICATION"))
        except ValueError as e:
            rows.append(DscParsedRow(row_num=i, data={}, errors=[str(e)]))
            continue

        issue_date = None
        expiry_date = None
        try:
            issue_date = _parse_date_field(gv("ISSUE_DATE"), "ISSUE_DATE")
            expiry_date = _parse_date_field(gv("EXPIRY_DATE"), "EXPIRY_DATE")
        except ValueError as e:
            errors.append(str(e))

        password = gv("DSC_PASSWORD")
        remarks = (gv("REMARKS") or "").strip()

        if not client_id:
            errors.append("CLIENT_ID is required.")
        if not client_name:
            errors.append("CLIENT_NAME is required.")
        elif not client:
            errors.append(
                f"CLIENT_ID not found, not Individual/Foreign Citizen, or not in your branch: {client_id}"
            )
        elif client and not client_allowed_for_user(user, client):
            errors.append(f"CLIENT_ID not allowed for your branch: {client_id}")
        elif client and client_name:
            expected = (client.client_name or "").strip()
            if expected.casefold() != client_name.casefold():
                errors.append(
                    f"CLIENT_NAME does not match client master for {client_id} "
                    f"(expected {expected!r}, got {client_name!r})."
                )

        if not issue_date:
            errors.append("ISSUE_DATE is required.")
        if not expiry_date:
            errors.append("EXPIRY_DATE is required.")
        if issue_date and expiry_date and expiry_date < issue_date:
            errors.append("EXPIRY_DATE must be on or after ISSUE_DATE.")
        if len(remarks) > 500:
            errors.append("REMARKS must be at most 500 characters.")

        cleaned = {
            "client": client,
            "issue_date": issue_date,
            "expiry_date": expiry_date,
            "expiry_notification": expiry_notification,
            "dsc_password": password,
            "remarks": remarks,
        }

        if not errors and client:
            try:
                obj = ClientDSC(
                    client=client,
                    issue_date=issue_date,
                    expiry_date=expiry_date,
                    expiry_notification=expiry_notification,
                    dsc_password=password,
                    remarks=remarks,
                )
                obj.full_clean()
            except ValidationError as ve:
                if hasattr(ve, "message_dict"):
                    for field, msgs in ve.message_dict.items():
                        for m in msgs:
                            errors.append(f"{field}: {m}")
                else:
                    errors.extend(list(ve.messages))

        rows.append(DscParsedRow(row_num=i, data=cleaned, errors=errors))

    return rows, file_errors
