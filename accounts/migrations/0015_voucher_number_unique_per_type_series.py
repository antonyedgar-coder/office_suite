from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0014_grant_payment_voucher_permissions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="voucher",
            name="number",
            field=models.CharField(max_length=40),
        ),
        migrations.AddConstraint(
            model_name="voucher",
            constraint=models.UniqueConstraint(
                fields=["voucher_type", "series", "number"],
                name="accounts_voucher_type_series_number_uniq",
            ),
        ),
    ]
