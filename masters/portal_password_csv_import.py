"""Parse and validate bulk portal password (ClientPortalCredential) CSV uploads."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from django.core.exceptions import ValidationError

from core.branch_access import approved_clients_for_user, client_allowed_for_user

from .models import Client, ClientPortalCredential, PortalName

PORTAL_PASSWORD_CSV_COLUMNS = [
    "CLIENT_ID",
    "PORTAL_NAME",
    "PORTAL_USERNAME",
    "PORTAL_PASSWORD",
]


def _upper(v: str) -> str:
    return (v or "").strip().upper()


@dataclass
class PortalPasswordParsedRow:
    row_num: int
    data: dict
    errors: list[str]


def parse_portal_passwords_csv(csv_bytes: bytes, *, user) -> tuple[list[PortalPasswordParsedRow], list[str]]:
    file_errors: list[str] = []
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = csv_bytes.decode("cp1252", errors="replace")

    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        return [], ["CSV appears to have no header row."]

    header_map = {_upper(h): h for h in reader.fieldnames}
    for req in PORTAL_PASSWORD_CSV_COLUMNS:
        if req not in header_map:
            return [], [f"Missing required column: {req}"]

    client_qs = approved_clients_for_user(user)
    clients_by_id = {c.client_id.upper(): c for c in client_qs}
    portals_by_name = {p.name.lower(): p for p in PortalName.objects.filter(is_active=True)}

    rows: list[PortalPasswordParsedRow] = []

    for i, raw in enumerate(reader, start=2):

        def gv(key: str) -> str:
            orig = header_map.get(key)
            return (raw.get(orig, "") or "").strip() if orig else ""

        errors: list[str] = []
        client_id = _upper(gv("CLIENT_ID"))
        portal_name = (gv("PORTAL_NAME") or "").strip()
        username = (gv("PORTAL_USERNAME") or "").strip()
        password = gv("PORTAL_PASSWORD")

        client = clients_by_id.get(client_id)
        portal = portals_by_name.get(portal_name.lower()) if portal_name else None

        if not client_id:
            errors.append("CLIENT_ID is required.")
        elif not client:
            errors.append(f"CLIENT_ID not found or not in your branch: {client_id}")
        elif not client_allowed_for_user(user, client):
            errors.append(f"CLIENT_ID not allowed for your branch: {client_id}")

        if not portal_name:
            errors.append("PORTAL_NAME is required.")
        elif not portal:
            errors.append(
                f"PORTAL_NAME not found or inactive: {portal_name} "
                "(add it under Portal names first)."
            )

        if not username:
            errors.append("PORTAL_USERNAME is required.")
        if not password:
            errors.append("PORTAL_PASSWORD is required.")

        cleaned = {
            "client": client,
            "portal": portal,
            "portal_username": username,
            "portal_password": password,
        }

        if not errors and client and portal:
            try:
                obj = ClientPortalCredential(
                    client=client,
                    portal=portal,
                    portal_username=username,
                    portal_password=password,
                )
                obj.full_clean()
            except ValidationError as ve:
                if hasattr(ve, "message_dict"):
                    for field, msgs in ve.message_dict.items():
                        for m in msgs:
                            errors.append(f"{field}: {m}")
                else:
                    errors.extend(list(ve.messages))

        rows.append(PortalPasswordParsedRow(row_num=i, data=cleaned, errors=errors))

    return rows, file_errors
