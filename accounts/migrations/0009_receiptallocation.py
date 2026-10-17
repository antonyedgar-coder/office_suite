from decimal import Decimal

from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_delete_system_accounts"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReceiptAllocation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                    ),
                ),
                ("is_advance", models.BooleanField(default=False)),
                (
                    "against",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="receipts_applied",
                        to="accounts.voucher",
                    ),
                ),
                (
                    "party",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="receipt_allocations",
                        to="accounts.account",
                    ),
                ),
                (
                    "receipt",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="receipt_allocations",
                        to="accounts.voucher",
                    ),
                ),
            ],
            options={"ordering": ["pk"]},
        ),
    ]
