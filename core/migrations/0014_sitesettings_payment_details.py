from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_sitesettings_theme_colours"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="bank_account_name",
            field=models.CharField(
                blank=True,
                help_text="Beneficiary name printed on sales invoices.",
                max_length=120,
                verbose_name="Account name",
            ),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="bank_name",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="bank_account_number",
            field=models.CharField(blank=True, max_length=20, verbose_name="Account number"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="bank_ifsc",
            field=models.CharField(blank=True, max_length=11, verbose_name="IFSC"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="upi_id",
            field=models.CharField(
                blank=True,
                help_text="When set, sales invoices include a UPI QR for this ID.",
                max_length=100,
                verbose_name="UPI ID",
            ),
        ),
    ]
