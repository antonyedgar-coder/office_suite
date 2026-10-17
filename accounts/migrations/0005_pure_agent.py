from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_account_hsn_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="is_pure_agent",
            field=models.BooleanField(
                default=False,
                help_text="Recoveries on this account are disbursements. No GST even on a GST invoice.",
                verbose_name="Pure agent",
            ),
        ),
        migrations.AddField(
            model_name="voucherline",
            name="is_pure_agent",
            field=models.BooleanField(default=False, verbose_name="Pure agent"),
        ),
    ]
