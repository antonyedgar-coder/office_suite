from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("mis", "0003_activity_remarks"),
    ]

    operations = [
        migrations.RenameField(
            model_name="receipt",
            old_name="amount_received",
            new_name="fees_received",
        ),
        migrations.AddField(
            model_name="receipt",
            name="expenses_received",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=12,
            ),
        ),
    ]
