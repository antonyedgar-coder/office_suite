from django.db import migrations


def seed_split_gst_accounts(apps, schema_editor):
    AccountGroup = apps.get_model("accounts", "AccountGroup")
    Account = apps.get_model("accounts", "Account")
    liabilities = AccountGroup.objects.filter(system_key="liabilities").first()
    if not liabilities:
        return
    for key, name in (
        ("cgst_output", "CGST output"),
        ("sgst_output", "SGST output"),
        ("igst_output", "IGST output"),
    ):
        if not Account.objects.filter(system_key=key).exists():
            Account.objects.create(system_key=key, name=name, group=liabilities)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_pure_agent"),
    ]

    operations = [
        migrations.RunPython(seed_split_gst_accounts, noop),
    ]
