from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_alter_employee_receive_dsc_expiry_notifications"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="gstin",
            field=models.CharField(
                blank=True,
                help_text="Office GSTIN. Sales invoices use the first two digits to choose CGST/SGST or IGST.",
                max_length=15,
                verbose_name="GST No",
            ),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="address",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
