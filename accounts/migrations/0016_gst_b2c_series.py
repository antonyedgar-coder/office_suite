from django.db import migrations, models


SERIES_CHOICES = [
    ("GST", "GST-B2B invoice"),
    ("GSTB2C", "GST-B2C invoice"),
    ("NGST", "Non-GST invoice"),
    ("PUR", "Purchase"),
    ("RV", "Receipt"),
    ("PV", "Payment"),
    ("CV", "Contra"),
    ("JV", "Journal"),
    ("CN", "Credit note"),
    ("DN", "Debit note"),
]


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0015_voucher_number_unique_per_type_series"),
    ]

    operations = [
        migrations.AlterField(
            model_name="voucher",
            name="series",
            field=models.CharField(choices=SERIES_CHOICES, max_length=8),
        ),
        migrations.AlterField(
            model_name="invoicenumberseq",
            name="series",
            field=models.CharField(choices=SERIES_CHOICES, max_length=8),
        ),
    ]
