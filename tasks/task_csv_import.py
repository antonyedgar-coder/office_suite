"""Parse and validate bulk task assignment CSV uploads."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.branch_access import approved_clients_for_user, client_allowed_for_user
from masters.models import Client

from .models import Task, TaskMaster
from .one_time_period import allocate_one_time_period_key
from .period_keys import PERIOD_ONE_TIME, build_period_key, period_type_for_task_master
from .period_overlap import find_overlapping_task, overlap_error_message
from .recurrence import compute_create_due_dates
from .user_labels import staff_users_queryset

User = get_user_model()

TASK_CSV_COLUMNS = [
    "CLIENT_ID",
    "TASK_MASTER",
    "ASSIGNEE_EMAILS",
    "VERIFIER_EMAIL",
    "DOCUMENT_CHECKER_EMAIL",
    "PERIOD_TYPE",
    "PERIOD_MONTH",
    "PERIOD_FY",
    "PERIOD_QUARTER",
    "PERIOD_HALF",
    "PERIOD_YEAR_FROM",
    "PERIOD_YEAR_TO",
    "DUE_DATE",
    "PRIORITY",
    "IS_BILLABLE",
    "FEES_AMOUNT",
]


def _upper(v: str) -> str:
    return (v or "").strip().upper()


def _cell(raw: dict, header_map: dict[str, str], key: str) -> str:
    orig = header_map.get(key)
    return (raw.get(orig, "") or "").strip() if orig else ""


def _parse_due_date(raw: str) -> date | None:
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
    return None


def _parse_bool_yes(raw: str) -> bool:
    s = _upper(raw)
    if s in {"", "NO", "N", "FALSE", "0"}:
        return False
    if s in {"YES", "Y", "TRUE", "1"}:
        return True
    raise ValueError("IS_BILLABLE must be YES or NO (or blank for NO).")


def _resolve_task_master(raw: str) -> TaskMaster | None:
    s = (raw or "").strip()
    if not s:
        return None
    if "|" in s:
        group_name, master_name = [p.strip() for p in s.split("|", 1)]
        return (
            TaskMaster.selectable_for_new_tasks()
            .filter(
                task_group__name__iexact=group_name,
                name__iexact=master_name,
            )
            .first()
        )
    return TaskMaster.selectable_for_new_tasks().filter(name__iexact=s).first()


@dataclass
class TaskParsedRow:
    row_num: int
    data: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def parse_tasks_csv(csv_bytes: bytes, *, user) -> tuple[list[TaskParsedRow], list[str]]:
    """Returns (rows, file_level_errors)."""
    file_errors: list[str] = []
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = csv_bytes.decode("cp1252", errors="replace")

    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames:
        return [], ["CSV appears to have no header row."]

    header_map = {_upper(h): h for h in reader.fieldnames}
    required = {
        "CLIENT_ID",
        "TASK_MASTER",
        "ASSIGNEE_EMAILS",
        "VERIFIER_EMAIL",
        "DOCUMENT_CHECKER_EMAIL",
        "PERIOD_TYPE",
        "DUE_DATE",
    }
    missing = sorted(required - set(header_map))
    if missing:
        return [], [f"Missing required column(s): {', '.join(missing)}"]

    staff_by_email = {u.email.lower(): u for u in staff_users_queryset()}
    client_qs = approved_clients_for_user(user)
    clients_by_id = {c.client_id.upper(): c for c in client_qs}
    rows: list[TaskParsedRow] = []
    seen_keys: set[tuple] = set()

    for i, raw in enumerate(reader, start=2):
        errors: list[str] = []
        client_id = _upper(_cell(raw, header_map, "CLIENT_ID"))
        master_raw = _cell(raw, header_map, "TASK_MASTER")
        assignee_raw = _cell(raw, header_map, "ASSIGNEE_EMAILS")
        verifier_emails_raw = _cell(raw, header_map, "VERIFIER_EMAIL")
        document_checker_email = _cell(raw, header_map, "DOCUMENT_CHECKER_EMAIL").lower()
        period_type = _cell(raw, header_map, "PERIOD_TYPE").lower().replace(" ", "_")
        due_raw = _cell(raw, header_map, "DUE_DATE")

        client = clients_by_id.get(client_id)
        if not client_id:
            errors.append("CLIENT_ID is required.")
        elif not client:
            errors.append(f"CLIENT_ID not found or not in your branch: {client_id}")
        elif not client_allowed_for_user(user, client):
            errors.append(f"CLIENT_ID not allowed for your branch: {client_id}")

        master = _resolve_task_master(master_raw) if master_raw else None
        if not master_raw:
            errors.append("TASK_MASTER is required (use Group | Master or master name).")
        elif not master:
            errors.append(
                f"TASK_MASTER not found or inactive: {master_raw} "
                "(only active task masters can be used)."
            )

        assignee_emails = [e.strip().lower() for e in assignee_raw.replace(";", ",").split(",") if e.strip()]
        assignees = []
        if not assignee_emails:
            errors.append("ASSIGNEE_EMAILS is required (comma or semicolon separated).")
        else:
            for em in assignee_emails:
                u = staff_by_email.get(em)
                if not u:
                    errors.append(f"Unknown assignee email: {em}")
                else:
                    assignees.append(u)
            if len({u.pk for u in assignees}) != len(assignees):
                errors.append("ASSIGNEE_EMAILS must be different people.")

        verifier = staff_by_email.get(verifier_email) if verifier_email else None
        if not verifier_email:
            errors.append("VERIFIER_EMAIL is required.")
        elif not verifier:
            errors.append(f"Unknown verifier email: {verifier_email}")

        document_checker = (
            staff_by_email.get(document_checker_email) if document_checker_email else None
        )
        if not document_checker_email:
            errors.append("DOCUMENT_CHECKER_EMAIL is required.")
        elif not document_checker:
            errors.append(f"Unknown document checker email: {document_checker_email}")

        if user.is_authenticated:
            if user.pk in {u.pk for u in assignees}:
                errors.append("Creator cannot be an assignee.")
            if verifiers and {u.pk for u in verifiers}.intersection({u.pk for u in assignees}):
                errors.append("A verifier cannot also be an assignee.")
            if document_checker and document_checker.pk in {u.pk for u in assignees}:
                errors.append("Document checker cannot be an assignee.")

        due_date = _parse_due_date(due_raw)

        locked_period = period_type_for_task_master(master) if master else None
        if locked_period:
            if period_type and period_type != locked_period:
                errors.append(
                    f"PERIOD_TYPE must be {locked_period} for this recurring task master."
                )
            period_type = locked_period

        period_key = ""
        period_type_stored = period_type
        try:
            month = int(_cell(raw, header_map, "PERIOD_MONTH") or "0") or None
            fy_raw = _cell(raw, header_map, "PERIOD_FY")
            fy_start = int(fy_raw) if fy_raw else None
            quarter = _upper(_cell(raw, header_map, "PERIOD_QUARTER")) or None
            half = _upper(_cell(raw, header_map, "PERIOD_HALF")) or None
            y_from = int(_cell(raw, header_map, "PERIOD_YEAR_FROM") or "0") or None
            y_to = int(_cell(raw, header_map, "PERIOD_YEAR_TO") or "0") or None
            period_key = build_period_key(
                period_type,
                month=month,
                fy_start=fy_start,
                quarter=quarter,
                half=half,
                year_from=y_from,
                year_to=y_to,
            )
        except (ValueError, DjangoValidationError) as exc:
            msg = exc.messages[0] if hasattr(exc, "messages") and exc.messages else str(exc)
            errors.append(f"Period: {msg}")

        if master and master.is_recurring and period_key and not errors:
            _, due_date = compute_create_due_dates(master, period_key, timezone.localdate())
        elif not due_raw:
            errors.append("DUE_DATE is required for one-time tasks (YYYY-MM-DD or DD-MM-YYYY).")
        elif not due_date:
            errors.append(f"Invalid DUE_DATE: {due_raw}")

        if (
            period_type == PERIOD_ONE_TIME
            and client
            and master
            and due_date
            and not errors
        ):
            period_key = allocate_one_time_period_key(client, master, due_date)

        priority = _cell(raw, header_map, "PRIORITY").lower() or TaskMaster.PRIORITY_NORMAL
        if priority not in dict(TaskMaster.PRIORITY_CHOICES):
            errors.append("PRIORITY must be low, normal, or urgent.")

        try:
            is_billable = _parse_bool_yes(_cell(raw, header_map, "IS_BILLABLE"))
        except ValueError as exc:
            errors.append(str(exc))
            is_billable = False

        fees_raw = _cell(raw, header_map, "FEES_AMOUNT")
        fees_amount = None
        if fees_raw:
            try:
                fees_amount = Decimal(fees_raw)
            except InvalidOperation:
                errors.append("FEES_AMOUNT must be a number.")
        if client and master and period_key and period_type and not errors:
            dup_key = (client.pk, master.pk, period_key)
            if dup_key in seen_keys:
                errors.append("Duplicate row for same client, task master, and period in this file.")
            else:
                existing = find_overlapping_task(
                    client=client,
                    master=master,
                    period_type=period_type,
                    period_key=period_key,
                )
                if existing:
                    errors.append(
                        overlap_error_message(
                            period_type=period_type,
                            period_key=period_key,
                            existing=existing,
                        )
                    )
                else:
                    seen_keys.add(dup_key)

        cleaned = {
            "client": client,
            "task_master": master,
            "assignees": assignees,
            "verifiers": verifiers,
            "document_checker": document_checker,
            "period_key": period_key,
            "period_type": period_type_stored,
            "due_date": due_date,
            "priority": priority,
            "is_billable": is_billable,
            "fees_amount": fees_amount,
        }
        rows.append(TaskParsedRow(row_num=i, data=cleaned if not errors else {}, errors=errors))

    return rows, file_errors
