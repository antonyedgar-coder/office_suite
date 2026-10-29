from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    DEBIT_HEADS,
    HEAD_ASSETS,
    HEAD_EXPENSES,
    HEAD_INCOME,
    HEAD_LIABILITIES,
    SERIES_CN,
    SERIES_DN,
    SERIES_GST,
    SERIES_JV,
    SERIES_NGST,
    series_for_sales_tax_kind,
    sales_series_uses_gst,
    SERIES_PUR,
    SERIES_CV,
    SERIES_PV,
    SERIES_RV,
    VOUCHER_CREDIT_NOTE,
    VOUCHER_DEBIT_NOTE,
    VOUCHER_CONTRA,
    VOUCHER_JOURNAL,
    VOUCHER_PAYMENT,
    VOUCHER_PURCHASE,
    VOUCHER_RECEIPT,
    VOUCHER_SALES,
    Account,
    AccountGroup,
    InvoiceNumberSeq,
    ReceiptAllocation,
    RecoveryAllocation,
    Voucher,
    VoucherLine,
)

TWOPLACES = Decimal("0.01")
OPENING_ALLOC_ID = "opening"

SYSTEM_GROUP_ASSETS = "assets"
SYSTEM_GROUP_DEBTORS = "sundry_debtors"
SYSTEM_GROUP_CREDITORS = "sundry_creditors"
SYSTEM_GROUP_CURRENT_ASSETS = "current_assets"
SYSTEM_GROUP_CURRENT_LIABILITIES = "current_liabilities"
SYSTEM_GROUP_DIRECT_INCOME = "direct_income"
SYSTEM_GROUP_DIRECT_EXPENSES = "direct_expenses"
SYSTEM_GROUP_INCOME = "income"
SYSTEM_GROUP_LIABILITIES = "liabilities"
SYSTEM_INCOME = "professional_income"
SYSTEM_GST_OUTPUT = "gst_output"
SYSTEM_CGST_OUTPUT = "cgst_output"
SYSTEM_SGST_OUTPUT = "sgst_output"
SYSTEM_IGST_OUTPUT = "igst_output"
SYSTEM_CASH = "cash"
SYSTEM_BANK = "bank"
GST_OUTPUT_KEYS = frozenset({SYSTEM_GST_OUTPUT, SYSTEM_CGST_OUTPUT, SYSTEM_SGST_OUTPUT, SYSTEM_IGST_OUTPUT})


def money(value) -> Decimal:
    return Decimal(value or 0).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def default_series_for_type(voucher_type: str, *, with_gst: bool = False, tax_kind: str | None = None) -> str:
    if voucher_type == VOUCHER_SALES:
        return series_for_sales_tax_kind(tax_kind, with_gst=with_gst)
    return {
        VOUCHER_PURCHASE: SERIES_PUR,
        VOUCHER_RECEIPT: SERIES_RV,
        VOUCHER_PAYMENT: SERIES_PV,
        VOUCHER_CONTRA: SERIES_CV,
        VOUCHER_JOURNAL: SERIES_JV,
        VOUCHER_CREDIT_NOTE: SERIES_CN,
        VOUCHER_DEBIT_NOTE: SERIES_DN,
    }[voucher_type]


@transaction.atomic
def allocate_voucher_number(series: str, voucher_date: date) -> str:
    year = voucher_date.year
    month = voucher_date.month
    seq, _ = InvoiceNumberSeq.objects.select_for_update().get_or_create(
        series=series,
        year=year,
        month=month,
        defaults={"last_value": 0},
    )
    seq.last_value += 1
    seq.save(update_fields=["last_value"])
    return f"{series}-{year:04d}-{month:02d}-{seq.last_value:04d}"


SYSTEM_ACCOUNT_NAMES = {
    SYSTEM_INCOME: "Professional income",
    SYSTEM_GST_OUTPUT: "GST output",
    SYSTEM_CGST_OUTPUT: "CGST output",
    SYSTEM_SGST_OUTPUT: "SGST output",
    SYSTEM_IGST_OUTPUT: "IGST output",
    SYSTEM_CASH: "Cash",
    SYSTEM_BANK: "Bank",
}


def seed_chart_of_accounts():
    """Keep only the four Main Heads. Ledgers and nested groups are user-created."""
    assets, _ = AccountGroup.objects.get_or_create(
        system_key=SYSTEM_GROUP_ASSETS,
        defaults={"name": "Assets", "main_head": HEAD_ASSETS},
    )
    assets.main_head = HEAD_ASSETS
    if not assets.name:
        assets.name = "Assets"
    assets.save()
    AccountGroup.objects.get_or_create(
        system_key=SYSTEM_GROUP_LIABILITIES,
        defaults={"name": "Liabilities", "main_head": HEAD_LIABILITIES},
    )
    AccountGroup.objects.get_or_create(
        system_key=SYSTEM_GROUP_INCOME,
        defaults={"name": "Income", "main_head": HEAD_INCOME},
    )
    AccountGroup.objects.get_or_create(
        system_key="expenses",
        defaults={"name": "Expenses", "main_head": HEAD_EXPENSES},
    )
    return assets


def sundry_debtors_group() -> AccountGroup | None:
    group = AccountGroup.account_groups().filter(system_key=SYSTEM_GROUP_DEBTORS).first()
    if group:
        return group
    group = AccountGroup.objects.filter(system_key=SYSTEM_GROUP_DEBTORS).first()
    if group:
        return group
    group = AccountGroup.account_groups().filter(name__iexact="Sundry Debtors").first()
    if group:
        return group
    return AccountGroup.parent_groups().filter(name__iexact="Sundry Debtors").first()


def ensure_sundry_debtors_group() -> AccountGroup:
    """Return Sundry Debtors as an Account Group, creating Current Assets / Sundry Debtors if needed."""
    group = sundry_debtors_group()
    if group is not None:
        return group
    seed_chart_of_accounts()
    assets = AccountGroup.objects.filter(system_key=SYSTEM_GROUP_ASSETS).first()
    if assets is None:
        raise ValidationError("Assets main head is missing. Open Account groups once to seed the chart.")
    current = (
        AccountGroup.objects.filter(system_key=SYSTEM_GROUP_CURRENT_ASSETS).first()
        or AccountGroup.parent_groups().filter(name__iexact="Current Assets", parent=assets).first()
    )
    if current is None:
        current = AccountGroup(
            name="Current Assets",
            parent=assets,
            main_head=HEAD_ASSETS,
            system_key=SYSTEM_GROUP_CURRENT_ASSETS,
        )
        current.full_clean()
        current.save()
    elif not current.system_key:
        current.system_key = SYSTEM_GROUP_CURRENT_ASSETS
        current.save(update_fields=["system_key", "updated_at"])
    group = AccountGroup(
        name="Sundry Debtors",
        parent=current,
        main_head=HEAD_ASSETS,
        system_key=SYSTEM_GROUP_DEBTORS,
    )
    group.full_clean()
    group.save()
    return group


def cash_equivalent_ledgers():
    """Active ledgers under Cash and Cash Equivalents (primary or secondary group)."""
    from django.db.models import Q

    names = ("Cash and Cash Equivalents", "Cash & Cash Equivalents")
    q = Q()
    for name in names:
        q |= Q(group__name__iexact=name) | Q(group__parent__name__iexact=name)
    q |= Q(group__name__icontains="cash and cash equivalent") | Q(
        group__parent__name__icontains="cash and cash equivalent"
    )
    return Account.objects.filter(is_active=True).filter(q).distinct().order_by("name")


def non_cash_ledgers():
    """Active ledgers that are not under Cash and Cash Equivalents."""
    cash_ids = cash_equivalent_ledgers().values_list("pk", flat=True)
    return Account.objects.filter(is_active=True).exclude(pk__in=cash_ids).order_by("name")


def task_master_ledgers():
    """Active ledgers that match a Task Master name or sit under its account group."""
    from django.db.models.functions import Lower

    from tasks.models import TaskMaster

    names = {
        (name or "").strip().lower()
        for name in TaskMaster.objects.values_list("name", flat=True)
        if (name or "").strip()
    }
    if not names:
        return Account.objects.none()
    return (
        Account.objects.filter(is_active=True)
        .annotate(_name_l=Lower("name"), _group_l=Lower("group__name"))
        .filter(Q(_name_l__in=names) | Q(_group_l__in=names))
        .distinct()
        .order_by("name")
    )


def capital_ledgers():
    """Active ledgers under Capital / Capital Account (liabilities)."""
    name_q = (
        Q(group__name__iexact="Capital")
        | Q(group__name__iexact="Capital Account")
        | Q(group__parent__name__iexact="Capital")
        | Q(group__parent__name__iexact="Capital Account")
        | Q(group__name__icontains="capital")
        | Q(group__parent__name__icontains="capital")
    )
    return (
        Account.objects.filter(is_active=True, group__main_head=HEAD_LIABILITIES)
        .filter(name_q)
        .distinct()
        .order_by("name")
    )


def receipt_account_ledgers():
    """Receipt Account tab: Sundry Debtors plus Capital ledgers."""
    return (sundry_debtors_ledgers() | capital_ledgers()).distinct().order_by("name")


def payment_account_ledgers():
    """Payment Account tab: non-cash ledgers excluding Sundry Debtors."""
    debtor_ids = sundry_debtors_ledgers().values_list("pk", flat=True)
    return non_cash_ledgers().exclude(pk__in=debtor_ids)


def pure_agent_ledgers():
    """Active ledgers marked Pure agent."""
    return Account.objects.filter(is_active=True, is_pure_agent=True).order_by("name")


def _folded_label(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def _ledger_match_key(value: str) -> str:
    """Same ledger name, ignoring case, spaces, hyphens, and a leading zero in a number."""
    text = re.sub(r"[^a-z0-9]+", "", (value or "").casefold())
    return re.sub(r"0+(\d)", r"\1", text)


def group_is_direct_income(group) -> bool:
    """True when the ledger's primary group is Direct Income."""
    if group is None or not getattr(group, "pk", None):
        return False
    if group.is_account_group():
        primary = group.parent
    elif group.is_parent_group():
        primary = group
    else:
        return False
    return bool(primary and _folded_label(primary.name) == "direct income")


def ledger_name_matches_task(name: str) -> bool:
    """True when the ledger name is the same as a task master or a task title."""
    from tasks.models import Task, TaskMaster

    key = _folded_label(name)
    if not key:
        return False
    candidates = list(TaskMaster.objects.values_list("name", flat=True))
    candidates.extend(Task.objects.exclude(title="").values_list("title", flat=True))
    return any(_folded_label(item) == key for item in candidates)


def sales_account_ledgers():
    """Sales Account tab: Pure agent ledgers, and ledgers under Direct or Indirect Income."""
    from django.db.models.functions import Lower

    income_names = ("direct income", "indirect income")
    income_q = Q()
    for name in income_names:
        income_q |= Q(_group_l=name) | Q(_parent_l=name)
    return (
        Account.objects.filter(is_active=True)
        .annotate(_group_l=Lower("group__name"), _parent_l=Lower("group__parent__name"))
        .filter(Q(is_pure_agent=True) | income_q)
        .distinct()
        .order_by("name")
    )


def line_account_ledgers(voucher_type: str | None):
    """Account-tab ledgers for invoice-style vouchers."""
    if voucher_type == VOUCHER_SALES:
        return sales_account_ledgers()
    if voucher_type == VOUCHER_RECEIPT:
        return receipt_account_ledgers()
    if voucher_type == VOUCHER_PAYMENT:
        return payment_account_ledgers()
    if voucher_type == VOUCHER_CONTRA:
        return cash_equivalent_ledgers()
    return Account.objects.filter(is_active=True).order_by("name")


def build_receipt_lines(*, mode: Account, items: list[dict]) -> list[dict]:
    """Debit mode of receipt for the total; credit each selected account."""
    if mode is None:
        raise ValidationError("Select the mode of receipt.")
    rows = []
    total = Decimal("0.00")
    for raw in items:
        account = raw.get("account")
        amount = money(raw.get("amount"))
        if not account or amount <= 0:
            continue
        if account.pk == mode.pk:
            raise ValidationError("The mode of receipt and the credited account cannot be the same.")
        total += amount
        rows.append(
            {
                "account": account,
                "debit": Decimal("0.00"),
                "credit": amount,
                "hsn_code": "",
            }
        )
    if not rows:
        raise ValidationError("Enter at least one account and amount.")
    rows.insert(0, {"account": mode, "debit": total, "credit": Decimal("0.00"), "hsn_code": ""})
    return rows


def build_payment_lines(*, mode: Account, items: list[dict]) -> list[dict]:
    """Credit mode of payment for the total; debit each selected account."""
    if mode is None:
        raise ValidationError("Select the mode of payment.")
    rows = []
    total = Decimal("0.00")
    for raw in items:
        account = raw.get("account")
        amount = money(raw.get("amount"))
        if not account or amount <= 0:
            continue
        if account.pk == mode.pk:
            raise ValidationError("The mode of payment and the debited account cannot be the same.")
        total += amount
        rows.append(
            {
                "account": account,
                "debit": amount,
                "credit": Decimal("0.00"),
                "hsn_code": "",
                "is_pure_agent": bool(getattr(account, "is_pure_agent", False)),
            }
        )
    if not rows:
        raise ValidationError("Enter at least one account and amount.")
    rows.insert(0, {"account": mode, "debit": Decimal("0.00"), "credit": total, "hsn_code": ""})
    return rows


def payment_has_pure_agent_debit(lines: list[dict]) -> bool:
    return any(
        row.get("account")
        and getattr(row["account"], "is_pure_agent", False)
        and money(row.get("debit")) > 0
        for row in lines or []
    )


def assign_payment_recovery(voucher: Voucher, *, lines: list[dict], on_behalf_of=None, on_behalf_task=None) -> None:
    if voucher.voucher_type != VOUCHER_PAYMENT or not payment_has_pure_agent_debit(lines):
        voucher.on_behalf_of = None
        voucher.on_behalf_task = None
        return
    if on_behalf_of is None:
        raise ValidationError("Select the client this pure-agent payment is for.")
    if not is_sundry_debtor(on_behalf_of):
        raise ValidationError("Select a client ledger under Sundry Debtors.")
    if on_behalf_task is not None:
        client = getattr(on_behalf_of, "client", None)
        if client is None or on_behalf_task.client_id != client.pk:
            raise ValidationError("The task must belong to the selected client.")
    voucher.on_behalf_of = on_behalf_of
    voucher.on_behalf_task = on_behalf_task


def _recovery_allocated_map(*, ignore_invoice_id=None) -> dict[int, Decimal]:
    from django.db.models import Sum

    qs = RecoveryAllocation.objects.all()
    if ignore_invoice_id:
        qs = qs.exclude(invoice_id=ignore_invoice_id)
    return {
        row["payment_line_id"]: money(row["total"])
        for row in qs.values("payment_line_id").annotate(total=Sum("amount"))
    }


def pending_recovery_rows(*, party=None, task=None, ignore_invoice_id=None) -> list[dict]:
    """Unbilled pure-agent payment debits, optionally for one client ledger or task."""
    qs = (
        VoucherLine.objects.filter(
            voucher__voucher_type=VOUCHER_PAYMENT,
            voucher__on_behalf_of__isnull=False,
            debit__gt=0,
            account__is_pure_agent=True,
        )
        .select_related(
            "voucher",
            "voucher__on_behalf_of",
            "voucher__on_behalf_task",
            "voucher__created_by",
            "account",
        )
        .order_by("voucher__date", "voucher__pk", "pk")
    )
    if party is not None:
        qs = qs.filter(voucher__on_behalf_of=party)
    if task is not None:
        qs = qs.filter(voucher__on_behalf_task=task)
    allocated = _recovery_allocated_map(ignore_invoice_id=ignore_invoice_id)
    rows = []
    for line in qs:
        pending = money(line.debit) - allocated.get(line.pk, Decimal("0.00"))
        if pending <= 0:
            continue
        task_obj = line.voucher.on_behalf_task
        rows.append(
            {
                "id": line.pk,
                "voucher_id": line.voucher_id,
                "number": line.voucher.number,
                "date": line.voucher.date,
                "account": line.account,
                "account_id": line.account_id,
                "account_name": line.account.name,
                "party": line.voucher.on_behalf_of,
                "party_id": line.voucher.on_behalf_of_id,
                "party_name": line.voucher.on_behalf_of.name if line.voucher.on_behalf_of_id else "",
                "task_id": task_obj.pk if task_obj else None,
                "task_label": (
                    f"{task_obj.display_title} ({task_obj.period_key})" if task_obj else ""
                ),
                "amount": money(line.debit),
                "billed": allocated.get(line.pk, Decimal("0.00")),
                "pending": pending,
                "created_by": line.voucher.created_by,
            }
        )
    return rows


def pending_recovery_sections(*, party=None, task=None) -> dict:
    rows = pending_recovery_rows(party=party, task=task)
    sections = []
    grand = Decimal("0.00")
    grouped: dict[int, list[dict]] = {}
    names: dict[int, str] = {}
    for row in rows:
        grouped.setdefault(row["party_id"], []).append(row)
        names[row["party_id"]] = row["party_name"]
    sl = 0
    for party_id, party_rows in grouped.items():
        total = sum((row["pending"] for row in party_rows), Decimal("0.00"))
        grand += total
        numbered = []
        for row in party_rows:
            sl += 1
            numbered.append({**row, "sl_no": sl})
        sections.append(
            {
                "party_id": party_id,
                "name": names[party_id],
                "rows": numbered,
                "total": total,
            }
        )
    return {"sections": sections, "grand_total": grand, "rows": rows}


def apply_recovery_allocations(invoice: Voucher, items: list[dict] | None) -> None:
    RecoveryAllocation.objects.filter(invoice=invoice).delete()
    if invoice.voucher_type != VOUCHER_SALES or not items:
        return
    party_line = next((ln for ln in invoice.lines.all() if money(ln.debit) > 0), None)
    party = party_line.account if party_line else None
    used: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))

    def remaining_for(line: VoucherLine) -> Decimal:
        allocated = _recovery_allocated_map(ignore_invoice_id=invoice.pk).get(line.pk, Decimal("0.00"))
        return money(line.debit) - allocated - used[line.pk]

    for raw in items:
        account = raw.get("account")
        amount = money(raw.get("amount"))
        if not account or amount <= 0 or not getattr(account, "is_pure_agent", False):
            continue
        leftover = amount
        recovery_id = raw.get("recovery_line") or ""
        if str(recovery_id).strip().isdigit():
            line = (
                VoucherLine.objects.select_related("voucher", "account")
                .filter(pk=int(recovery_id), account=account, voucher__voucher_type=VOUCHER_PAYMENT)
                .first()
            )
            if line is None:
                raise ValidationError("Select a valid pending recovery.")
            if party and line.voucher.on_behalf_of_id not in (None, party.pk):
                raise ValidationError("That recovery belongs to a different client.")
            take = min(leftover, remaining_for(line))
            if take <= 0:
                raise ValidationError("That recovery has already been billed.")
            RecoveryAllocation.objects.create(invoice=invoice, payment_line=line, amount=take)
            used[line.pk] += take
            leftover -= take
        if leftover <= 0:
            continue
        for row in pending_recovery_rows(party=party, ignore_invoice_id=invoice.pk):
            if leftover <= 0:
                break
            if row["account_id"] != account.pk:
                continue
            line = VoucherLine.objects.filter(pk=row["id"]).first()
            if line is None:
                continue
            take = min(leftover, remaining_for(line))
            if take <= 0:
                continue
            RecoveryAllocation.objects.create(invoice=invoice, payment_line=line, amount=take)
            used[line.pk] += take
            leftover -= take


def build_contra_lines(*, receivers: list[dict], payers: list[dict]) -> list[dict]:
    """Debit receiver lines; credit payer lines. Cash ledgers only; totals must match."""
    recv_rows = []
    pay_rows = []
    recv_total = Decimal("0.00")
    pay_total = Decimal("0.00")
    seen_recv = set()
    seen_pay = set()
    for raw in receivers:
        account = raw.get("account")
        amount = money(raw.get("amount"))
        if not account or amount <= 0:
            continue
        if account.pk in seen_recv:
            raise ValidationError("The same account cannot appear twice under Receiver.")
        seen_recv.add(account.pk)
        recv_total += amount
        recv_rows.append(
            {"account": account, "debit": amount, "credit": Decimal("0.00"), "hsn_code": ""}
        )
    for raw in payers:
        account = raw.get("account")
        amount = money(raw.get("amount"))
        if not account or amount <= 0:
            continue
        if account.pk in seen_pay:
            raise ValidationError("The same account cannot appear twice under Payer.")
        seen_pay.add(account.pk)
        pay_total += amount
        pay_rows.append(
            {"account": account, "debit": Decimal("0.00"), "credit": amount, "hsn_code": ""}
        )
    if not recv_rows:
        raise ValidationError("Enter at least one receiver account and amount.")
    if not pay_rows:
        raise ValidationError("Enter at least one payer account and amount.")
    overlap = seen_recv & seen_pay
    if overlap:
        raise ValidationError("Receiver and payer cannot use the same account ledger.")
    if recv_total != pay_total:
        raise ValidationError("Receiver total and payer total must be the same.")
    return recv_rows + pay_rows


def _sales_invoice_amount_for_party(voucher: Voucher, party: Account) -> Decimal:
    total = Decimal("0.00")
    for line in voucher.lines.all():
        if line.account_id == party.pk:
            total += money(line.debit)
    return total


def _purchase_invoice_amount_for_party(voucher: Voucher, party: Account) -> Decimal:
    total = Decimal("0.00")
    for line in voucher.lines.all():
        if line.account_id == party.pk:
            total += money(line.credit)
    return total


def _opening_knocked(account: Account, ignore_receipt_id=None) -> Decimal:
    from django.db.models import Sum

    qs = ReceiptAllocation.objects.filter(party=account, is_opening=True, is_advance=False)
    if ignore_receipt_id:
        qs = qs.exclude(receipt_id=ignore_receipt_id)
    return money(qs.aggregate(total=Sum("amount"))["total"])


def _opening_outstanding(account: Account, used: dict | None = None, ignore_receipt_id=None) -> Decimal:
    opening_dr, _opening_cr = opening_debit_credit(account)
    if opening_dr <= 0:
        return Decimal("0.00")
    remaining = (
        opening_dr
        - _opening_knocked(account, ignore_receipt_id=ignore_receipt_id)
        - money((used or {}).get(OPENING_ALLOC_ID))
    )
    return remaining if remaining > 0 else Decimal("0.00")


def _opening_credit_outstanding(account: Account, used: dict | None = None, ignore_receipt_id=None) -> Decimal:
    _opening_dr, opening_cr = opening_debit_credit(account)
    if opening_cr <= 0:
        return Decimal("0.00")
    remaining = (
        opening_cr
        - _opening_knocked(account, ignore_receipt_id=ignore_receipt_id)
        - money((used or {}).get(OPENING_ALLOC_ID))
    )
    return remaining if remaining > 0 else Decimal("0.00")


def outstanding_bills_for_account(account: Account, ignore_receipt_id=None) -> list[dict]:
    """Opening debit (if any) then open sales invoices, less receipts already knocked off."""
    from django.db.models import Sum

    rows = []
    opening = _opening_outstanding(account, ignore_receipt_id=ignore_receipt_id)
    if opening > 0:
        dr, _cr = opening_debit_credit(account)
        rows.append(
            {
                "id": OPENING_ALLOC_ID,
                "number": "Opening balance",
                "date": "",
                "invoice_amount": dr,
                "outstanding": opening,
                "is_opening": True,
            }
        )
    vouchers = list(
        Voucher.objects.filter(
            voucher_type=VOUCHER_SALES,
            lines__account=account,
            lines__debit__gt=0,
        )
        .distinct()
        .prefetch_related("lines")
        .order_by("date", "pk")
    )
    applied_qs = ReceiptAllocation.objects.filter(against__in=vouchers, is_advance=False, is_opening=False)
    if ignore_receipt_id:
        applied_qs = applied_qs.exclude(receipt_id=ignore_receipt_id)
    applied = {row["against_id"]: money(row["total"]) for row in applied_qs.values("against_id").annotate(total=Sum("amount"))}
    for voucher in vouchers:
        invoice_amount = _sales_invoice_amount_for_party(voucher, account)
        outstanding = invoice_amount - applied.get(voucher.pk, Decimal("0.00"))
        if outstanding <= 0:
            continue
        rows.append(
            {
                "id": voucher.pk,
                "number": voucher.number,
                "date": voucher.date.isoformat(),
                "invoice_amount": invoice_amount,
                "outstanding": outstanding,
                "is_opening": False,
            }
        )
    return rows


def _parse_bill_date(value):
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def due_for_label(bill_date, as_on) -> str:
    if not bill_date or not as_on:
        return "—"
    days = (as_on - bill_date).days
    if days < 0:
        days = 0
    if days == 1:
        return "1 Day"
    return f"{days} Days"


def billwise_outstanding_sections(*, as_on=None) -> dict:
    """Open sales bills for every Sundry Debtors ledger, grouped by debtor name."""
    as_on = as_on or timezone.localdate()
    sections = []
    grand_total = Decimal("0.00")
    for account in sundry_debtors_ledgers().prefetch_related("group", "group__parent"):
        rows = []
        total = Decimal("0.00")
        sl_no = 0
        for bill in outstanding_bills_for_account(account):
            bill_date = None if bill.get("is_opening") else _parse_bill_date(bill.get("date"))
            if bill_date and bill_date > as_on:
                continue
            amount = money(bill.get("outstanding"))
            if amount <= 0:
                continue
            sl_no += 1
            total += amount
            rows.append(
                {
                    "sl_no": sl_no,
                    "date": bill_date,
                    "number": bill.get("number") or "",
                    "outstanding": amount,
                    "due_for": due_for_label(bill_date, as_on),
                    "voucher_id": None if bill.get("is_opening") else bill.get("id"),
                }
            )
        if not rows:
            continue
        sections.append({"account": account, "name": account.name, "rows": rows, "total": total})
        grand_total += total
    return {"sections": sections, "grand_total": grand_total, "as_on": as_on}


def outstanding_purchase_bills_for_account(account: Account, ignore_receipt_id=None) -> list[dict]:
    """Opening credit (if any) then open purchase invoices, less knock-off already applied."""
    from django.db.models import Sum

    rows = []
    opening = _opening_credit_outstanding(account, ignore_receipt_id=ignore_receipt_id)
    if opening > 0:
        _dr, cr = opening_debit_credit(account)
        rows.append(
            {
                "id": OPENING_ALLOC_ID,
                "number": "Opening balance",
                "date": "",
                "invoice_amount": cr,
                "outstanding": opening,
                "is_opening": True,
            }
        )
    vouchers = list(
        Voucher.objects.filter(
            voucher_type=VOUCHER_PURCHASE,
            lines__account=account,
            lines__credit__gt=0,
        )
        .distinct()
        .prefetch_related("lines")
        .order_by("date", "pk")
    )
    applied_qs = ReceiptAllocation.objects.filter(against__in=vouchers, is_advance=False, is_opening=False)
    if ignore_receipt_id:
        applied_qs = applied_qs.exclude(receipt_id=ignore_receipt_id)
    applied = {
        row["against_id"]: money(row["total"])
        for row in applied_qs.values("against_id").annotate(total=Sum("amount"))
    }
    for voucher in vouchers:
        invoice_amount = _purchase_invoice_amount_for_party(voucher, account)
        outstanding = invoice_amount - applied.get(voucher.pk, Decimal("0.00"))
        if outstanding <= 0:
            continue
        rows.append(
            {
                "id": voucher.pk,
                "number": voucher.number,
                "date": voucher.date.isoformat(),
                "invoice_amount": invoice_amount,
                "outstanding": outstanding,
                "is_opening": False,
            }
        )
    return rows


def outstanding_party_bills_for_note(account: Account, ignore_receipt_id=None) -> list[dict]:
    """Bills to knock off on a credit or debit note for Sundry Debtors / Creditors."""
    if is_sundry_creditor(account):
        return outstanding_purchase_bills_for_account(account, ignore_receipt_id=ignore_receipt_id)
    if is_sundry_debtor(account):
        return outstanding_bills_for_account(account, ignore_receipt_id=ignore_receipt_id)
    return []


def _fifo_allocate(account: Account, amount: Decimal, used: dict | None = None) -> dict:
    remaining = money(amount)
    bills = []
    used = used or {}
    for bill in outstanding_bills_for_account(account):
        if remaining <= 0:
            break
        available = money(bill["outstanding"]) - money(used.get(bill["id"]))
        if available <= 0:
            continue
        take = min(remaining, available)
        bills.append({"id": bill["id"], "amount": take})
        remaining -= take
    return {"bills": bills, "advance": remaining, "as_advance": not bills and remaining > 0}


def parse_receipt_allocation_payload(raw) -> dict | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, dict):
        data = raw
    else:
        import json

        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            raise ValidationError("Bill-wise details are not valid.")
    if not isinstance(data, dict):
        raise ValidationError("Bill-wise details are not valid.")
    return data


def resolve_receipt_allocations(
    *,
    account: Account,
    amount: Decimal,
    payload: dict | None,
    used: dict | None = None,
    against_type: str = VOUCHER_SALES,
) -> list[dict]:
    """Turn UI JSON into allocation rows. Empty payload uses FIFO, leftover is advance."""
    amount = money(amount)
    used = used or {}
    if amount <= 0:
        return []
    bill_rows = (
        outstanding_purchase_bills_for_account(account)
        if against_type == VOUCHER_PURCHASE
        else outstanding_bills_for_account(account)
    )
    data = payload
    if data is None:
        data = _fifo_allocate(account, amount, used)
        if against_type == VOUCHER_PURCHASE:
            remaining = money(amount)
            bills = []
            for bill in bill_rows:
                if remaining <= 0:
                    break
                available = money(bill["outstanding"]) - money(used.get(bill["id"]))
                if available <= 0:
                    continue
                take = min(remaining, available)
                bills.append({"id": bill["id"], "amount": take})
                remaining -= take
            data = {"bills": bills, "advance": remaining, "as_advance": not bills and remaining > 0}
    as_advance = bool(data.get("as_advance"))
    bills_in = data.get("bills") or []
    advance = money(data.get("advance"))
    outstanding = {bill["id"]: money(bill["outstanding"]) for bill in bill_rows}
    rows = []
    billed = Decimal("0.00")
    if as_advance:
        if amount > 0:
            rows.append({"against": None, "amount": amount, "is_advance": True, "is_opening": False})
        return rows
    seen = set()
    for raw in bills_in:
        if not isinstance(raw, dict):
            continue
        raw_id = raw.get("id")
        take = money(raw.get("amount"))
        if take <= 0:
            continue
        is_opening = str(raw_id).strip().lower() == OPENING_ALLOC_ID
        if is_opening:
            bill_id = OPENING_ALLOC_ID
        else:
            try:
                bill_id = int(raw_id)
            except (TypeError, ValueError):
                raise ValidationError("Select a bill to knock off.")
        if bill_id in seen:
            raise ValidationError("The same bill cannot be knocked off twice on one line.")
        seen.add(bill_id)
        available = outstanding.get(bill_id, Decimal("0.00")) - money(used.get(bill_id))
        if available <= 0:
            raise ValidationError("That bill has no outstanding balance.")
        if take > available:
            raise ValidationError("Knock-off cannot exceed the outstanding on a bill.")
        if is_opening:
            rows.append({"against": None, "amount": take, "is_advance": False, "is_opening": True})
        else:
            voucher = Voucher.objects.filter(pk=bill_id, voucher_type=against_type).first()
            if voucher is None:
                raise ValidationError("Select a valid bill to knock off.")
            rows.append({"against": voucher, "amount": take, "is_advance": False, "is_opening": False})
        billed += take
    leftover = money(amount - billed)
    if leftover < 0:
        raise ValidationError("Knock-off amounts cannot exceed the receipt amount.")
    if leftover > 0:
        rows.append({"against": None, "amount": leftover, "is_advance": True, "is_opening": False})
    elif advance > 0 and billed == amount:
        pass
    if not rows:
        rows.append({"against": None, "amount": amount, "is_advance": True, "is_opening": False})
    return rows


def pending_advance_rows(*, party, ignore_invoice_id=None) -> list[dict]:
    """Advance slices for a client. While editing a bill, include the amount already knocked to it."""
    if party is None:
        return []
    qs = ReceiptAllocation.objects.filter(party=party, is_opening=False).select_related("receipt")
    if ignore_invoice_id:
        qs = qs.filter(
            Q(is_advance=True, against__isnull=True) | Q(against_id=ignore_invoice_id, is_advance=False)
        )
    else:
        qs = qs.filter(is_advance=True, against__isnull=True)
    rows = []
    for row in qs.order_by("receipt__date", "receipt_id", "pk"):
        rows.append(
            {
                "id": row.pk,
                "number": row.receipt.number,
                "date": row.receipt.date,
                "pending": money(row.amount),
                "selected": bool(ignore_invoice_id and row.against_id == ignore_invoice_id),
            }
        )
    return rows


def receipt_allocation_snapshot(*, receipt_id: int, party) -> dict:
    """Knock-off amounts already stored on this receipt, so editing it does not refill the bills."""
    knocks: dict[str, str] = {}
    advance = Decimal("0.00")
    knocked_a_bill = False
    for row in ReceiptAllocation.objects.filter(receipt_id=receipt_id, party=party):
        if row.is_advance:
            advance += money(row.amount)
            continue
        if row.is_opening:
            knocks[OPENING_ALLOC_ID] = str(money(row.amount))
            knocked_a_bill = True
        elif row.against_id:
            knocks[str(row.against_id)] = str(money(row.amount))
            knocked_a_bill = True
    return {
        "receipt_knocks": knocks,
        "receipt_as_advance": advance > 0 and not knocked_a_bill,
    }


def release_invoice_receipt_knocks(invoice: Voucher) -> None:
    """Put amounts knocked to this bill back on the receipt as advance."""
    ReceiptAllocation.objects.filter(against=invoice, is_advance=False, is_opening=False).update(
        against=None,
        is_advance=True,
    )


def apply_sales_advance_knocks(invoice: Voucher, selections: list[dict] | None) -> None:
    """Knock selected advance receipts against this sales invoice. Unselected advances stay pending."""
    if invoice.voucher_type != VOUCHER_SALES or not selections:
        return
    party_line = next((ln for ln in invoice.lines.all() if money(ln.debit) > 0), None)
    if party_line is None:
        raise ValidationError("Select a buyer.")
    party = party_line.account
    invoice_total = money(party_line.debit)
    used = Decimal("0.00")
    seen: set[int] = set()
    for raw in selections:
        try:
            alloc_id = int(raw.get("id"))
        except (TypeError, ValueError):
            raise ValidationError("Select a valid advance receipt.")
        amount = money(raw.get("amount"))
        if amount <= 0:
            continue
        if alloc_id in seen:
            raise ValidationError("The same advance cannot be used twice on one bill.")
        seen.add(alloc_id)
        alloc = (
            ReceiptAllocation.objects.select_for_update()
            .filter(pk=alloc_id, party=party, is_advance=True, is_opening=False, against__isnull=True)
            .first()
        )
        if alloc is None:
            raise ValidationError("Select a valid advance receipt.")
        if amount > money(alloc.amount):
            raise ValidationError("Knock-off cannot exceed the advance on that receipt.")
        if used + amount > invoice_total:
            raise ValidationError("Advance knock-off cannot exceed the invoice total.")
        if amount == money(alloc.amount):
            alloc.is_advance = False
            alloc.against = invoice
            alloc.save(update_fields=["is_advance", "against"])
        else:
            alloc.amount = money(alloc.amount - amount)
            alloc.save(update_fields=["amount"])
            ReceiptAllocation.objects.create(
                receipt=alloc.receipt,
                party=party,
                against=invoice,
                amount=amount,
                is_advance=False,
                is_opening=False,
            )
        used += amount


def apply_receipt_allocations(receipt: Voucher, items: list[dict]) -> None:
    used: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for raw in items:
        account = raw.get("account")
        amount = money(raw.get("amount"))
        if not account or amount <= 0:
            continue
        if not is_sundry_debtor(account) and not is_sundry_creditor(account):
            continue
        payload = parse_receipt_allocation_payload(raw.get("bill_alloc"))
        against_type = VOUCHER_PURCHASE if is_sundry_creditor(account) else VOUCHER_SALES
        for row in resolve_receipt_allocations(
            account=account,
            amount=amount,
            payload=payload,
            used=used,
            against_type=against_type,
        ):
            ReceiptAllocation.objects.create(
                receipt=receipt,
                party=account,
                against=row["against"],
                amount=row["amount"],
                is_advance=row["is_advance"],
                is_opening=row.get("is_opening", False),
            )
            if row.get("is_opening"):
                used[OPENING_ALLOC_ID] += row["amount"]
            elif row["against"] is not None:
                used[row["against"].pk] += row["amount"]


def sundry_debtors_ledgers():
    """Active Account Ledger rows under Sundry Debtors (primary or secondary)."""
    from django.db.models import Q

    return (
        Account.objects.filter(is_active=True)
        .filter(
            Q(group__system_key=SYSTEM_GROUP_DEBTORS)
            | Q(group__parent__system_key=SYSTEM_GROUP_DEBTORS)
            | Q(group__name__iexact="Sundry Debtors")
            | Q(group__parent__name__iexact="Sundry Debtors")
        )
        .distinct()
        .order_by("name")
    )


def sundry_creditors_ledgers():
    """Active Account Ledger rows under Sundry Creditors (primary or secondary)."""
    from django.db.models import Q

    return (
        Account.objects.filter(is_active=True)
        .filter(
            Q(group__system_key=SYSTEM_GROUP_CREDITORS)
            | Q(group__parent__system_key=SYSTEM_GROUP_CREDITORS)
            | Q(group__name__iexact="Sundry Creditors")
            | Q(group__parent__name__iexact="Sundry Creditors")
        )
        .distinct()
        .order_by("name")
    )


def is_sundry_debtor(account: Account | None) -> bool:
    return bool(account and sundry_debtors_ledgers().filter(pk=account.pk).exists())


def is_sundry_creditor(account: Account | None) -> bool:
    return bool(account and sundry_creditors_ledgers().filter(pk=account.pk).exists())


def delete_parent_and_account_groups() -> int:
    """Remove all Parent Group and Account Group rows. Main Heads are kept."""
    seed_chart_of_accounts()
    head_by_nature = {g.main_head: g for g in AccountGroup.main_heads()}
    to_move = Account.objects.exclude(group__parent__isnull=True).select_related("group", "group__parent")
    for acc in to_move:
        head = head_by_nature.get(acc.group.resolved_main_head())
        if head:
            acc.group = head
            acc.save(update_fields=["group", "updated_at"])
    deleted_account_groups, _ = AccountGroup.account_groups().delete()
    deleted_parent_groups, _ = AccountGroup.parent_groups().delete()
    return deleted_account_groups + deleted_parent_groups


def account_by_key(key: str) -> Account:
    acc = Account.objects.filter(system_key=key, is_active=True).first()
    if acc:
        return acc
    name = SYSTEM_ACCOUNT_NAMES.get(key)
    if name:
        acc = Account.objects.filter(name__iexact=name, is_active=True).first()
        if acc:
            return acc
        raise ValidationError(f"Create an account named {name} in Account Ledger first.")
    raise ValidationError(f"Missing account {key}.")


def sync_client_account(client) -> Account | None:
    if not getattr(client, "pk", None):
        return None
    from masters.models import Client

    if getattr(client, "approval_status", None) and client.approval_status != Client.APPROVED:
        existing = Account.objects.filter(client=client).first()
        return existing
    group = ensure_sundry_debtors_group()
    acc = Account.objects.filter(client=client).first()
    name = (client.client_name or "").strip() or f"Client {client.pk}"
    if acc is None:
        acc = Account(client=client, group=group, name=name)
    acc.name = name
    acc.address = (client.address or "")[:255]
    acc.gstin = (client.gstin or "")[:15]
    acc.pan = (client.pan or "")[:10]
    acc.group = group
    acc.full_clean()
    acc.save()
    return acc


def backfill_approved_client_ledgers(*, dry_run: bool = False) -> dict:
    """One-time: create Sundry Debtor ledgers for approved Client Master rows.

    Unapproved clients are skipped. Opening balance stays at zero.
    Already-linked ledgers are refreshed from Client Master (name, GSTIN, PAN, address).
    """
    from masters.models import Client

    approved = Client.objects.filter(approval_status=Client.APPROVED).order_by("client_name")
    skipped_unapproved = Client.objects.exclude(approval_status=Client.APPROVED).count()
    created = 0
    updated = 0
    errors: list[str] = []
    if not dry_run:
        ensure_sundry_debtors_group()
    for client in approved.iterator():
        existing = Account.objects.filter(client=client).first()
        if dry_run:
            if existing is None:
                created += 1
            else:
                updated += 1
            continue
        try:
            was_new = existing is None
            sync_client_account(client)
            if was_new:
                created += 1
            else:
                updated += 1
        except ValidationError as exc:
            errors.append(f"{client.client_id}: {exc}")
    return {
        "approved": approved.count(),
        "created": created,
        "updated": updated,
        "skipped_unapproved": skipped_unapproved,
        "errors": errors,
        "dry_run": dry_run,
    }


def ensure_direct_income_group() -> AccountGroup:
    """Primary group Direct Income under the Income main head."""
    seed_chart_of_accounts()
    income = AccountGroup.objects.filter(system_key=SYSTEM_GROUP_INCOME).first()
    if income is None:
        raise ValidationError("Income main head is missing. Open Account groups once to seed the chart.")
    existing = AccountGroup.parent_groups().filter(parent=income, name__iexact="Direct Income").first()
    if existing is None:
        existing = AccountGroup.parent_groups().filter(name__iexact="Direct Income").first()
    if existing is not None:
        return existing
    group = AccountGroup(name="Direct Income", parent=income, main_head=income.resolved_main_head())
    group.full_clean()
    group.save()
    return group


def _account_group_under_direct_income(primary: AccountGroup, name: str) -> AccountGroup:
    label = (name or "").strip()
    if not label:
        raise ValidationError("Task group name is required to place the ledger.")
    found = (
        AccountGroup.account_groups()
        .filter(parent=primary, name__iexact=label)
        .order_by("pk")
        .first()
    )
    if found is not None:
        return found
    group = AccountGroup(name=label, parent=primary, main_head=primary.resolved_main_head())
    group.full_clean()
    group.save()
    return group


def _direct_income_ledgers():
    return Account.objects.filter(
        Q(group__name__iexact="Direct Income") | Q(group__parent__name__iexact="Direct Income")
    )


def backfill_task_master_ledgers(*, dry_run: bool = False) -> dict:
    """One-time: one Direct Income ledger per Task Master.

    The ledger uses the Task Master name. Its account group is the Task Group.
    A ledger already under Direct Income with the same name is left as it is.
    """
    from tasks.models import TaskMaster

    masters = list(
        TaskMaster.objects.select_related("task_group").order_by("task_group__name", "name")
    )
    direct = None if dry_run else ensure_direct_income_group()
    existing_keys = {_ledger_match_key(name) for name in _direct_income_ledgers().values_list("name", flat=True)}
    pending: list[str] = []
    created: list[str] = []
    already = 0
    errors: list[str] = []
    for master in masters:
        key = _ledger_match_key(master.name)
        if not key:
            errors.append(f"{master.pk}: Task Master has no name.")
            continue
        if key in existing_keys:
            already += 1
            continue
        if dry_run:
            pending.append(master.name)
            existing_keys.add(key)
            continue
        try:
            account_group = _account_group_under_direct_income(direct, master.task_group.name)
            account = Account(
                name=(master.name or "").strip(),
                group=account_group,
                is_active=bool(master.is_active),
            )
            account.full_clean()
            account.save()
            created.append(account.name)
            existing_keys.add(key)
        except ValidationError as exc:
            errors.append(f"{master.name}: {exc}")
    return {
        "task_masters": len(masters),
        "already_present": already,
        "pending": pending,
        "created": len(created),
        "created_names": created,
        "errors": errors,
        "dry_run": dry_run,
    }


def _validate_lines(lines: list[dict]) -> list[dict]:
    cleaned = []
    debit_t = Decimal("0.00")
    credit_t = Decimal("0.00")
    for raw in lines:
        account = raw.get("account")
        if not account:
            continue
        debit = money(raw.get("debit"))
        credit = money(raw.get("credit"))
        if debit and credit:
            raise ValidationError("A line cannot have both debit and credit.")
        if not debit and not credit:
            continue
        cleaned.append(
            {
                "account": account,
                "debit": debit,
                "credit": credit,
                "hsn_code": (raw.get("hsn_code") or "")[:16],
                "is_pure_agent": bool(raw.get("is_pure_agent")),
            }
        )
        debit_t += debit
        credit_t += credit
    if len(cleaned) < 2:
        raise ValidationError("Enter at least two voucher lines.")
    if debit_t != credit_t:
        raise ValidationError("Total debit must equal total credit.")
    if debit_t <= 0:
        raise ValidationError("Voucher amount must be greater than zero.")
    return cleaned


def gstin_state_code(gstin: str) -> str:
    value = (gstin or "").strip().upper()
    code = value[:2]
    return code if len(code) == 2 and code.isdigit() else ""


def company_gstin() -> str:
    from core.site_settings import get_site_settings

    return (getattr(get_site_settings(), "gstin", None) or "").strip().upper()


def is_intra_state_sale(buyer_gstin: str, office_gstin: str | None = None) -> bool:
    office = gstin_state_code(office_gstin if office_gstin is not None else company_gstin())
    if not office:
        raise ValidationError("Set the company GST No in Settings → Company branding before raising a GST invoice.")
    buyer = gstin_state_code(buyer_gstin)
    if not buyer:
        return True
    return buyer == office


def _split_gst_amount(gst_amt: Decimal, *, intra: bool) -> tuple[Decimal, Decimal, Decimal]:
    if gst_amt <= 0:
        return Decimal("0.00"), Decimal("0.00"), Decimal("0.00")
    if intra:
        cgst = money(gst_amt / Decimal("2"))
        sgst = gst_amt - cgst
        return cgst, sgst, Decimal("0.00")
    return Decimal("0.00"), Decimal("0.00"), gst_amt


def format_gst_rate_label(rate: Decimal) -> str:
    quantized = money(rate)
    text = format(quantized, "f").rstrip("0").rstrip(".")
    return text or "0"


def _gst_output_ledgers():
    return Account.objects.filter(is_active=True).filter(
        Q(group__name__iexact="GST Output") | Q(group__parent__name__iexact="GST Output")
    )


def _gst_output_group() -> AccountGroup:
    seed_chart_of_accounts()
    liabilities = AccountGroup.objects.filter(system_key=SYSTEM_GROUP_LIABILITIES).first()
    if liabilities is None:
        raise ValidationError("Liabilities main head is missing. Open Account groups once to seed the chart.")
    group = (
        AccountGroup.objects.filter(name__iexact="GST Output", parent=liabilities).first()
        or AccountGroup.parent_groups().filter(name__iexact="GST Output").first()
    )
    if group:
        return group
    group = AccountGroup(name="GST Output", parent=liabilities, main_head=HEAD_LIABILITIES)
    group.full_clean()
    group.save()
    return group


def find_gst_output_ledger(kind: str, component_rate: Decimal) -> Account:
    """CGST Output 9%, SGST Output 9%, IGST Output 18% under the GST Output group."""
    kind = (kind or "").strip().upper()
    label = format_gst_rate_label(component_rate)
    expected = f"{kind} Output {label}%"
    wanted = " ".join(expected.split()).casefold()
    rate = money(component_rate)
    candidates = list(_gst_output_ledgers())
    if not candidates:
        candidates = list(Account.objects.filter(is_active=True))

    def norm(name: str) -> str:
        return " ".join((name or "").split()).casefold()

    for acc in candidates:
        if norm(acc.name) == wanted:
            return acc
    for acc in candidates:
        name = (acc.name or "").casefold()
        if kind.lower() not in name or "output" not in name:
            continue
        if acc.gst_rate is not None and money(acc.gst_rate) == rate:
            return acc
    group = _gst_output_group()
    acc = Account(name=expected, group=group, gst_rate=rate)
    acc.full_clean()
    acc.save()
    return acc


GST_OUTPUT_NAME_RE = re.compile(r"(CGST|SGST|IGST)\s+Output\s+([\d.]+)\s*%", re.I)
GSTIN_STATE_NAMES = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
}
_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"]
_TEENS = ["Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
_KIND_ORDER = {"CGST": 0, "SGST": 1, "IGST": 2}


def format_indian_money(value) -> str:
    amount = money(value)
    negative = amount < 0
    amount = abs(amount)
    whole, frac = f"{amount:.2f}".split(".")
    last3 = whole[-3:]
    rest = whole[:-3]
    groups = []
    while rest:
        groups.append(rest[-2:])
        rest = rest[:-2]
    grouped = ",".join(list(reversed(groups)) + [last3]) if groups else last3
    text = f"{grouped}.{frac}"
    return f"-{text}" if negative else text


def _two_digit_words(n: int) -> str:
    if n < 10:
        return _ONES[n]
    if n < 20:
        return _TEENS[n - 10]
    tens, ones = divmod(n, 10)
    return (_TENS[tens] + (" " + _ONES[ones] if ones else "")).strip()


def _three_digit_words(n: int) -> str:
    hundred, rest = divmod(n, 100)
    parts = []
    if hundred:
        parts.append(_ONES[hundred] + " Hundred")
    if rest:
        parts.append(_two_digit_words(rest))
    return " ".join(parts)


def amount_in_indian_words(value) -> str:
    amount = money(value)
    rupees = int(amount)
    paise = int((amount - Decimal(rupees)) * 100)
    if rupees == 0 and paise == 0:
        return "Rupees Zero Only"
    crore, rem = divmod(rupees, 10000000)
    lakh, rem = divmod(rem, 100000)
    thousand, rem = divmod(rem, 1000)
    parts = []
    if crore:
        parts.append(_three_digit_words(crore) + " Crore")
    if lakh:
        parts.append(_two_digit_words(lakh) + " Lakh")
    if thousand:
        parts.append(_two_digit_words(thousand) + " Thousand")
    if rem:
        parts.append(_three_digit_words(rem))
    rupee_words = " ".join(parts) if parts else "Zero"
    if paise:
        return f"Rupees {rupee_words} and Paise {_two_digit_words(paise)} Only"
    return f"Rupees {rupee_words} Only"


def is_gst_output_account(account: Account) -> bool:
    group = getattr(account, "group", None)
    if group is not None:
        names = [(group.name or "").strip().casefold()]
        parent = getattr(group, "parent", None)
        if parent is not None:
            names.append((parent.name or "").strip().casefold())
        if "gst output" in names:
            return True
    return bool(GST_OUTPUT_NAME_RE.search(account.name or ""))


def _parse_gst_output_row(account: Account, amount: Decimal) -> dict | None:
    if amount <= 0 or not is_gst_output_account(account):
        return None
    match = GST_OUTPUT_NAME_RE.search(account.name or "")
    if match:
        kind = match.group(1).upper()
        rate = money(match.group(2))
    else:
        name = (account.name or "").upper()
        if "IGST" in name:
            kind = "IGST"
        elif "SGST" in name:
            kind = "SGST"
        elif "CGST" in name:
            kind = "CGST"
        else:
            return None
        rate = money(account.gst_rate) if account.gst_rate is not None else Decimal("0.00")
    label = f"{kind} {format_gst_rate_label(rate)}%"
    return {"kind": kind, "rate": rate, "label": label, "amount": amount}


def sales_invoice_document(voucher: Voucher) -> dict:
    """Client-facing sales invoice: line amounts, GST summarised by rate, then grand total."""
    from core.site_settings import get_site_settings
    from django.urls import reverse

    lines = list(voucher.lines.select_related("account", "account__group", "account__group__parent").all())
    buyer_line = next((ln for ln in lines if money(ln.debit) > 0), None)
    buyer = buyer_line.account if buyer_line else None
    items = []
    tax_map: dict[tuple[str, Decimal], Decimal] = defaultdict(lambda: Decimal("0.00"))
    taxable = Decimal("0.00")
    for ln in lines:
        credit = money(ln.credit)
        if credit <= 0:
            continue
        parsed = _parse_gst_output_row(ln.account, credit)
        if parsed:
            key = (parsed["kind"], parsed["rate"])
            tax_map[key] += parsed["amount"]
            continue
        taxable += credit
        items.append(
            {
                "description": ln.account.name,
                "hsn": (ln.hsn_code or getattr(ln.account, "hsn_code", None) or ""),
                "amount": credit,
                "amount_display": format_indian_money(credit),
                "is_pure_agent": bool(ln.is_pure_agent),
            }
        )
    tax_rows = []
    gst_total = Decimal("0.00")
    for (kind, rate), amt in sorted(
        tax_map.items(),
        key=lambda item: (_KIND_ORDER.get(item[0][0], 9), item[0][1], item[0][0]),
    ):
        if amt <= 0:
            continue
        gst_total += amt
        tax_rows.append(
            {
                "kind": kind,
                "rate": rate,
                "label": f"{kind} {format_gst_rate_label(rate)}%",
                "amount": amt,
                "amount_display": format_indian_money(amt),
            }
        )
    grand = taxable + gst_total
    settings = get_site_settings()
    payment = _invoice_payment(settings, amount=grand, number=voucher.number)
    buyer_gstin = (getattr(buyer, "gstin", None) or "").strip().upper() if buyer else ""
    state_code = gstin_state_code(buyer_gstin)
    is_gst = sales_series_uses_gst(voucher.series) or bool(tax_rows)
    logo_url = reverse("site_logo") if getattr(settings, "logo", None) else ""
    return {
        "title": "TAX INVOICE" if is_gst else "INVOICE",
        "is_gst": is_gst,
        "number": voucher.number,
        "date": voucher.date,
        "narration": voucher.narration or "",
        "company_name": (settings.company_name or "").strip(),
        "company_address": (getattr(settings, "address", None) or "").strip(),
        "company_gstin": (getattr(settings, "gstin", None) or "").strip().upper(),
        "logo_url": logo_url,
        "buyer_name": buyer.name if buyer else "",
        "buyer_address": (getattr(buyer, "address", None) or "").strip() if buyer else "",
        "buyer_gstin": buyer_gstin,
        "place_of_supply": GSTIN_STATE_NAMES.get(state_code, state_code),
        "items": items,
        "taxable_total": taxable,
        "taxable_total_display": format_indian_money(taxable),
        "tax_rows": tax_rows,
        "gst_total": gst_total,
        "grand_total": grand,
        "grand_total_display": format_indian_money(grand),
        "amount_in_words": amount_in_indian_words(grand),
        "tasks": list(voucher.tasks.all()),
        **payment,
    }


def _invoice_payment(settings, *, amount, number: str) -> dict:
    from .upi import upi_payment_uri, upi_qr_data_uri

    account_name = (getattr(settings, "bank_account_name", None) or "").strip()
    bank_name = (getattr(settings, "bank_name", None) or "").strip()
    account_number = (getattr(settings, "bank_account_number", None) or "").strip()
    ifsc = (getattr(settings, "bank_ifsc", None) or "").strip().upper()
    upi_id = (getattr(settings, "upi_id", None) or "").strip()
    payee = account_name or (getattr(settings, "company_name", None) or "").strip()
    uri = upi_payment_uri(vpa=upi_id, payee_name=payee, amount=amount, note=number) if upi_id else ""
    return {
        "bank_account_name": account_name,
        "bank_name": bank_name,
        "bank_account_number": account_number,
        "bank_ifsc": ifsc,
        "upi_id": upi_id,
        "payment_uri": uri,
        "payment_qr": upi_qr_data_uri(uri) if uri else "",
        "show_payment": bool(account_number or ifsc or bank_name or account_name or upi_id),
    }


def _append_rate_tax_credit(rows: list[dict], party: Account, kind: str, component_rate: Decimal, amount: Decimal) -> None:
    if amount <= 0:
        return
    acc = find_gst_output_ledger(kind, component_rate)
    if acc.pk == party.pk:
        raise ValidationError("A GST ledger cannot be the buyer.")
    rows.append({"account": acc, "debit": Decimal("0.00"), "credit": amount, "hsn_code": ""})


def build_invoice_lines(
    *, voucher_type: str, party: Account, items: list[dict], with_gst: bool = False
) -> list[dict]:
    """Sales: debit buyer, credit each account. Purchase: debit each account, credit supplier."""
    if voucher_type not in (VOUCHER_SALES, VOUCHER_PURCHASE):
        raise ValidationError("Buyer/supplier posting is only for sales and purchase invoices.")
    if party is None:
        raise ValidationError("Select a buyer." if voucher_type == VOUCHER_SALES else "Select a supplier.")
    apply_gst = bool(with_gst) and voucher_type == VOUCHER_SALES
    intra = False
    if apply_gst:
        intra = is_intra_state_sale(getattr(party, "gstin", "") or "")
    rows = []
    total = Decimal("0.00")
    gst_total = Decimal("0.00")
    tax_credits: dict[tuple[str, Decimal], Decimal] = defaultdict(lambda: Decimal("0.00"))
    for raw in items:
        account = raw.get("account")
        amount = money(raw.get("amount"))
        if not account or amount <= 0:
            continue
        if account.pk == party.pk:
            raise ValidationError("The party and account cannot be the same.")
        hsn = (getattr(account, "hsn_code", None) or "")[:16]
        pure = bool(getattr(account, "is_pure_agent", False))
        rate = money(account.gst_rate) if apply_gst and not pure else Decimal("0.00")
        if apply_gst and not pure and rate <= 0:
            raise ValidationError(
                f'Set GST % on account ledger "{account.name}" before raising a GST invoice.'
            )
        gst_amt = money(amount * rate / Decimal("100")) if rate > 0 else Decimal("0.00")
        cgst, sgst, igst = _split_gst_amount(gst_amt, intra=intra) if apply_gst else (
            Decimal("0.00"),
            Decimal("0.00"),
            Decimal("0.00"),
        )
        total += amount
        gst_total += gst_amt
        if apply_gst and gst_amt > 0:
            if intra:
                half_rate = money(rate / Decimal("2"))
                tax_credits[("CGST", half_rate)] += cgst
                tax_credits[("SGST", half_rate)] += sgst
            else:
                tax_credits[("IGST", rate)] += igst
        line = {
            "account": account,
            "hsn_code": hsn,
            "is_pure_agent": pure,
        }
        if voucher_type == VOUCHER_SALES:
            line["debit"] = Decimal("0.00")
            line["credit"] = amount
        else:
            line["debit"] = amount
            line["credit"] = Decimal("0.00")
        rows.append(line)
    if not rows:
        raise ValidationError("Enter at least one account and amount.")
    if apply_gst:
        for (kind, component_rate), amt in tax_credits.items():
            _append_rate_tax_credit(rows, party, kind, component_rate, amt)
    party_amount = total + gst_total
    if voucher_type == VOUCHER_SALES:
        rows.insert(0, {"account": party, "debit": party_amount, "credit": Decimal("0.00"), "hsn_code": ""})
    else:
        rows.insert(0, {"account": party, "debit": Decimal("0.00"), "credit": party_amount, "hsn_code": ""})
    return rows


@transaction.atomic
def post_voucher(
    *,
    voucher_type: str,
    voucher_date,
    narration: str = "",
    lines: list[dict],
    actor=None,
    series: str | None = None,
    number: str | None = None,
    with_gst: bool = False,
    tax_kind: str | None = None,
    tasks=None,
    receipt_items=None,
    on_behalf_of=None,
    on_behalf_task=None,
    recovery_items=None,
    advance_items=None,
    skip_recovery_assignment: bool = False,
) -> Voucher:
    cleaned = _validate_lines(lines)
    series = series or default_series_for_type(voucher_type, with_gst=with_gst, tax_kind=tax_kind)
    requested = (number or "").strip()
    if requested:
        if len(requested) > 40:
            raise ValidationError("Voucher number cannot be longer than 40 characters.")
        if Voucher.objects.filter(
            voucher_type=voucher_type, series=series, number=requested
        ).exists():
            raise ValidationError(
                f"Voucher number {requested} already exists for this voucher type."
            )
        number = requested
    else:
        number = allocate_voucher_number(series, voucher_date)
    voucher = Voucher(
        voucher_type=voucher_type,
        series=series,
        number=number,
        date=voucher_date,
        narration=(narration or "").strip()[:500],
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    if skip_recovery_assignment:
        voucher.on_behalf_of = None
        voucher.on_behalf_task = None
    else:
        assign_payment_recovery(
            voucher, lines=cleaned, on_behalf_of=on_behalf_of, on_behalf_task=on_behalf_task
        )
    voucher.save()
    for row in cleaned:
        VoucherLine.objects.create(
            voucher=voucher,
            account=row["account"],
            debit=row["debit"],
            credit=row["credit"],
            hsn_code=(row.get("hsn_code") or "")[:16],
            is_pure_agent=bool(row.get("is_pure_agent")),
        )
    if tasks:
        voucher.tasks.set(tasks)
        _mark_tasks_billed(tasks, voucher)
    if receipt_items:
        apply_receipt_allocations(voucher, receipt_items)
    if recovery_items:
        apply_recovery_allocations(voucher, recovery_items)
    if advance_items:
        apply_sales_advance_knocks(voucher, advance_items)
    return voucher


@transaction.atomic
def import_legacy_vouchers(*, rows, actor=None) -> int:
    """Post old-software vouchers keeping their numbers. Does not consume InvoiceNumberSeq."""
    from .csv_import import grouped_voucher_books

    books = grouped_voucher_books(rows)
    for book in books:
        post_voucher(
            voucher_type=book["voucher_type"],
            voucher_date=book["date"],
            narration=book["narration"],
            lines=book["lines"],
            actor=actor,
            series=book["series"],
            number=book["number"],
            skip_recovery_assignment=True,
        )
    return len(books)


@transaction.atomic
def update_voucher(
    voucher: Voucher,
    *,
    voucher_date,
    narration: str = "",
    lines: list[dict],
    receipt_items=None,
    on_behalf_of=None,
    on_behalf_task=None,
    recovery_items=None,
    advance_items=None,
) -> Voucher:
    cleaned = _validate_lines(lines)
    if voucher.voucher_type == VOUCHER_PAYMENT and RecoveryAllocation.objects.filter(
        payment_line__voucher=voucher
    ).exists():
        raise ValidationError("This payment has been billed on a sales invoice. Edit or delete that invoice first.")
    if voucher.voucher_type == VOUCHER_SALES and advance_items is not None:
        release_invoice_receipt_knocks(voucher)
    else:
        ReceiptAllocation.objects.filter(Q(receipt=voucher) | Q(against=voucher)).delete()
    RecoveryAllocation.objects.filter(invoice=voucher).delete()
    voucher.lines.all().delete()
    voucher.date = voucher_date
    voucher.narration = (narration or "").strip()[:500]
    assign_payment_recovery(
        voucher, lines=cleaned, on_behalf_of=on_behalf_of, on_behalf_task=on_behalf_task
    )
    voucher.save(
        update_fields=["date", "narration", "on_behalf_of", "on_behalf_task", "updated_at"]
    )
    for row in cleaned:
        VoucherLine.objects.create(
            voucher=voucher,
            account=row["account"],
            debit=row["debit"],
            credit=row["credit"],
            hsn_code=(row.get("hsn_code") or "")[:16],
            is_pure_agent=bool(row.get("is_pure_agent")),
        )
    for task in voucher.tasks.all():
        if not task.bill_raised:
            continue
        task.bill_date = voucher.date
        task.save(update_fields=["bill_date", "updated_at"])
    if receipt_items:
        apply_receipt_allocations(voucher, receipt_items)
    if recovery_items:
        apply_recovery_allocations(voucher, recovery_items)
    if advance_items is not None:
        apply_sales_advance_knocks(voucher, advance_items)
    return voucher


def _mark_tasks_billed(tasks, voucher: Voucher) -> None:
    from tasks.models import Task

    for task in tasks:
        task.bill_raised = True
        task.bill_date = voucher.date
        remark = f"Invoice {voucher.number}"
        if task.bill_remarks:
            if voucher.number not in task.bill_remarks:
                task.bill_remarks = f"{task.bill_remarks}; {remark}"[:255]
        else:
            task.bill_remarks = remark[:255]
        task.save(update_fields=["bill_raised", "bill_date", "bill_remarks", "updated_at"])


@transaction.atomic
def delete_voucher(voucher: Voucher) -> None:
    tasks = list(voucher.tasks.all())
    number = voucher.number
    if voucher.voucher_type == VOUCHER_SALES:
        release_invoice_receipt_knocks(voucher)
    else:
        ReceiptAllocation.objects.filter(against=voucher).delete()
    voucher.delete()
    for task in tasks:
        if task.accounts_vouchers.exists():
            continue
        task.bill_raised = False
        task.bill_date = None
        remark = f"Invoice {number}"
        if task.bill_remarks:
            parts = [
                part.strip()
                for part in task.bill_remarks.split(";")
                if part.strip() and part.strip() != remark
            ]
            task.bill_remarks = "; ".join(parts)[:255]
        task.save(update_fields=["bill_raised", "bill_date", "bill_remarks", "updated_at"])


def create_sales_invoices_for_tasks(*, tasks, actor, voucher_date=None, with_gst: bool | None = None):
    voucher_date = voucher_date or timezone.localdate()
    created = []
    for task in tasks:
        created.append(
            create_sales_invoice_for_task(
                task=task,
                actor=actor,
                voucher_date=voucher_date,
                with_gst=with_gst,
            )
        )
    return created


def _ensure_named_group(*, name: str, parent: AccountGroup) -> AccountGroup:
    label = (name or "").strip()[:120]
    if not label:
        raise ValidationError("A group name is required.")
    existing = AccountGroup.objects.filter(name__iexact=label, parent=parent).first()
    if existing:
        return existing
    obj = AccountGroup(name=label, parent=parent, main_head=parent.resolved_main_head())
    obj.full_clean()
    obj.save()
    return obj


def _named_income_ledgers(name: str):
    return Account.objects.filter(name__iexact=name, client__isnull=True, is_active=True).order_by("pk")


def _ledger_has_gst_rate(account: Account | None) -> bool:
    return bool(account is not None and account.gst_rate is not None and money(account.gst_rate) > 0)


def _infer_gst_rate_from_output_ledgers() -> Decimal | None:
    """If CGST/SGST Output 9% (or IGST 18%) exist, treat the income rate as 18%."""
    igst = None
    half = None
    for acc in list(_gst_output_ledgers()) or list(Account.objects.filter(is_active=True)):
        parsed = GST_OUTPUT_NAME_RE.search(acc.name or "")
        if not parsed:
            continue
        kind = parsed.group(1).upper()
        component = money(parsed.group(2))
        if component <= 0:
            continue
        if kind == "IGST":
            igst = component
        elif kind in ("CGST", "SGST"):
            half = component
    if igst:
        return igst
    if half:
        return money(half * 2)
    return None


def _fill_income_gst_rate(account: Account) -> Decimal:
    if _ledger_has_gst_rate(account):
        return money(account.gst_rate)
    template = Account.objects.filter(system_key=SYSTEM_INCOME).first()
    rate = money(template.gst_rate) if template is not None and template.gst_rate is not None else Decimal("0.00")
    if rate <= 0:
        inferred = _infer_gst_rate_from_output_ledgers()
        rate = inferred if inferred is not None else Decimal("0.00")
    if rate > 0 and (account.gst_rate is None or money(account.gst_rate) <= 0):
        account.gst_rate = rate
        account.save(update_fields=["gst_rate", "updated_at"])
    return rate


def ensure_task_income_ledger(task) -> Account:
    """Use the existing task-named income ledger when present; otherwise create it."""
    master = getattr(task, "task_master", None)
    if master is None:
        raise ValidationError("Task master is required to create the income ledger.")
    seed_chart_of_accounts()
    income_head = AccountGroup.objects.filter(system_key=SYSTEM_GROUP_INCOME).first()
    if income_head is None:
        raise ValidationError("Income main head is missing. Open Account groups once to seed the chart.")
    task_group_name = (getattr(getattr(master, "task_group", None), "name", None) or "Direct Income").strip()
    primary = _ensure_named_group(name=task_group_name, parent=income_head)
    account_group = _ensure_named_group(name=master.name, parent=primary)
    ledger_name = (getattr(task, "display_title", None) or master.name or "").strip()[:200]
    if not ledger_name:
        raise ValidationError("Task name is required to create the income ledger.")
    named = list(_named_income_ledgers(ledger_name))
    acc = next((row for row in named if row.group_id == account_group.pk and _ledger_has_gst_rate(row)), None)
    if acc is None:
        acc = next((row for row in named if _ledger_has_gst_rate(row)), None)
    if acc is None:
        acc = next((row for row in named if row.group_id == account_group.pk), None)
    if acc is None and named:
        acc = named[0]
    if acc is None:
        template = Account.objects.filter(system_key=SYSTEM_INCOME).first()
        acc = Account(
            name=ledger_name,
            group=account_group,
            gst_rate=getattr(template, "gst_rate", None),
            hsn_code=(getattr(template, "hsn_code", None) or "")[:16],
        )
        acc.full_clean()
        acc.save()
    return acc


def _sales_party_for_client(client) -> Account:
    party = sync_client_account(client)
    if party is None:
        raise ValidationError("Could not create the client ledger.")
    client_gstin = (getattr(client, "gstin", None) or "").strip().upper()
    if client_gstin and (party.gstin or "").strip().upper() != client_gstin:
        party.gstin = client_gstin
        party.save(update_fields=["gstin", "updated_at"])
    return party


def _invoice_use_gst(*, party, tasks, with_gst: bool | None) -> bool:
    if with_gst is not None:
        return bool(with_gst)
    for task in tasks or []:
        if (getattr(getattr(task, "client", None), "gstin", None) or "").strip():
            return True
    client = getattr(party, "client", None)
    if (getattr(client, "gstin", None) or "").strip():
        return True
    return bool((getattr(party, "gstin", None) or "").strip())


def _combined_invoice_narration(*, party, tasks, recoveries) -> str:
    parts = []
    for task in tasks or []:
        label = f"Task {task.display_title}"
        period = getattr(task, "period_key", "") or ""
        if period:
            label = f"{label} — {period}"
        parts.append(label)
    rec_names = sorted(
        {
            (row.get("account").name if row.get("account") else "") or (row.get("account_name") or "")
            for row in recoveries or []
        }
    )
    rec_names = [name for name in rec_names if name]
    if rec_names and not tasks:
        extra = f"Recoveries — {party.name}"
        extra = f"{extra} ({', '.join(rec_names)})"
        parts.append(extra)
    elif rec_names:
        parts.append(f"Recoveries ({', '.join(rec_names)})")
    return "; ".join(parts)[:500]


def _fee_item_for_task(task, *, use_gst: bool) -> dict:
    if task.bill_raised or task.accounts_vouchers.exists():
        raise ValidationError(f"Bill already raised for {task.display_title}.")
    if not task.is_billable:
        raise ValidationError("Only billable tasks can raise a sales invoice.")
    fees = money(task.fees_amount)
    if fees <= 0:
        raise ValidationError("Enter a fees amount on the task before raising the bill.")
    income = ensure_task_income_ledger(task)
    if use_gst:
        rate = _fill_income_gst_rate(income)
        if rate <= 0:
            raise ValidationError(
                f'Set GST % on account ledger "{income.name}" (Account Ledger → GST rate %) '
                "before raising a GST invoice."
            )
    return {"account": income, "amount": fees}


@transaction.atomic
def create_sales_invoice_for_party_items(
    *,
    party: Account,
    actor,
    tasks=None,
    recoveries=None,
    voucher_date=None,
    with_gst: bool | None = None,
    tax_kind: str | None = None,
) -> Voucher:
    tasks = list(tasks or [])
    recoveries = list(recoveries or [])
    if party is None:
        raise ValidationError("Select a client ledger.")
    if not tasks and not recoveries:
        raise ValidationError("Select at least one fees or recovery row.")
    seen_tasks = set()
    unique_tasks = []
    for task in tasks:
        if task.pk in seen_tasks:
            continue
        seen_tasks.add(task.pk)
        unique_tasks.append(task)
    tasks = unique_tasks
    party_client_id = getattr(party, "client_id", None)
    for task in tasks:
        if party_client_id and task.client_id != party_client_id:
            raise ValidationError("Selected rows belong to more than one client.")
    if tax_kind:
        use_gst = sales_series_uses_gst(series_for_sales_tax_kind(tax_kind))
    else:
        use_gst = _invoice_use_gst(party=party, tasks=tasks, with_gst=with_gst)
    items = [_fee_item_for_task(task, use_gst=use_gst) for task in tasks]
    seen_recoveries = set()
    for row in recoveries:
        amount = money(row.get("pending") or row.get("amount"))
        account = row.get("account")
        recovery_id = row.get("id") or row.get("recovery_line")
        if not account or amount <= 0:
            continue
        if recovery_id in seen_recoveries:
            continue
        if recovery_id:
            seen_recoveries.add(recovery_id)
        items.append(
            {
                "account": account,
                "amount": amount,
                "recovery_line": recovery_id,
            }
        )
    if not items:
        raise ValidationError("Select at least one fees or recovery row.")
    lines = build_invoice_lines(
        voucher_type=VOUCHER_SALES,
        party=party,
        items=items,
        with_gst=use_gst,
    )
    return post_voucher(
        voucher_type=VOUCHER_SALES,
        voucher_date=voucher_date or timezone.localdate(),
        narration=_combined_invoice_narration(party=party, tasks=tasks, recoveries=recoveries),
        lines=lines,
        actor=actor,
        with_gst=use_gst,
        tax_kind=tax_kind,
        tasks=tasks,
        recovery_items=items,
    )


@transaction.atomic
def create_sales_invoice_for_task(
    *,
    task,
    actor,
    voucher_date=None,
    with_gst: bool | None = None,
    include_recoveries: bool = True,
) -> Voucher:
    party = _sales_party_for_client(task.client)
    recoveries = pending_recovery_rows(party=party, task=task) if include_recoveries else []
    return create_sales_invoice_for_party_items(
        party=party,
        actor=actor,
        tasks=[task],
        recoveries=recoveries,
        voucher_date=voucher_date,
        with_gst=with_gst,
    )


UNBILLED_FEES = "fees"
UNBILLED_RECOVERY = "recovery"
UNBILLED_BOTH = "both"
UNBILLED_KIND_LABELS = {
    UNBILLED_FEES: "Fees",
    UNBILLED_RECOVERY: "Recovery",
    UNBILLED_BOTH: "Both",
}


def build_unbilled_queue(*, tasks) -> list[dict]:
    """Fees waiting on completed tasks, plus each unbilled pure-agent recovery as its own row."""
    items = []
    for task in tasks:
        items.append(
            {
                "key": f"task:{task.pk}",
                "kind": UNBILLED_FEES,
                "kind_label": UNBILLED_KIND_LABELS[UNBILLED_FEES],
                "client_name": task.client.client_name,
                "task": task,
                "task_id": task.pk,
                "task_label": task.display_title,
                "ledger_label": "",
                "voucher_number": "",
                "period": task.period_key,
                "fees": money(task.fees_amount),
                "recovery": None,
                "recovery_ids": [],
            }
        )
    for row in pending_recovery_rows():
        items.append(
            {
                "key": f"recovery:{row['id']}",
                "kind": UNBILLED_RECOVERY,
                "kind_label": UNBILLED_KIND_LABELS[UNBILLED_RECOVERY],
                "client_name": row["party_name"],
                "task": None,
                "task_id": row.get("task_id"),
                "task_label": row["task_label"] or "—",
                "ledger_label": row["account_name"],
                "voucher_number": row.get("number") or "",
                "period": "",
                "fees": None,
                "recovery": row["pending"],
                "recovery_ids": [row["id"]],
                "party": row["party"],
            }
        )
    return items


def filter_unbilled_queue(items: list[dict], q: str) -> list[dict]:
    needle = (q or "").strip().casefold()
    if not needle:
        return items
    out = []
    for item in items:
        hay = " ".join(
            filter(
                None,
                [
                    item.get("client_name"),
                    item.get("task_label"),
                    item.get("ledger_label"),
                    item.get("voucher_number"),
                    item.get("period"),
                    item.get("kind_label"),
                ],
            )
        ).casefold()
        if needle in hay:
            out.append(item)
    return out


@transaction.atomic
def create_sales_invoice_for_recoveries(
    *,
    party: Account,
    recoveries: list[dict],
    actor,
    voucher_date=None,
    with_gst: bool = False,
) -> Voucher:
    return create_sales_invoice_for_party_items(
        party=party,
        actor=actor,
        recoveries=recoveries,
        voucher_date=voucher_date,
        with_gst=with_gst,
    )


@transaction.atomic
def create_invoices_from_unbilled_keys(
    *,
    keys: list[str],
    tasks,
    actor,
    voucher_date=None,
    with_gst: bool = False,
    tax_kind: str | None = None,
) -> list[Voucher]:
    seen: set[str] = set()
    unique_keys = []
    for raw in keys:
        key = str(raw or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique_keys.append(key)
    queue = {item["key"]: item for item in build_unbilled_queue(tasks=tasks)}
    selected = []
    for key in unique_keys:
        item = queue.get(key)
        if item is None:
            raise ValidationError("One or more selected rows are not eligible.")
        selected.append(item)
    if not selected:
        raise ValidationError("Select at least one fees or recovery row.")
    task_map = {task.pk: task for task in tasks}
    pending_by_id = {row["id"]: row for row in pending_recovery_rows()}
    groups: dict[int, dict] = {}
    for item in selected:
        if item["kind"] in (UNBILLED_FEES, UNBILLED_BOTH):
            task = task_map.get(item["task_id"])
            if task is None:
                raise ValidationError("One or more selected tasks are not eligible.")
            party = _sales_party_for_client(task.client)
            bucket = groups.setdefault(party.pk, {"party": party, "tasks": [], "recoveries": []})
            bucket["tasks"].append(task)
            continue
        if item["kind"] != UNBILLED_RECOVERY:
            continue
        for recovery_id in item.get("recovery_ids") or []:
            row = pending_by_id.get(recovery_id)
            if row is None:
                raise ValidationError("One or more selected rows are not eligible.")
            party = row["party"]
            bucket = groups.setdefault(party.pk, {"party": party, "tasks": [], "recoveries": []})
            bucket["recoveries"].append(row)
    created = []
    for bucket in groups.values():
        created.append(
            create_sales_invoice_for_party_items(
                party=bucket["party"],
                actor=actor,
                tasks=bucket["tasks"],
                recoveries=bucket["recoveries"],
                voucher_date=voucher_date,
                with_gst=with_gst,
                tax_kind=tax_kind,
            )
        )
    return created


TB_REPORT_GROUP = "group"
TB_REPORT_LEDGER = "ledger"
TB_REPORT_CHOICES = [
    (TB_REPORT_GROUP, "TB Group Wise"),
    (TB_REPORT_LEDGER, "TB Account Ledger wise"),
]
TB_FORMAT_TB = "tb"
TB_FORMAT_OPENING = "opening"
TB_FORMAT_TRANSACTIONS = "transactions"
TB_FORMAT_CHOICES = [
    (TB_FORMAT_TB, "Trial Balance"),
    (TB_FORMAT_OPENING, "TB with Opening Balance"),
    (TB_FORMAT_TRANSACTIONS, "TB with Opening and Transactions"),
]
TB_AMOUNT_KEYS = (
    "opening_debit",
    "opening_credit",
    "period_debit",
    "period_credit",
    "closing_debit",
    "closing_credit",
)


def financial_year_start(today=None):
    today = today or timezone.localdate()
    year = today.year if today.month >= 4 else today.year - 1
    return date(year, 4, 1)


def _sales_register_row(voucher: Voucher, *, gst: bool) -> dict:
    lines = list(voucher.lines.all())
    party_line = next((ln for ln in lines if money(ln.debit) > 0), None)
    party = party_line.account if party_line else None
    gstin = (getattr(party, "gstin", None) or "").strip().upper() if party else ""
    is_b2b = bool(gstin)
    taxable = Decimal("0.00")
    pure_agent = Decimal("0.00")
    igst = Decimal("0.00")
    cgst = Decimal("0.00")
    sgst = Decimal("0.00")
    for ln in lines:
        credit = money(ln.credit)
        if credit <= 0:
            continue
        parsed = _parse_gst_output_row(ln.account, credit)
        if parsed:
            if parsed["kind"] == "IGST":
                igst += parsed["amount"]
            elif parsed["kind"] == "CGST":
                cgst += parsed["amount"]
            elif parsed["kind"] == "SGST":
                sgst += parsed["amount"]
            continue
        if ln.is_pure_agent:
            pure_agent += credit
        else:
            taxable += credit
    total = money(party_line.debit) if party_line else money(taxable + pure_agent + igst + cgst + sgst)
    row = {
        "voucher": voucher,
        "date": voucher.date,
        "number": voucher.number,
        "customer": party.name if party else "",
        "gstin": gstin,
        "total": total,
        "amount": total,
    }
    if gst:
        row["b2c_sales"] = Decimal("0.00") if is_b2b else taxable
        row["b2b_sales"] = taxable if is_b2b else Decimal("0.00")
        row["pure_agent"] = pure_agent
        row["igst"] = igst
        row["cgst"] = cgst
        row["sgst"] = sgst
    else:
        row["sales"] = money(taxable + pure_agent)
    return row


def sales_register_totals(rows: list[dict], *, gst: bool) -> dict:
    keys = (
        ["b2b_sales", "b2c_sales", "pure_agent", "igst", "cgst", "sgst", "total"]
        if gst
        else ["sales", "total"]
    )
    totals = {key: Decimal("0.00") for key in keys}
    for row in rows:
        for key in keys:
            totals[key] += money(row.get(key))
    return totals


def _register_particulars(voucher: Voucher) -> str:
    lines = list(voucher.lines.all())
    vtype = voucher.voucher_type
    if vtype == VOUCHER_SALES:
        line = next((row for row in lines if money(row.debit) > 0), None)
    elif vtype == VOUCHER_PURCHASE:
        line = next((row for row in lines if money(row.credit) > 0), None)
    elif vtype == VOUCHER_CREDIT_NOTE:
        line = next((row for row in lines if money(row.credit) > 0), None)
    elif vtype == VOUCHER_DEBIT_NOTE:
        line = next((row for row in lines if money(row.debit) > 0), None)
    else:
        line = next((row for row in lines if money(row.debit) > 0), None)
    return line.account.name if line else ""


def book_register_rows(*, voucher_type: str, date_from=None, date_to=None, series: str | None = None) -> list[dict]:
    qs = (
        Voucher.objects.filter(voucher_type=voucher_type)
        .prefetch_related("lines__account", "lines__account__group", "lines__account__group__parent")
        .order_by("date", "pk")
    )
    if series:
        qs = qs.filter(series=series)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)
    sales_gst = voucher_type == VOUCHER_SALES and sales_series_uses_gst(series)
    sales_ngst = voucher_type == VOUCHER_SALES and series == SERIES_NGST
    rows = []
    for voucher in qs:
        if sales_gst or sales_ngst:
            rows.append(_sales_register_row(voucher, gst=sales_gst))
            continue
        amount = money(sum((line.debit or Decimal("0.00")) for line in voucher.lines.all()))
        rows.append(
            {
                "voucher": voucher,
                "date": voucher.date,
                "number": voucher.number,
                "particulars": _register_particulars(voucher),
                "narration": voucher.narration or "",
                "amount": amount,
            }
        )
    return rows


def opening_debit_credit(account: Account) -> tuple[Decimal, Decimal]:
    opening = money(account.opening_balance)
    if opening <= 0:
        return Decimal("0.00"), Decimal("0.00")
    if account.is_debit_nature():
        return opening, Decimal("0.00")
    return Decimal("0.00"), opening


def _net_debit_credit(debit, credit) -> tuple[Decimal, Decimal]:
    debit = money(debit)
    credit = money(credit)
    if debit >= credit:
        return debit - credit, Decimal("0.00")
    return Decimal("0.00"), credit - debit


def _tb_zero_amounts() -> dict:
    return {key: Decimal("0.00") for key in TB_AMOUNT_KEYS}


def _tb_sum_amounts(rows) -> dict:
    totals = _tb_zero_amounts()
    for row in rows:
        for key in TB_AMOUNT_KEYS:
            totals[key] += money(row.get(key))
    return totals


def _tb_row_active(row) -> bool:
    return any(money(row.get(key)) for key in TB_AMOUNT_KEYS)


def account_totals(account: Account, *, date_from=None, date_to=None) -> dict:
    dr_open, cr_open = opening_debit_credit(account)
    qs = VoucherLine.objects.filter(account=account).select_related("voucher")
    if date_to:
        qs = qs.filter(voucher__date__lte=date_to)
    period_qs = qs
    if date_from:
        for line in qs.filter(voucher__date__lt=date_from):
            dr_open += money(line.debit)
            cr_open += money(line.credit)
        dr_open, cr_open = _net_debit_credit(dr_open, cr_open)
        period_qs = qs.filter(voucher__date__gte=date_from)
    period_dr = Decimal("0.00")
    period_cr = Decimal("0.00")
    for line in period_qs:
        period_dr += money(line.debit)
        period_cr += money(line.credit)
    closing_dr, closing_cr = _net_debit_credit(dr_open + period_dr, cr_open + period_cr)
    return {
        "account": account,
        "opening_debit": dr_open,
        "opening_credit": cr_open,
        "period_debit": period_dr,
        "period_credit": period_cr,
        "closing_debit": closing_dr,
        "closing_credit": closing_cr,
    }


def _tb_group_kind(group: AccountGroup) -> str:
    if group.is_account_group():
        return "account_group"
    if group.is_parent_group():
        return "parent"
    return "parent"


def _tb_group_display_rows(ledger_rows: list[dict]) -> list[dict]:
    by_group = defaultdict(list)
    groups = {}
    for row in ledger_rows:
        group = row["account"].group
        by_group[group.pk].append(row)
        node = group
        while node is not None:
            groups[node.pk] = node
            node = node.parent
    children = defaultdict(list)
    roots = []
    for group in groups.values():
        if group.parent_id and group.parent_id in groups:
            children[group.parent_id].append(group)
        else:
            roots.append(group)
    for child_list in children.values():
        child_list.sort(key=lambda item: item.name.lower())
    head_order = {
        HEAD_LIABILITIES: 0,
        HEAD_ASSETS: 1,
        HEAD_INCOME: 2,
        HEAD_EXPENSES: 3,
    }
    roots.sort(key=lambda item: (head_order.get(item.resolved_main_head(), 99), item.name.lower()))
    for group_id in by_group:
        by_group[group_id].sort(key=lambda item: item["account"].name.lower())

    def subtree_ledgers(group: AccountGroup) -> list[dict]:
        rows = list(by_group.get(group.pk, []))
        for child in children.get(group.pk, []):
            rows.extend(subtree_ledgers(child))
        return rows

    display = []

    def add_group(group: AccountGroup, indent: int):
        amounts = _tb_sum_amounts(subtree_ledgers(group))
        direct = by_group.get(group.pk, [])
        display.append(
            {
                **amounts,
                "kind": _tb_group_kind(group),
                "name": group.name,
                "indent": indent,
                "is_header": True,
                "account": None,
                "group": group,
                "group_id": group.pk,
                "expandable": bool(direct),
                "collapsed": False,
                "parent_group_id": None,
            }
        )
        for child in children.get(group.pk, []):
            add_group(child, indent + 1)
        for row in direct:
            display.append(
                {
                    **row,
                    "kind": "ledger",
                    "name": row["account"].name,
                    "indent": indent + 1,
                    "is_header": False,
                    "group": group,
                    "group_id": None,
                    "expandable": False,
                    "collapsed": True,
                    "parent_group_id": group.pk,
                }
            )

    for root in roots:
        add_group(root, 0)
    return display


def trial_balance(
    *,
    date_from=None,
    date_to=None,
    report=TB_REPORT_GROUP,
    fmt=TB_FORMAT_TB,
):
    ledger_rows = []
    accounts = Account.objects.filter(is_active=True).select_related(
        "group",
        "group__parent",
        "group__parent__parent",
    )
    for acc in accounts:
        row = account_totals(acc, date_from=date_from, date_to=date_to)
        if _tb_row_active(row):
            ledger_rows.append(row)
    totals = _tb_sum_amounts(ledger_rows)
    show_opening = fmt in (TB_FORMAT_OPENING, TB_FORMAT_TRANSACTIONS)
    show_transactions = fmt == TB_FORMAT_TRANSACTIONS
    if report == TB_REPORT_LEDGER:
        ledger_rows.sort(key=lambda item: item["account"].name.lower())
        rows = [
            {
                **row,
                "kind": "ledger",
                "name": row["account"].name,
                "indent": 0,
                "is_header": False,
                "group": row["account"].group,
                "group_id": None,
                "expandable": False,
                "collapsed": False,
                "parent_group_id": None,
            }
            for row in ledger_rows
        ]
    else:
        rows = _tb_group_display_rows(ledger_rows)
    return {
        "report": report,
        "fmt": fmt,
        "rows": rows,
        "totals": totals,
        "show_group_column": report == TB_REPORT_LEDGER,
        "show_opening": show_opening,
        "show_transactions": show_transactions,
    }


def trial_balance_drill(group: AccountGroup, *, date_from=None, date_to=None, fmt=TB_FORMAT_TB) -> dict:
    """Account groups under a primary, or ledgers under an account group, that have a balance."""
    data = trial_balance(date_from=date_from, date_to=date_to, report=TB_REPORT_GROUP, fmt=fmt)
    if group.is_account_group():
        source = [
            row
            for row in data["rows"]
            if row.get("kind") == "ledger" and row.get("parent_group_id") == group.pk
        ]
        level = "ledgers"
    else:
        source = [
            row
            for row in data["rows"]
            if row.get("is_header") and getattr(row.get("group"), "parent_id", None) == group.pk
        ]
        level = "primary_groups" if group.is_main_head() else "account_groups"
    rows = []
    for row in source:
        item = dict(row)
        item["indent"] = 0
        item["collapsed"] = False
        item["parent_group_id"] = None
        item["expandable"] = False
        rows.append(item)
    drilled = dict(data)
    drilled["rows"] = rows
    drilled["totals"] = _tb_sum_amounts(rows)
    drilled["show_group_column"] = False
    drilled["drill_level"] = level
    return drilled


def _sum_closing_by_head(head: str, *, date_to=None) -> Decimal:
    total = Decimal("0.00")
    for acc in Account.objects.filter(is_active=True).select_related("group", "group__parent"):
        if acc.group.resolved_main_head() != head:
            continue
        row = account_totals(acc, date_to=date_to)
        if head in DEBIT_HEADS:
            total += row["closing_debit"] - row["closing_credit"]
        else:
            total += row["closing_credit"] - row["closing_debit"]
    return total


def _inr(amount) -> str:
    value = money(amount)
    if not value:
        return ""
    return f"{value:,.2f}"


def _pnl_blank_line() -> dict:
    return {
        "kind": "",
        "name": "",
        "inner": None,
        "outer": None,
        "inner_display": "",
        "outer_display": "",
        "indent": 0,
        "expandable": False,
        "group_id": None,
        "children": [],
        "account_id": None,
    }


def _pnl_line(
    kind: str,
    name: str,
    *,
    inner=None,
    outer=None,
    indent=0,
    expandable: bool = False,
    group_id=None,
    children=None,
    account_id=None,
) -> dict:
    def cell(value):
        if value is None:
            return None, ""
        amount = money(value)
        return amount, f"{amount:,.2f}"

    inner_amt, inner_disp = cell(inner)
    outer_amt, outer_disp = cell(outer)
    return {
        "kind": kind,
        "name": name,
        "inner": inner_amt,
        "outer": outer_amt,
        "inner_display": inner_disp,
        "outer_display": outer_disp,
        "indent": indent,
        "expandable": expandable,
        "group_id": group_id,
        "children": children or [],
        "account_id": account_id,
    }


def _pnl_nominal_amount(row: dict, *, expense: bool, date_from=None) -> Decimal:
    if date_from:
        debit, credit = row["period_debit"], row["period_credit"]
    else:
        debit, credit = row["closing_debit"], row["closing_credit"]
    if expense:
        return money(debit) - money(credit)
    return money(credit) - money(debit)


_STOCK_WORD_RE = re.compile(r"(?<![a-z])(?:stock|inventory)(?![a-z])", re.I)


def _is_stock_account(account: Account) -> bool:
    """True only for asset stock/inventory ledgers, not names that merely contain those letters."""
    if account.group.resolved_main_head() != HEAD_ASSETS:
        return False
    names = [account.name or "", account.group.name or ""]
    node = account.group.parent
    while node:
        names.append(node.name or "")
        node = node.parent
    if any((name or "").strip().lower() == "sundry debtors" for name in names[1:]):
        return False
    return any(_STOCK_WORD_RE.search(name) for name in names)


def _pnl_bucket(account: Account) -> str:
    names = []
    node = account.group
    while node is not None:
        names.append(node.name.lower())
        node = node.parent
    blob = " ".join(names)
    head = account.group.resolved_main_head()
    if head == HEAD_INCOME:
        if "indirect income" in blob:
            return "indirect_income"
        return "direct_income"
    if head != HEAD_EXPENSES:
        return ""
    if "indirect expense" in blob:
        return "indirect_expenses"
    if "direct expense" in blob:
        return "direct_expenses"
    if "depreciat" in blob or "amort" in blob:
        return "depreciation"
    if "finance" in blob:
        return "finance"
    if "purchase" in blob or "purchase" in account.name.lower():
        return "purchase"
    return "indirect_expenses"


def _pnl_block_group(account: Account) -> AccountGroup:
    group = account.group
    if group.is_account_group():
        return group.parent
    return group


def _pnl_block_lines(title: str, items: list[dict]) -> tuple[list[dict], Decimal]:
    items = [item for item in items if money(item.get("amount"))]
    items.sort(key=lambda item: item["name"].lower())
    if not items:
        return [], Decimal("0.00")
    total = money(sum((item["amount"] for item in items), Decimal("0.00")))
    if len(items) == 1 and (not title or title.lower() == items[0]["name"].lower()):
        return [
            _pnl_line(
                "ledger",
                items[0]["name"],
                outer=items[0]["amount"],
                account_id=items[0].get("account_id"),
            )
        ], total
    if not title:
        return (
            [
                _pnl_line(
                    "ledger",
                    items[0]["name"],
                    outer=items[0]["amount"],
                    account_id=items[0].get("account_id"),
                )
            ]
            if len(items) == 1
            else [
                _pnl_line(
                    "ledger",
                    item["name"],
                    inner=item["amount"],
                    outer=total if index == len(items) - 1 else None,
                    account_id=item.get("account_id"),
                )
                for index, item in enumerate(items)
            ],
            total,
        )
    lines = [_pnl_line("header", title)]
    if len(items) == 1:
        lines.append(
            _pnl_line(
                "ledger",
                items[0]["name"],
                outer=items[0]["amount"],
                account_id=items[0].get("account_id"),
            )
        )
    else:
        for index, item in enumerate(items):
            lines.append(
                _pnl_line(
                    "ledger",
                    item["name"],
                    inner=item["amount"],
                    outer=total if index == len(items) - 1 else None,
                    account_id=item.get("account_id"),
                )
            )
    return lines, total


def _pnl_account_group_lines(title: str, items: list[dict], *, group_id) -> tuple[list[dict], Decimal]:
    """Always show the Account Group total; ledgers stay collapsed until expanded."""
    items = [item for item in items if money(item.get("amount"))]
    items.sort(key=lambda item: item["name"].lower())
    if not items:
        return [], Decimal("0.00")
    total = money(sum((item["amount"] for item in items), Decimal("0.00")))
    children = [
        _pnl_line(
            "ledger",
            item["name"],
            inner=item["amount"],
            indent=1,
            account_id=item.get("account_id"),
        )
        for item in items
    ]
    return (
        [
            _pnl_line(
                "header",
                title,
                outer=total,
                expandable=True,
                group_id=group_id,
                children=children,
            )
        ],
        total,
    )


def _pnl_pair_rows(left_lines: list[dict], right_lines: list[dict], left_total, right_total) -> list[dict]:
    size = max(len(left_lines), len(right_lines))
    left_lines = left_lines + [_pnl_blank_line() for _ in range(size - len(left_lines))]
    right_lines = right_lines + [_pnl_blank_line() for _ in range(size - len(right_lines))]
    rows = [{"left": left, "right": right} for left, right in zip(left_lines, right_lines)]
    rows.append(
        {
            "left": _pnl_line("total", "Total", outer=left_total),
            "right": _pnl_line("total", "Total", outer=right_total),
        }
    )
    return rows


def profit_and_loss(*, date_from=None, date_to=None):
    accounts = Account.objects.filter(is_active=True).select_related(
        "group",
        "group__parent",
        "group__parent__parent",
    )
    rows_income = []
    rows_expenses = []
    buckets = defaultdict(lambda: defaultdict(list))
    direct_income_blocks = {}
    opening_stock = Decimal("0.00")
    closing_stock = Decimal("0.00")
    for acc in accounts:
        row = account_totals(acc, date_from=date_from, date_to=date_to)
        head = acc.group.resolved_main_head()
        if head == HEAD_INCOME:
            rows_income.append(row)
        elif head == HEAD_EXPENSES:
            rows_expenses.append(row)
        if _is_stock_account(acc):
            opening_stock += money(row["opening_debit"]) - money(row["opening_credit"])
            closing_stock += money(row["closing_debit"]) - money(row["closing_credit"])
            continue
        bucket = _pnl_bucket(acc)
        if not bucket:
            continue
        expense = bucket not in ("direct_income", "indirect_income")
        amount = _pnl_nominal_amount(row, expense=expense, date_from=date_from)
        if amount <= 0:
            continue
        if bucket == "direct_income":
            account_group = acc.group
            block = direct_income_blocks.setdefault(account_group.pk, {"group": account_group, "items": []})
            block["items"].append({"name": acc.name, "amount": amount, "account_id": acc.pk})
            continue
        group = _pnl_block_group(acc)
        title = group.name if not group.is_main_head() else ""
        buckets[bucket][title].append({"name": acc.name, "amount": amount, "account_id": acc.pk})

    def collect(bucket: str) -> tuple[list[dict], Decimal]:
        lines = []
        total = Decimal("0.00")
        for title, items in buckets[bucket].items():
            block, amount = _pnl_block_lines(title, items)
            lines.extend(block)
            total += amount
        return lines, total

    def collect_direct_income() -> tuple[list[dict], Decimal]:
        lines = []
        total = Decimal("0.00")
        blocks = sorted(
            direct_income_blocks.values(),
            key=lambda block: (block["group"].name or "").lower(),
        )
        for block in blocks:
            group = block["group"]
            block_lines, amount = _pnl_account_group_lines(
                group.name,
                block["items"],
                group_id=group.pk,
            )
            lines.extend(block_lines)
            total += amount
        return lines, total

    trading_left, purchase = collect("purchase")
    if opening_stock:
        trading_left.insert(0, _pnl_line("ledger", "Opening Stock", outer=opening_stock))
    direct_exp_lines, direct_exp = collect("direct_expenses")
    trading_left.extend(direct_exp_lines)
    trading_left_total = money(opening_stock + purchase + direct_exp)

    trading_right, direct_income = collect_direct_income()
    if closing_stock:
        trading_right.append(_pnl_line("ledger", "Closing Stock", outer=closing_stock))
    trading_right_total = money(direct_income + closing_stock)

    gross = trading_right_total - trading_left_total
    if gross > 0:
        trading_left.append(_pnl_line("balancing", "Gross Profit C/f", outer=gross))
        trading_left_total += gross
    elif gross < 0:
        loss = abs(gross)
        trading_right.append(_pnl_line("balancing", "Gross Loss C/f", outer=loss))
        trading_right_total += loss

    trading_rows = _pnl_pair_rows(trading_left, trading_right, trading_left_total, trading_right_total)

    indirect_lines, indirect_exp = collect("indirect_expenses")
    dep_lines, dep = collect("depreciation")
    finance_lines, finance = collect("finance")
    pnl_left = indirect_lines + dep_lines + finance_lines
    pnl_left_total = money(indirect_exp + dep + finance)
    pnl_right = []

    if gross > 0:
        pnl_right.append(_pnl_line("balancing", "Gross Profit B/f", outer=gross))
    elif gross < 0:
        pnl_left.insert(0, _pnl_line("balancing", "Gross Loss B/f", outer=abs(gross)))
        pnl_left_total += abs(gross)
    indirect_inc_lines, indirect_inc = collect("indirect_income")
    pnl_right.extend(indirect_inc_lines)
    pnl_right_total = money((gross if gross > 0 else Decimal("0.00")) + indirect_inc)

    net = pnl_right_total - pnl_left_total
    if net > 0:
        pnl_left.append(_pnl_line("balancing", "Net Profit/Loss", outer=net))
        pnl_left_total += net
    elif net < 0:
        pnl_right.append(_pnl_line("balancing", "Net Profit/Loss", outer=abs(net)))
        pnl_right_total += abs(net)

    pnl_rows = _pnl_pair_rows(pnl_left, pnl_right, pnl_left_total, pnl_right_total)
    income = money(direct_income + indirect_inc + closing_stock)
    expenses = money(opening_stock + purchase + direct_exp + indirect_exp + dep + finance)
    return {
        "income": income,
        "expenses": expenses,
        "net_profit": money(income - expenses),
        "gross_profit": gross,
        "rows_income": rows_income,
        "rows_expenses": rows_expenses,
        "trading_rows": trading_rows,
        "pnl_rows": pnl_rows,
    }


def _bs_fmt_amount(value) -> tuple[Decimal | None, str]:
    if value is None:
        return None, ""
    amount = money(value)
    if amount < 0:
        return amount, f"({abs(amount):,.2f})"
    return amount, f"{amount:,.2f}"


def _bs_line(kind: str, name: str, *, inner=None, outer=None, indent=0, account_id=None) -> dict:
    inner_amt, inner_disp = _bs_fmt_amount(inner)
    outer_amt, outer_disp = _bs_fmt_amount(outer)
    return {
        "kind": kind,
        "name": name,
        "inner": inner_amt,
        "outer": outer_amt,
        "inner_display": inner_disp,
        "outer_display": outer_disp,
        "indent": indent,
        "account_id": account_id,
    }


def _bs_closing_amount(row: dict, *, asset: bool) -> Decimal:
    if asset:
        return money(row["closing_debit"]) - money(row["closing_credit"])
    return money(row["closing_credit"]) - money(row["closing_debit"])


def _bs_parent_rank(name: str, *, asset: bool) -> tuple:
    label = (name or "").lower()
    if asset:
        rules = [
            (0, ("fixed asset", "fixed assets")),
            (1, ("non current asset", "non-current asset", "noncurrent asset")),
            (2, ("current asset", "current assets")),
        ]
    else:
        rules = [
            (0, ("capital", "equity", "reserve", "surplus")),
            (1, ("non current liab", "non-current liab", "noncurrent liab", "long term", "long-term")),
            (2, ("current liab",)),
        ]
    for rank, keys in rules:
        if any(key in label for key in keys):
            return (rank, label)
    return (9, label)


def _bs_parent_of(account: Account) -> AccountGroup | None:
    group = account.group
    if group.is_account_group():
        return group.parent
    if group.is_parent_group():
        return group
    return None


def _bs_build_side(items: list[dict], *, asset: bool) -> tuple[list[dict], Decimal]:
    parents: dict = {}
    for item in items:
        parent = item["parent"]
        key = parent.pk if parent is not None else 0
        slot = parents.setdefault(
            key,
            {"parent": parent, "direct": [], "groups": {}, "total": Decimal("0.00")},
        )
        slot["total"] += item["amount"]
        if item["account_group"] is None:
            slot["direct"].append(item)
        else:
            slot["groups"].setdefault(item["account_group"], []).append(item)

    ordered = sorted(
        parents.values(),
        key=lambda slot: _bs_parent_rank(slot["parent"].name if slot["parent"] else "Other", asset=asset),
    )
    lines = []
    grand = Decimal("0.00")
    for slot in ordered:
        if not slot["total"]:
            continue
        parent = slot["parent"]
        title = parent.name if parent is not None else ("Other Assets" if asset else "Other Liabilities")
        lines.append(_bs_line("header", title, outer=slot["total"], indent=0))
        for ledger in sorted(
            slot["direct"],
            key=lambda row: (
                1 if row["name"].lower() in ("net profit", "net loss") else 0,
                row["name"].lower(),
            ),
        ):
            kind = "balancing" if ledger["name"].lower() in ("net profit", "net loss") else "ledger"
            lines.append(
                _bs_line(
                    kind,
                    ledger["name"],
                    inner=ledger["amount"],
                    indent=1,
                    account_id=None if kind == "balancing" else ledger.get("account_id"),
                )
            )
        group_items = sorted(slot["groups"].items(), key=lambda pair: pair[0].name.lower())
        for account_group, ledgers in group_items:
            ledgers = sorted(ledgers, key=lambda row: row["name"].lower())
            group_total = money(sum((row["amount"] for row in ledgers), Decimal("0.00")))
            if not group_total:
                continue
            lines.append(_bs_line("subheader", account_group.name, outer=group_total, indent=1))
            for ledger in ledgers:
                lines.append(
                    _bs_line(
                        "ledger",
                        ledger["name"],
                        inner=ledger["amount"],
                        indent=2,
                        account_id=ledger.get("account_id"),
                    )
                )
        grand += slot["total"]
    return lines, money(grand)


def balance_sheet(*, date_to=None):
    accounts = Account.objects.filter(is_active=True).select_related(
        "group",
        "group__parent",
        "group__parent__parent",
    )
    rows_assets = []
    rows_liabilities = []
    asset_items = []
    liability_items = []
    for acc in accounts:
        row = account_totals(acc, date_to=date_to)
        head = acc.group.resolved_main_head()
        if head == HEAD_ASSETS:
            rows_assets.append(row)
            amount = _bs_closing_amount(row, asset=True)
            if not amount:
                continue
            group = acc.group
            asset_items.append(
                {
                    "name": acc.name,
                    "amount": amount,
                    "parent": _bs_parent_of(acc),
                    "account_group": group if group.is_account_group() else None,
                    "account_id": acc.pk,
                }
            )
        elif head == HEAD_LIABILITIES:
            rows_liabilities.append(row)
            amount = _bs_closing_amount(row, asset=False)
            if not amount:
                continue
            group = acc.group
            liability_items.append(
                {
                    "name": acc.name,
                    "amount": amount,
                    "parent": _bs_parent_of(acc),
                    "account_group": group if group.is_account_group() else None,
                    "account_id": acc.pk,
                }
            )

    fy_from = financial_year_start(date_to)
    pnl = profit_and_loss(date_from=fy_from, date_to=date_to)
    net = pnl["net_profit"]
    capital_parent = None
    for group in AccountGroup.parent_groups().filter(is_active=True):
        if group.resolved_main_head() != HEAD_LIABILITIES:
            continue
        if _bs_parent_rank(group.name, asset=False)[0] == 0:
            capital_parent = group
            break
    if net > 0 and capital_parent is not None:
        liability_items.append(
            {
                "name": "Net Profit",
                "amount": net,
                "parent": capital_parent,
                "account_group": None,
            }
        )

    asset_lines, assets_total = _bs_build_side(asset_items, asset=True)
    liab_lines, liab_total = _bs_build_side(liability_items, asset=False)
    if net > 0 and capital_parent is None:
        liab_lines.insert(0, _bs_line("balancing", "Net Profit", outer=net, indent=0))
        liab_total += net
    elif net < 0:
        asset_lines.append(_bs_line("balancing", "Net Loss", outer=abs(net), indent=0))
        assets_total += abs(net)
    statement_rows = _pnl_pair_rows(liab_lines, asset_lines, liab_total, assets_total)
    return {
        "assets": assets_total,
        "liabilities": liab_total - net if net >= 0 else liab_total,
        "net_profit": net,
        "liabilities_and_equity": liab_total,
        "rows_assets": rows_assets,
        "rows_liabilities": rows_liabilities,
        "pnl": pnl,
        "statement_rows": statement_rows,
    }


def _ledger_row(*, kind, date=None, number="", ledger_account="", narration="", debit=None, credit=None, voucher=None):
    debit = money(debit)
    credit = money(credit)
    return {
        "kind": kind,
        "date": date,
        "number": number,
        "ledger_account": ledger_account,
        "narration": narration,
        "debit": debit,
        "credit": credit,
        "amount": debit or credit,
        "voucher": voucher,
        "balance": None,
        "balance_display": "",
    }


def _format_running_balance(amount) -> str:
    if amount is None:
        return ""
    amount = money(amount)
    if amount > 0:
        return f"{amount} Dr"
    if amount < 0:
        return f"{money(abs(amount))} Cr"
    return "0.00"


def _apply_running_balance(rows: list[dict]) -> None:
    running = Decimal("0.00")
    for row in rows:
        kind = row.get("kind")
        if kind in ("opening", "entry"):
            running = money(running + money(row.get("debit")) - money(row.get("credit")))
            row["balance"] = running
        elif kind == "closing":
            row["balance"] = running
        else:
            row["balance"] = None
        row["balance_display"] = _format_running_balance(row["balance"])


def _ledger_counterpart_name(this_line, voucher_lines, account_pk: int) -> str:
    """Name the opposite-side ledger; ignore same-side tax/split lines."""
    this_debit = money(this_line.debit)
    this_credit = money(this_line.credit)
    want_debit = this_credit > 0 and this_debit == 0
    want_credit = this_debit > 0 and this_credit == 0
    opposites = []
    for other in voucher_lines:
        if other.account_id == account_pk:
            continue
        other_debit = money(other.debit)
        other_credit = money(other.credit)
        if want_debit and other_debit > 0:
            opposites.append((other_debit, other.account.name))
        elif want_credit and other_credit > 0:
            opposites.append((other_credit, other.account.name))
    if not opposites:
        return ""
    opposites.sort(key=lambda item: (-item[0], (item[1] or "").lower()))
    return opposites[0][1]


def ledger_lines(account: Account, *, date_from=None, date_to=None):
    dr_open, cr_open = opening_debit_credit(account)
    running = dr_open - cr_open
    if date_from:
        prior = VoucherLine.objects.filter(account=account, voucher__date__lt=date_from)
        for line in prior:
            running += money(line.debit) - money(line.credit)
        if running > 0:
            dr_open, cr_open = money(running), Decimal("0.00")
        elif running < 0:
            dr_open, cr_open = Decimal("0.00"), money(abs(running))
        else:
            dr_open, cr_open = Decimal("0.00"), Decimal("0.00")
    rows = []
    if dr_open or cr_open:
        rows.append(
            _ledger_row(
                kind="opening",
                date=date_from,
                number="Opening",
                ledger_account="Opening Balance",
                debit=dr_open,
                credit=cr_open,
            )
        )
    qs = (
        VoucherLine.objects.filter(account=account)
        .select_related("voucher")
        .prefetch_related("voucher__lines__account")
        .order_by("voucher__date", "voucher_id", "pk")
    )
    if date_from:
        qs = qs.filter(voucher__date__gte=date_from)
    if date_to:
        qs = qs.filter(voucher__date__lte=date_to)
    for line in qs:
        rows.append(
            _ledger_row(
                kind="entry",
                date=line.voucher.date,
                number=(line.voucher.number or "").replace("/", "-"),
                ledger_account=_ledger_counterpart_name(line, line.voucher.lines.all(), account.pk),
                narration=line.voucher.narration,
                debit=money(line.debit),
                credit=money(line.credit),
                voucher=line.voucher,
            )
        )
    total_debit = money(sum((row["debit"] for row in rows), Decimal("0.00")))
    total_credit = money(sum((row["credit"] for row in rows), Decimal("0.00")))
    closing = money(total_debit - total_credit)
    closing_debit = Decimal("0.00")
    closing_credit = Decimal("0.00")
    if closing > 0:
        closing_credit = closing
    elif closing < 0:
        closing_debit = money(abs(closing))
    if rows or closing:
        rows.append(
            _ledger_row(
                kind="closing",
                ledger_account="Closing Balance",
                debit=closing_debit,
                credit=closing_credit,
            )
        )
        rows.append(
            _ledger_row(
                kind="total",
                ledger_account="Total",
                debit=money(total_debit + closing_debit),
                credit=money(total_credit + closing_credit),
            )
        )
    _apply_running_balance(rows)
    return rows


def _ledger_group_labels(account: Account) -> tuple[str, str]:
    group = account.group
    if group.is_account_group():
        parent = group.parent
        return (parent.name if parent else group.name, group.name)
    if group.is_parent_group():
        return (group.name, "")
    return (group.name, "")


def all_ledger_sections(*, date_from=None, date_to=None) -> list[dict]:
    accounts = (
        Account.objects.filter(is_active=True)
        .select_related("group", "group__parent", "group__parent__parent")
        .order_by("name")
    )
    sections = []
    for account in accounts:
        rows = ledger_lines(account, date_from=date_from, date_to=date_to)
        if not rows:
            continue
        parent_group, account_group = _ledger_group_labels(account)
        sections.append(
            {
                "account": account,
                "parent_group": parent_group,
                "account_group": account_group,
                "rows": rows,
            }
        )
    sections.sort(
        key=lambda item: (
            item["parent_group"].lower(),
            item["account_group"].lower(),
            item["account"].name.lower(),
        )
    )
    return sections
