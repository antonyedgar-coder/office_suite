from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


def recompute_receipt_tender_totals(apps, schema_editor):
    Receipt = apps.get_model("mis", "Receipt")
    TenderDetail = apps.get_model("mis", "TenderDetail")
    for row in Receipt.objects.all().iterator():
        total = (row.fees_received or Decimal("0.00")) + (row.expenses_received or Decimal("0.00"))
        if row.total_amount != total:
            row.total_amount = total
            row.save(update_fields=["total_amount"])
    for row in TenderDetail.objects.all().iterator():
        total = (row.tender_fees or Decimal("0.00")) + (row.tender_deposit or Decimal("0.00"))
        if row.total_amount != total:
            row.total_amount = total
            row.save(update_fields=["total_amount"])


class Migration(migrations.Migration):

    dependencies = [
        ("mis", "0008_feesdetail_expenses_invoice_amount"),
    ]

    operations = [
        migrations.AddField(
            model_name="receipt",
            name="total_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                editable=False,
                max_digits=12,
                validators=[MinValueValidator(Decimal("0.00"))],
            ),
        ),
        migrations.AddField(
            model_name="tenderdetail",
            name="total_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                editable=False,
                max_digits=12,
                validators=[MinValueValidator(Decimal("0.00"))],
            ),
        ),
        migrations.RunPython(recompute_receipt_tender_totals, migrations.RunPython.noop),
    ]
