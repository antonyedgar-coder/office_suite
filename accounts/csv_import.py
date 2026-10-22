"""Parse and validate bulk Account Group, Account Ledger, and old-books voucher CSV uploads."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from .models import (
    MAIN_HEAD_CHOICES,
    SERIES_CHOICES,
    SERIES_GST,
    SERIES_NGST,
    VOUCHER_SALES,
    VOUCHER_TABS,
    VOUCHER_TYPE_CHOICES,
    Account,
    AccountGroup,
    Voucher,
)

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


VOUCHER_BOOKS_CSV_COLUMNS = [
    "DATE",
    "VOUCHER_TYPE",
    "NUMBER",
    "NARRATION",
    "ACCOUNT",
    "DEBIT",
    "CREDIT",
    "SERIES",
]

_TYPE_BY_KEY = {key.lower(): key for key, _label in VOUCHER_TYPE_CHOICES}
_TYPE_BY_LABEL = {label.lower(): key for key, label in VOUCHER_TYPE_CHOICES}
_TYPE_BY_TAB = {label.lower(): key for key, label in VOUCHER_TABS}
_TYPE_ALIASES = {
    "gst": VOUCHER_SALES,
    "gst invoice": VOUCHER_SALES,
    "non gst": VOUCHER_SALES,
    "non-gst": VOUCHER_SALES,
    "ngst": VOUCHER_SALES,
    "sales invoice": VOUCHER_SALES,
    "purchase invoice": "purchase",
    "receipt voucher": "receipt",
    "payment voucher": "payment",
    "contra voucher": "contra",
    "journal voucher": "journal",
    "jv": "journal",
    "cn": "credit_note",
    "dn": "debit_note",
}
_TYPE_SERIES_HINTS = {
    "gst": SERIES_GST,
    "gst invoice": SERIES_GST,
    "non gst": SERIES_NGST,
    "non-gst": SERIES_NGST,
    "ngst": SERIES_NGST,
}
_SERIES_BY_KEY = {key.lower(): key for key, _label in SERIES_CHOICES}
_SERIES_BY_LABEL = {label.lower(): key for key, label in SERIES_CHOICES}


def _parse_voucher_date(v: str):
    s = (v or "").strip()
    if not s:
        raise ValueError("DATE is required.")
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError("DATE must be DD-MM-YYYY.")


def _resolve_voucher_type(v: str) -> str | None:
    s = (v or "").strip().lower()
    if not s:
        return None
    return (
        _TYPE_BY_KEY.get(s)
        or _TYPE_BY_LABEL.get(s)
        or _TYPE_BY_TAB.get(s)
        or _TYPE_ALIASES.get(s)
    )


def _resolve_series(v: str) -> str | None:
    s = (v or "").strip()
    if not s:
        return None
    key = _SERIES_BY_KEY.get(s.lower()) or _SERIES_BY_LABEL.get(s.lower())
    if not key:
        labels = ", ".join(code for code, _label in SERIES_CHOICES)
        raise ValueError(f"SERIES must be one of: {labels}.")
    return key


def _find_ledger(name: str) -> Account | None:
    matches = list(Account.objects.filter(name__iexact=name)[:3])
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"ACCOUNT is ambiguous: {name}.")
    return None


def _voucher_book_key(data: dict) -> tuple[str, str, str]:
    return (
        data.get("voucher_type") or "",
        data.get("series") or "",
        (data.get("number") or "").strip(),
    )


def _annotate_voucher_group_errors(rows: list[ParsedRow]) -> None:
    grouped: dict[tuple[str, str, str], list[ParsedRow]] = defaultdict(list)
    for row in rows:
        key = _voucher_book_key(row.data)
        if key[2]:
            grouped[key].append(row)
    existing = set(
        Voucher.objects.filter(number__in={key[2] for key in grouped}).values_list(
            "voucher_type", "series", "number"
        )
    )
    for key, members in grouped.items():
        if any(m.errors for m in members):
            continue
        extra: list[str] = []
        dates = {m.data["date"] for m in members}
        if len(dates) > 1:
            extra.append("All rows for this NUMBER and voucher type must use the same DATE.")
        debit = sum((m.data.get("debit") or Decimal("0.00") for m in members), Decimal("0.00"))
        credit = sum((m.data.get("credit") or Decimal("0.00") for m in members), Decimal("0.00"))
        filled = [
            m
            for m in members
            if (m.data.get("debit") or Decimal("0.00")) or (m.data.get("credit") or Decimal("0.00"))
        ]
        if len(filled) < 2:
            extra.append("Each voucher needs at least two debit/credit lines.")
        if debit != credit:
            extra.append("Total debit must equal total credit for this NUMBER.")
        if key in existing:
            extra.append(f"Voucher number already exists: {key[2]}")
        for m in members:
            m.errors.extend(extra)


def grouped_voucher_books(rows: list[ParsedRow]) -> list[dict]:
    grouped: dict[tuple[str, str, str], list[ParsedRow]] = defaultdict(list)
    for row in rows:
        grouped[_voucher_book_key(row.data)].append(row)
    out = []
    for _key, members in grouped.items():
        first = members[0]
        out.append(
            {
                "number": first.data["number"],
                "date": first.data["date"],
                "voucher_type": first.data["voucher_type"],
                "series": first.data.get("series"),
                "narration": first.data.get("narration") or "",
                "lines": [
                    {
                        "account": m.data["account"],
                        "debit": m.data.get("debit") or Decimal("0.00"),
                        "credit": m.data.get("credit") or Decimal("0.00"),
                    }
                    for m in members
                ],
            }
        )
    return out


def parse_voucher_books_csv(csv_bytes: bytes) -> tuple[list[ParsedRow], list[str]]:
    text = _decode_csv(csv_bytes)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        return [], ["CSV appears to have no header row."]

    header_map = _header_map(reader.fieldnames)
    missing = [col for col in ("DATE", "VOUCHER_TYPE", "NUMBER", "ACCOUNT") if col not in header_map]
    if missing:
        return [], [f"Missing required column: {missing[0]}"]

    rows: list[ParsedRow] = []
    for i, raw in enumerate(reader, start=2):
        errors: list[str] = []
        number = (_row_value(raw, header_map, "NUMBER") or "").strip()
        narration = (_row_value(raw, header_map, "NARRATION") or "").strip()
        account_name = (_row_value(raw, header_map, "ACCOUNT") or "").strip()
        raw_date = _row_value(raw, header_map, "DATE")
        raw_type = _row_value(raw, header_map, "VOUCHER_TYPE")
        raw_debit = _row_value(raw, header_map, "DEBIT")
        raw_credit = _row_value(raw, header_map, "CREDIT")
        if not any(
            (v or "").strip()
            for v in (raw_date, raw_type, number, account_name, raw_debit, raw_credit)
        ):
            continue
        voucher_date = None
        voucher_type = None
        series = None
        debit = Decimal("0.00")
        credit = Decimal("0.00")
        account = None
        try:
            voucher_date = _parse_voucher_date(raw_date)
        except ValueError as e:
            errors.append(str(e))
        voucher_type = _resolve_voucher_type(raw_type)
        if not voucher_type:
            errors.append(
                "VOUCHER_TYPE is required (Sales, Purchase, Receipt, Payment, Contra, Journal, Credit note, Debit note)."
            )
        try:
            series = _resolve_series(_row_value(raw, header_map, "SERIES"))
        except ValueError as e:
            errors.append(str(e))
        if series is None:
            series = _TYPE_SERIES_HINTS.get((raw_type or "").strip().lower())
        if voucher_type == VOUCHER_SALES and not series:
            errors.append("SERIES is required for Sales (GST or NGST).")
        elif series is None and voucher_type:
            from .services import default_series_for_type

            series = default_series_for_type(voucher_type)
        try:
            debit = _parse_decimal(_row_value(raw, header_map, "DEBIT"), "DEBIT") or Decimal("0.00")
            credit = _parse_decimal(_row_value(raw, header_map, "CREDIT"), "CREDIT") or Decimal("0.00")
        except ValueError as e:
            errors.append(str(e))
        if debit and credit:
            errors.append("A line cannot have both DEBIT and CREDIT.")
        if not number:
            errors.append("NUMBER is required (use the old software serial).")
        elif len(number) > 40:
            errors.append("NUMBER cannot be longer than 40 characters.")
        if not account_name:
            errors.append("ACCOUNT is required.")
        else:
            try:
                account = _find_ledger(account_name)
            except ValueError as e:
                errors.append(str(e))
            else:
                if account is None:
                    errors.append(f"ACCOUNT not found: {account_name}")
        rows.append(
            ParsedRow(
                row_num=i,
                data={
                    "date": voucher_date,
                    "voucher_type": voucher_type,
                    "number": number,
                    "narration": narration[:500],
                    "account": account,
                    "account_name": account_name,
                    "debit": debit,
                    "credit": credit,
                    "series": series,
                },
                errors=errors,
            )
        )
    _annotate_voucher_group_errors(rows)
    return rows, []
