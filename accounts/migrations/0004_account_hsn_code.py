from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_voucher_purchase"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="hsn_code",
            field=models.CharField(blank=True, max_length=16, verbose_name="HSN / SAC"),
        ),
        migrations.AddField(
            model_name="voucherline",
            name="hsn_code",
            field=models.CharField(blank=True, max_length=16, verbose_name="HSN / SAC"),
        ),
    ]
