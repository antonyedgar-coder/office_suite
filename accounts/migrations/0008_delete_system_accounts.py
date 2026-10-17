from django.db import migrations


def delete_system_accounts(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    VoucherLine = apps.get_model("accounts", "VoucherLine")
    used = set(
        VoucherLine.objects.filter(account__system_key__isnull=False).values_list("account_id", flat=True)
    )
    Account.objects.exclude(system_key=None).exclude(system_key="").exclude(pk__in=used).delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_alter_invoicenumberseq_series"),
    ]

    operations = [
        migrations.RunPython(delete_system_accounts, noop),
    ]
