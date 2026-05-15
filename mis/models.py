from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class FeesDetail(models.Model):
    """
    MIS capture of fees raised to clients (not an invoice).
    """

    date = models.DateField()
    client = models.ForeignKey("masters.Client", on_delete=models.PROTECT, related_name="mis_fees")
    pan_no = models.CharField(max_length=10, blank=True)

    fees_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    gst_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        default=Decimal("0.00"),
    )
    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        editable=False,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def save(self, *args, **kwargs):
        if self.client_id:
            self.pan_no = (self.client.pan or "").strip().upper()
        fees = self.fees_amount or Decimal("0.00")
        gst = self.gst_amount or Decimal("0.00")
        self.total_amount = fees + gst
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Fees {self.client_id} {self.date} ({self.total_amount})"


class Receipt(models.Model):
    """
    MIS capture of amount received from clients.
    """

    date = models.DateField()
    client = models.ForeignKey("masters.Client", on_delete=models.PROTECT, related_name="mis_receipts")
    pan_no = models.CharField(max_length=10, blank=True)
    amount_received = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def save(self, *args, **kwargs):
        if self.client_id:
            self.pan_no = (self.client.pan or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Receipt {self.client_id} {self.date} ({self.amount_received})"


class ExpenseDetail(models.Model):
    """
    MIS capture of expenses paid for/against a client.
    """

    date = models.DateField()
    client = models.ForeignKey("masters.Client", on_delete=models.PROTECT, related_name="mis_expenses")
    pan_no = models.CharField(max_length=10, blank=True)
    expenses_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    notes = models.CharField(max_length=300, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def save(self, *args, **kwargs):
        if self.client_id:
            self.pan_no = (self.client.pan or "").strip().upper()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"Expense {self.client_id} {self.date} ({self.expenses_paid})"

