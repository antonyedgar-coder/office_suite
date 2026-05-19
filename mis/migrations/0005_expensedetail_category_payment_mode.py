from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def seed_expense_category(apps, schema_editor):
    ExpenseCategory = apps.get_model("masters", "ExpenseCategory")
    ExpenseDetail = apps.get_model("mis", "ExpenseDetail")
    general, _ = ExpenseCategory.objects.get_or_create(name="General")
    ExpenseDetail.objects.filter(category__isnull=True).update(category=general)


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0025_expensecategory"),
        ("mis", "0004_receipt_fees_expenses_received"),
    ]

    operations = [
        migrations.AddField(
            model_name="expensedetail",
            name="payment_mode",
            field=models.CharField(
                choices=[
                    ("CASH", "Cash"),
                    ("BANK_TRANSFER", "Bank Transfer"),
                    ("UPI", "UPI"),
                    ("CHEQUE", "Cheque"),
                    ("PAYMENT_GATEWAY", "Payment Gateway"),
                    ("OTHERS", "Others"),
                ],
                default="CASH",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="expensedetail",
            name="category",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="mis_expenses",
                to="masters.expensecategory",
            ),
        ),
        migrations.RunPython(seed_expense_category, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="expensedetail",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="mis_expenses",
                to="masters.expensecategory",
            ),
        ),
        migrations.AlterField(
            model_name="expensedetail",
            name="expenses_paid",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=12,
            ),
        ),
    ]
