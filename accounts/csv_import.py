"""Parse and validate bulk Account Group and Account Ledger CSV uploads."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from .models import MAIN_HEAD_CHOICES, Account, AccountGroup

PRIMARY_GROUP_CSV_COLUMNS = ["NAME", "MAIN_HEAD", "IS_ACTIVE"]
ACCOUNT_GROUP_CSV_COLUMNS = ["NAME", "PRIMARY_GROUP", "MAIN_HEAD", "IS_ACTIVE"]
ACCOUNT_LEDGER_CSV_COLUMNS = [
    "NAME",
    "PRIMARY_GROUP",
    "ACCOUNT_GROUP",
    "ADDRESS",
    "GSTIN",
    "HSN_SAC",
    "GST_RATE",
    "PURE_AGENT",
    "PAN",
    "OPENING_BALANCE",
    "IS_ACTIVE",
]

_HEAD_BY_KEY = {key.lower(): key for key, _label in MAIN_HEAD_CHOICES}
_HEAD_BY_LABEL = {label.lower(): key for key, label in MAIN_HEAD_CHOICES}


def _upper(v: str) -> str:
    return (v or "").strip().upper()


def _decode_csv(csv_bytes: bytes) -> str:
    try:
        return csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return csv_bytes.decode("cp1252", errors="replace")


def _bool_flag(v: str, field: str, *, default: bool = True) -> bool:
    s = _upper(v)
    if s in {""}:
        return default
    if s in {"YES", "Y", "TRUE", "1"}:
        return True
    if s in {"NO", "N", "FALSE", "0"}:
        return False
    raise ValueError(f"{field} must be YES, NO, or blank.")


def _parse_decimal(v: str, field: str, *, allow_blank: bool = True) -> Decimal | None:
    s = (v or "").strip()
    if not s:
        if allow_blank:
            return None
        raise ValueError(f"{field} is required.")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a number.") from exc


def _resolve_main_head(v: str) -> str | None:
    s = (v or "").strip()
    if not s:
        return None
    key = _HEAD_BY_KEY.get(s.lower()) or _HEAD_BY_LABEL.get(s.lower())
    if not key:
        labels = ", ".join(label for _key, label in MAIN_HEAD_CHOICES)
        raise ValueError(f"MAIN_HEAD must be one of: {labels}.")
    return key


def _find_primary_group(name: str, main_head: str | None = None) -> AccountGroup | None:
    qs = AccountGroup.parent_groups().filter(name__iexact=name)
    if main_head:
        qs = qs.filter(main_head=main_head)
    matches = list(qs[:3])
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"PRIMARY_GROUP is ambiguous ({name}). Set MAIN_HEAD to Assets, Liabilities, Income, or Expenses."
        )
    return None


def _collect_validation_errors(exc: ValidationError) -> list[str]:
    if hasattr(exc, "message_dict"):
        out: list[str] = []
        for field, msgs in exc.message_dict.items():
            for m in msgs:
                out.append(f"{field}: {m}")
        return out
    return list(exc.messages)


def _header_map(fieldnames) -> dict[str, str]:
    return {_upper(h): h for h in fieldnames if h is not None}


def _row_value(raw: dict, header_map: dict[str, str], key: str) -> str:
    orig = header_map.get(key)
    return (raw.get(orig, "") or "").strip() if orig else ""


@dataclass
class ParsedRow:
    row_num: int
    data: dict
    errors: list[str]


def parse_primary_groups_csv(csv_bytes: bytes) -> tuple[list[ParsedRow], list[str]]:
    text = _decode_csv(csv_bytes)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        return [], ["CSV appears to have no header row."]

    header_map = _header_map(reader.fieldnames)
    missing = [col for col in ("NAME", "MAIN_HEAD") if col not in header_map]
    if missing:
        return [], [f"Missing required column: {missing[0]}"]

    rows: list[ParsedRow] = []
    seen: set[tuple[str, int]] = set()

    for i, raw in enumerate(reader, start=2):
        errors: list[str] = []
        name = (_row_value(raw, header_map, "NAME") or "").strip()
        try:
            is_active = _bool_flag(_row_value(raw, header_map, "IS_ACTIVE"), "IS_ACTIVE")
            main_head = _resolve_main_head(_row_value(raw, header_map, "MAIN_HEAD"))
        except ValueError as e:
            rows.append(ParsedRow(row_num=i, data={}, errors=[str(e)]))
            continue

        parent = None
        if not name:
            errors.append("NAME is required.")
        if not main_head:
            errors.append("MAIN_HEAD is required.")
        else:
            parent = AccountGroup.main_heads().filter(main_head=main_head).first()
            if parent is None:
                parent = AccountGroup.main_heads().filter(name__iexact=main_head).first()
            if parent is None:
                errors.append(f"MAIN_HEAD not found: {_row_value(raw, header_map, 'MAIN_HEAD')}")

        cleaned = {
            "name": name,
            "parent": parent,
            "parent_name": parent.name if parent else "",
            "is_active": is_active,
        }

        if not errors and parent:
            key = (name.lower(), parent.pk)
            if key in seen:
                errors.append(f"Duplicate NAME under this main head in file: {name}")
            elif AccountGroup.objects.filter(name__iexact=name, parent=parent).exists():
                errors.append(f"Primary group already exists under {parent.name}: {name}")
            else:
                obj = AccountGroup(
                    name=name,
                    parent=parent,
                    main_head=parent.resolved_main_head(),
                    is_active=is_active,
                )
                try:
                    obj.full_clean()
                except ValidationError as ve:
                    errors.extend(_collect_validation_errors(ve))
                else:
                    seen.add(key)

        rows.append(ParsedRow(row_num=i, data=cleaned, errors=errors))

    return rows, []


def parse_account_groups_csv(csv_bytes: bytes) -> tuple[list[ParsedRow], list[str]]:
    text = _decode_csv(csv_bytes)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        return [], ["CSV appears to have no header row."]

    header_map = _header_map(reader.fieldnames)
    missing = [col for col in ("NAME", "PRIMARY_GROUP") if col not in header_map]
    if missing:
        return [], [f"Missing required column: {missing[0]}"]

    rows: list[ParsedRow] = []
    seen: set[tuple[str, int]] = set()

    for i, raw in enumerate(reader, start=2):
        errors: list[str] = []
        name = ( _row_value(raw, header_map, "NAME") or "").strip()
        primary_name = (_row_value(raw, header_map, "PRIMARY_GROUP") or "").strip()
        try:
            is_active = _bool_flag(_row_value(raw, header_map, "IS_ACTIVE"), "IS_ACTIVE")
        except ValueError as e:
            rows.append(ParsedRow(row_num=i, data={}, errors=[str(e)]))
            continue
        try:
            main_head = _resolve_main_head(_row_value(raw, header_map, "MAIN_HEAD"))
        except ValueError as e:
            rows.append(ParsedRow(row_num=i, data={}, errors=[str(e)]))
            continue

        parent = None
        if not name:
            errors.append("NAME is required.")
        if not primary_name:
            errors.append("PRIMARY_GROUP is required.")
        else:
            try:
                parent = _find_primary_group(primary_name, main_head)
            except ValueError as e:
                errors.append(str(e))
            else:
                if parent is None:
                    extra = f" under {main_head}" if main_head else ""
                    errors.append(f"PRIMARY_GROUP not found{extra}: {primary_name}")

        cleaned = {
            "name": name,
            "parent": parent,
            "parent_name": parent.name if parent else primary_name,
            "is_active": is_active,
        }

        if not errors and parent:
            key = (name.lower(), parent.pk)
            if key in seen:
                errors.append(f"Duplicate NAME under this primary group in file: {name}")
            elif AccountGroup.objects.filter(name__iexact=name, parent=parent).exists():
                errors.append(f"Account group already exists under {parent.name}: {name}")
            else:
                obj = AccountGroup(
                    name=name,
                    parent=parent,
                    main_head=parent.resolved_main_head(),
                    is_active=is_active,
                )
                try:
                    obj.full_clean()
                except ValidationError as ve:
                    errors.extend(_collect_validation_errors(ve))
                else:
                    seen.add(key)

        rows.append(ParsedRow(row_num=i, data=cleaned, errors=errors))

    return rows, []


def parse_account_ledgers_csv(csv_bytes: bytes) -> tuple[list[ParsedRow], list[str]]:
    text = _decode_csv(csv_bytes)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        return [], ["CSV appears to have no header row."]

    header_map = _header_map(reader.fieldnames)
    missing = [col for col in ("NAME", "PRIMARY_GROUP") if col not in header_map]
    if missing:
        return [], [f"Missing required column: {missing[0]}"]

    rows: list[ParsedRow] = []
    seen: set[tuple[str, int]] = set()

    for i, raw in enumerate(reader, start=2):
        errors: list[str] = []
        name = (_row_value(raw, header_map, "NAME") or "").strip()
        primary_name = (_row_value(raw, header_map, "PRIMARY_GROUP") or "").strip()
        account_group_name = (_row_value(raw, header_map, "ACCOUNT_GROUP") or "").strip()
        address = (_row_value(raw, header_map, "ADDRESS") or "").strip()
        gstin = _upper(_row_value(raw, header_map, "GSTIN"))
        hsn_code = (_row_value(raw, header_map, "HSN_SAC") or "").strip()
        pan = _upper(_row_value(raw, header_map, "PAN"))

        try:
            is_active = _bool_flag(_row_value(raw, header_map, "IS_ACTIVE"), "IS_ACTIVE")
            is_pure_agent = _bool_flag(
                _row_value(raw, header_map, "PURE_AGENT"), "PURE_AGENT", default=False
            )
            gst_rate = _parse_decimal(_row_value(raw, header_map, "GST_RATE"), "GST_RATE")
            opening = _parse_decimal(_row_value(raw, header_map, "OPENING_BALANCE"), "OPENING_BALANCE")
        except ValueError as e:
            rows.append(ParsedRow(row_num=i, data={}, errors=[str(e)]))
            continue

        if opening is None:
            opening = Decimal("0.00")
        if opening < 0:
            errors.append("OPENING_BALANCE cannot be negative.")
        if gst_rate is not None and gst_rate < 0:
            errors.append("GST_RATE cannot be negative.")
        if is_pure_agent:
            gst_rate = None

        parent = None
        group = None
        if not name:
            errors.append("NAME is required.")
        if not primary_name:
            errors.append("PRIMARY_GROUP is required.")
        else:
            try:
                parent = _find_primary_group(primary_name)
            except ValueError as e:
                errors.append(str(e))
            else:
                if parent is None:
                    errors.append(f"PRIMARY_GROUP not found: {primary_name}")

        if parent and account_group_name:
            group = (
                AccountGroup.account_groups()
                .filter(name__iexact=account_group_name, parent=parent)
                .first()
            )
            if group is None:
                errors.append(
                    f"ACCOUNT_GROUP not found under {parent.name}: {account_group_name}"
                )
        elif parent:
            group = parent

        cleaned = {
            "name": name,
            "group": group,
            "primary_name": parent.name if parent else primary_name,
            "account_group_name": group.name if group and group != parent else "",
            "address": address,
            "gstin": gstin,
            "hsn_code": hsn_code,
            "gst_rate": gst_rate,
            "is_pure_agent": is_pure_agent,
            "pan": pan,
            "opening_balance": opening,
            "is_active": is_active,
        }

        if not errors and group:
            key = (name.lower(), group.pk)
            if key in seen:
                errors.append(f"Duplicate NAME under this group in file: {name}")
            elif Account.objects.filter(name__iexact=name, group=group).exists():
                label = group.name
                errors.append(f"Account ledger already exists under {label}: {name}")
            else:
                obj = Account(
                    name=name,
                    group=group,
                    address=address,
                    gstin=gstin,
                    hsn_code=hsn_code,
                    gst_rate=gst_rate,
                    is_pure_agent=is_pure_agent,
                    pan=pan,
                    opening_balance=opening,
                    is_active=is_active,
                )
                try:
                    obj.full_clean()
                except ValidationError as ve:
                    errors.extend(_collect_validation_errors(ve))
                else:
                    seen.add(key)

        rows.append(ParsedRow(row_num=i, data=cleaned, errors=errors))

    return rows, []
