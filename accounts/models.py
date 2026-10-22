from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from core.created_by import created_by_field

HEAD_LIABILITIES = "liabilities"
HEAD_ASSETS = "assets"
HEAD_INCOME = "income"
HEAD_EXPENSES = "expenses"
MAIN_HEAD_CHOICES = [
    (HEAD_LIABILITIES, "Liabilities"),
    (HEAD_ASSETS, "Assets"),
    (HEAD_INCOME, "Income"),
    (HEAD_EXPENSES, "Expenses"),
]

DEBIT_HEADS = frozenset({HEAD_ASSETS, HEAD_EXPENSES})

VOUCHER_SALES = "sales"
VOUCHER_PURCHASE = "purchase"
VOUCHER_RECEIPT = "receipt"
VOUCHER_PAYMENT = "payment"
VOUCHER_CONTRA = "contra"
VOUCHER_JOURNAL = "journal"
VOUCHER_CREDIT_NOTE = "credit_note"
VOUCHER_DEBIT_NOTE = "debit_note"
VOUCHER_TYPE_CHOICES = [
    (VOUCHER_SALES, "Sales invoice"),
    (VOUCHER_PURCHASE, "Purchase invoice"),
    (VOUCHER_RECEIPT, "Receipt voucher"),
    (VOUCHER_PAYMENT, "Payment voucher"),
    (VOUCHER_CONTRA, "Contra voucher"),
    (VOUCHER_JOURNAL, "Journal voucher"),
    (VOUCHER_CREDIT_NOTE, "Credit note"),
    (VOUCHER_DEBIT_NOTE, "Debit note"),
]
VOUCHER_TABS = [
    (VOUCHER_SALES, "Sales"),
    (VOUCHER_PURCHASE, "Purchase"),
    (VOUCHER_RECEIPT, "Receipt"),
    (VOUCHER_PAYMENT, "Payment"),
    (VOUCHER_CONTRA, "Contra"),
    (VOUCHER_JOURNAL, "Journal"),
    (VOUCHER_CREDIT_NOTE, "Credit note"),
    (VOUCHER_DEBIT_NOTE, "Debit note"),
]
REGISTER_TABS = [
    (VOUCHER_SALES, "Sales register"),
    (VOUCHER_PURCHASE, "Purchase register"),
    (VOUCHER_JOURNAL, "Journal Register"),
    (VOUCHER_CREDIT_NOTE, "CN Register"),
    (VOUCHER_DEBIT_NOTE, "DN Register"),
]
SALES_INVOICE_GST = "gst"
SALES_INVOICE_GST_B2C = "gst_b2c"
SALES_INVOICE_NGST = "ngst"
SALES_INVOICE_TABS = [
    (SALES_INVOICE_GST, "GST-B2B Invoice"),
    (SALES_INVOICE_GST_B2C, "GST-B2C Invoice"),
    (SALES_INVOICE_NGST, "Non GST Invoice"),
]
SALES_INVOICE_KEYS = {key for key, _ in SALES_INVOICE_TABS}
VOUCHER_TYPE_KEYS = {key for key, _ in VOUCHER_TYPE_CHOICES}
REGISTER_TYPE_KEYS = {key for key, _ in REGISTER_TABS}

SERIES_GST = "GST"
SERIES_GST_B2C = "GSTB2C"
SERIES_NGST = "NGST"
SERIES_PUR = "PUR"
SERIES_RV = "RV"
SERIES_PV = "PV"
SERIES_CV = "CV"
SERIES_JV = "JV"
SERIES_CN = "CN"
SERIES_DN = "DN"
SERIES_CHOICES = [
    (SERIES_GST, "GST-B2B invoice"),
    (SERIES_GST_B2C, "GST-B2C invoice"),
    (SERIES_NGST, "Non-GST invoice"),
    (SERIES_PUR, "Purchase"),
    (SERIES_RV, "Receipt"),
    (SERIES_PV, "Payment"),
    (SERIES_CV, "Contra"),
    (SERIES_JV, "Journal"),
    (SERIES_CN, "Credit note"),
    (SERIES_DN, "Debit note"),
]
GST_SALES_SERIES = frozenset({SERIES_GST, SERIES_GST_B2C})
SALES_TAX_KIND_GST = "gst"
SALES_TAX_KIND_GST_B2C = "gst_b2c"
SALES_TAX_KIND_NGST = "ngst"


def series_for_sales_tax_kind(tax_kind: str | None, *, with_gst: bool = False) -> str:
    kind = (tax_kind or "").strip().lower().replace(" ", "").replace("_", "-")
    if kind in {"gst-b2c", "gstb2c", "b2c"}:
        return SERIES_GST_B2C
    if kind in {"gst", "gst-b2b", "gstb2b", "b2b"}:
        return SERIES_GST
    if kind in {"ngst", "nongst", "non-gst"}:
        return SERIES_NGST
    return SERIES_GST if with_gst else SERIES_NGST


def tax_kind_for_sales_series(series: str | None) -> str:
    if series == SERIES_GST_B2C:
        return SALES_TAX_KIND_GST_B2C
    if series == SERIES_GST:
        return SALES_TAX_KIND_GST
    return SALES_TAX_KIND_NGST


def sales_series_uses_gst(series: str | None) -> bool:
    return series in GST_SALES_SERIES


class AccountGroup(models.Model):
    name = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    main_head = models.CharField(max_length=16, choices=MAIN_HEAD_CHOICES)
    system_key = models.CharField(max_length=40, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = created_by_field()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["name", "parent"], name="accounts_group_name_parent_uniq"),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        if not self.parent_id:
            if not self.main_head:
                raise ValidationError({"main_head": "Select a main head."})
            return
        if self.parent_id == self.pk:
            raise ValidationError({"parent": "A group cannot be its own parent."})
        ancestor = self.parent
        seen = set()
        while ancestor is not None:
            if ancestor.pk in seen:
                raise ValidationError({"parent": "Group nesting cannot form a loop."})
            seen.add(ancestor.pk)
            if self.pk and ancestor.pk == self.pk:
                raise ValidationError({"parent": "Group nesting cannot form a loop."})
            ancestor = ancestor.parent
        parent = self.parent
        if parent.parent_id and parent.parent.parent_id:
            raise ValidationError({"parent": "Account groups cannot have further sub-groups."})
        self.main_head = parent.resolved_main_head()

    def resolved_main_head(self) -> str:
        node = self
        guard = 0
        while node.parent_id and guard < 50:
            node = node.parent
            guard += 1
        return node.main_head

    def is_debit_nature(self) -> bool:
        return self.resolved_main_head() in DEBIT_HEADS

    def is_main_head(self) -> bool:
        return self.parent_id is None

    def is_parent_group(self) -> bool:
        return bool(self.parent_id) and self.parent.parent_id is None

    def is_account_group(self) -> bool:
        return bool(self.parent_id) and self.parent.parent_id is not None

    @classmethod
    def main_heads(cls):
        return cls.objects.filter(parent__isnull=True)

    @classmethod
    def parent_groups(cls):
        return cls.objects.filter(parent__isnull=False, parent__parent__isnull=True)

    @classmethod
    def account_groups(cls):
        return cls.objects.filter(parent__parent__isnull=False)


class Account(models.Model):
    name = models.CharField(max_length=200)
    group = models.ForeignKey(AccountGroup, on_delete=models.PROTECT, related_name="accounts")
    address = models.CharField(max_length=255, blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    hsn_code = models.CharField("HSN / SAC", max_length=16, blank=True)
    is_pure_agent = models.BooleanField(
        "Pure agent",
        default=False,
        help_text="Recoveries on this account are disbursements. No GST even on a GST invoice.",
    )
    pan = models.CharField(max_length=10, blank=True)
    opening_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    client = models.OneToOneField(
        "masters.Client",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ledger_account",
    )
    system_key = models.CharField(max_length=40, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = created_by_field()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        self.name = (self.name or "").strip()
        self.gstin = (self.gstin or "").strip().upper()
        self.pan = (self.pan or "").strip().upper()
        self.hsn_code = (self.hsn_code or "").strip()
        if self.is_pure_agent:
            self.gst_rate = None
        if not self.name:
            raise ValidationError({"name": "Account name is required."})

    def is_debit_nature(self) -> bool:
        return self.group.is_debit_nature()

    def primary_group(self) -> AccountGroup | None:
        group = self.group
        if group.is_account_group():
            return group.parent
        if group.is_parent_group():
            return group
        return None

    def secondary_group(self) -> AccountGroup | None:
        group = self.group
        if group.is_account_group():
            return group
        return None


class InvoiceNumberSeq(models.Model):
    series = models.CharField(max_length=8, choices=SERIES_CHOICES)
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["series", "year", "month"],
                name="accounts_invoice_seq_series_ym_uniq",
            ),
        ]


class Voucher(models.Model):
    voucher_type = models.CharField(max_length=20, choices=VOUCHER_TYPE_CHOICES)
    series = models.CharField(max_length=8, choices=SERIES_CHOICES)
    number = models.CharField(max_length=40)
    date = models.DateField()
    narration = models.CharField(max_length=500, blank=True)
    tasks = models.ManyToManyField("tasks.Task", blank=True, related_name="accounts_vouchers")
    on_behalf_of = models.ForeignKey(
        "Account",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="recoverable_payments",
    )
    on_behalf_task = models.ForeignKey(
        "tasks.Task",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recoverable_payments",
    )
    created_by = created_by_field()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["voucher_type", "series", "number"],
                name="accounts_voucher_type_series_number_uniq",
            ),
        ]
        permissions = [
            ("post_voucher", "Can post accounts vouchers"),
            ("view_accounts_reports", "Can view accounts reports"),
            ("add_payment_voucher", "Payment voucher | Add"),
            ("change_payment_voucher", "Payment voucher | Change"),
            ("delete_payment_voucher", "Payment voucher | Delete"),
            ("print_payment_voucher", "Payment voucher | Print"),
        ]

    def __str__(self) -> str:
        return self.number

    def debit_total(self) -> Decimal:
        return sum((line.debit or Decimal("0")) for line in self.lines.all()) or Decimal("0")

    def credit_total(self) -> Decimal:
        return sum((line.credit or Decimal("0")) for line in self.lines.all()) or Decimal("0")


class VoucherLine(models.Model):
    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="voucher_lines")
    debit = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    credit = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    hsn_code = models.CharField("HSN / SAC", max_length=16, blank=True)
    is_pure_agent = models.BooleanField("Pure agent", default=False)

    class Meta:
        ordering = ["pk"]

    def clean(self):
        debit = self.debit or Decimal("0")
        credit = self.credit or Decimal("0")
        if debit and credit:
            raise ValidationError("A line cannot have both debit and credit.")
        if not debit and not credit:
            raise ValidationError("Enter a debit or a credit amount.")


class ReceiptAllocation(models.Model):
    """Bill-wise knock-off (or advance) of a receipt against a party's sales invoices."""

    receipt = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name="receipt_allocations")
    party = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="receipt_allocations")
    against = models.ForeignKey(
        Voucher,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="receipts_applied",
    )
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    is_advance = models.BooleanField(default=False)
    is_opening = models.BooleanField(default=False)

    class Meta:
        ordering = ["pk"]

    def clean(self):
        if self.is_advance and self.is_opening:
            raise ValidationError("An amount cannot be both advance and opening balance.")
        if self.is_advance:
            if self.against_id:
                raise ValidationError("Advance cannot be linked to a bill.")
            return
        if self.is_opening:
            if self.against_id:
                raise ValidationError("Opening balance knock-off cannot be linked to a bill.")
            return
        if not self.against_id:
            raise ValidationError("Select the bill or opening balance to knock off, or mark the amount as advance.")


class RecoveryAllocation(models.Model):
    """Knock-off of a pure-agent payment debit against a sales invoice credit."""

    invoice = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name="recovery_allocations")
    payment_line = models.ForeignKey(
        VoucherLine,
        on_delete=models.PROTECT,
        related_name="recovery_allocations",
    )
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )

    class Meta:
        ordering = ["pk"]
