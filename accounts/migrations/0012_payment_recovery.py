import django.core.validators
from decimal import Decimal
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0011_voucher_contra"),
        ("tasks", "0023_task_billing"),
    ]

    operations = [
        migrations.AddField(
            model_name="voucher",
            name="on_behalf_of",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="recoverable_payments",
                to="accounts.account",
            ),
        ),
        migrations.AddField(
            model_name="voucher",
            name="on_behalf_task",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="recoverable_payments",
                to="tasks.task",
            ),
        ),
        migrations.CreateModel(
            name="RecoveryAllocation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=14,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                    ),
                ),
                (
                    "invoice",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recovery_allocations",
                        to="accounts.voucher",
                    ),
                ),
                (
                    "payment_line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="recovery_allocations",
                        to="accounts.voucherline",
                    ),
                ),
            ],
            options={
                "ordering": ["pk"],
            },
        ),
    ]
