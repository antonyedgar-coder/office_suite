from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_receiptallocation_is_opening"),
    ]

    operations = [
        migrations.AlterField(
            model_name="voucher",
            name="voucher_type",
            field=models.CharField(
                choices=[
                    ("sales", "Sales invoice"),
                    ("purchase", "Purchase invoice"),
                    ("receipt", "Receipt voucher"),
                    ("payment", "Payment voucher"),
                    ("contra", "Contra voucher"),
                    ("journal", "Journal voucher"),
                    ("credit_note", "Credit note"),
                    ("debit_note", "Debit note"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="voucher",
            name="series",
            field=models.CharField(
                choices=[
                    ("GST", "GST invoice"),
                    ("NGST", "Non-GST invoice"),
                    ("PUR", "Purchase"),
                    ("RV", "Receipt"),
                    ("PV", "Payment"),
                    ("CV", "Contra"),
                    ("JV", "Journal"),
                    ("CN", "Credit note"),
                    ("DN", "Debit note"),
                ],
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="invoicenumberseq",
            name="series",
            field=models.CharField(
                choices=[
                    ("GST", "GST invoice"),
                    ("NGST", "Non-GST invoice"),
                    ("PUR", "Purchase"),
                    ("RV", "Receipt"),
                    ("PV", "Payment"),
                    ("CV", "Contra"),
                    ("JV", "Journal"),
                    ("CN", "Credit note"),
                    ("DN", "Debit note"),
                ],
                max_length=8,
            ),
        ),
    ]
