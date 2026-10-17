from django.db import migrations


def seed_and_grant(apps, schema_editor):
    AccountGroup = apps.get_model("accounts", "AccountGroup")
    Account = apps.get_model("accounts", "Account")

    def group(key, name, main_head):
        obj = AccountGroup.objects.filter(system_key=key).first()
        if obj:
            return obj
        return AccountGroup.objects.create(system_key=key, name=name, main_head=main_head)

    assets = group("assets", "Assets", "assets")
    liabilities = group("liabilities", "Liabilities", "liabilities")
    income = group("income", "Income", "income")
    group("expenses", "Expenses", "expenses")

    def account(key, name, grp):
        if Account.objects.filter(system_key=key).exists():
            return
        Account.objects.create(system_key=key, name=name, group=grp)

    account("professional_income", "Professional income", income)
    account("gst_output", "GST output", liabilities)
    account("cash", "Cash", assets)
    account("bank", "Bank", assets)

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    perms = list(Permission.objects.filter(content_type__app_label="accounts"))
    if not perms:
        return
    for group_row in Group.objects.all():
        name = (group_row.name or "").lower()
        if name in (
            "admin",
            "administrator",
            "super admin",
            "accounts",
            "account",
            "accountant",
            "accountants",
        ) or "account" in name:
            group_row.permissions.add(*perms)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_and_grant, noop),
    ]
