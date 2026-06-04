from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


def recompute_fees_totals(apps, schema_editor):
    FeesDetail = apps.get_model("mis", "FeesDetail")
    for row in FeesDetail.objects.all().iterator():
        fees = row.fees_amount or Decimal("0.00")
        expenses_invoice = row.expenses_invoice_amount or Decimal("0.00")
        gst = row.gst_amount or Decimal("0.00")
        new_total = fees + expenses_invoice + gst
        if row.total_amount != new_total:
            row.total_amount = new_total
            row.save(update_fields=["total_amount"])


class Migration(migrations.Migration):

    dependencies = [
        ("mis", "0007_alter_expensedetail_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="feesdetail",
            name="expenses_invoice_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=12,
                validators=[MinValueValidator(Decimal("0.00"))],
            ),
        ),
        migrations.RunPython(recompute_fees_totals, migrations.RunPython.noop),
    ]
