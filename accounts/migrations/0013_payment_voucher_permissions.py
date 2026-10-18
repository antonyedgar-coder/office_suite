from django.db import migrations


PAYMENT_PERM_NAMES = {
    "add_payment_voucher": "Payment voucher | Add",
    "change_payment_voucher": "Payment voucher | Change",
    "delete_payment_voucher": "Payment voucher | Delete",
    "print_payment_voucher": "Payment voucher | Print",
}


def grant_payment_voucher_permissions(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("core", "User")
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct = ContentType.objects.filter(app_label="accounts", model="voucher").first()
    if not ct:
        return
    new_perms = []
    for codename, name in PAYMENT_PERM_NAMES.items():
        perm, _created = Permission.objects.get_or_create(
            content_type=ct,
            codename=codename,
            defaults={"name": name},
        )
        if perm.name != name:
            perm.name = name
            perm.save(update_fields=["name"])
        new_perms.append(perm)
    donors = list(
        Permission.objects.filter(content_type=ct, codename__in=["post_voucher", "add_voucher"])
    )
    group_ids = set()
    if donors:
        group_ids.update(
            Group.objects.filter(permissions__in=donors).values_list("pk", flat=True)
        )
        for user in User.objects.filter(user_permissions__in=donors).distinct():
            user.user_permissions.add(*new_perms)
    for group in Group.objects.all():
        name = (group.name or "").lower()
        if name in (
            "admin",
            "administrator",
            "super admin",
            "accounts",
            "account",
            "accountant",
            "accountants",
        ) or "account" in name:
            group_ids.add(group.pk)
    for group in Group.objects.filter(pk__in=group_ids):
        group.permissions.add(*new_perms)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_payment_recovery"),
        ("core", "0012_sitesettings_gstin_address"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="voucher",
            options={
                "ordering": ["-date", "-id"],
                "permissions": [
                    ("post_voucher", "Can post accounts vouchers"),
                    ("view_accounts_reports", "Can view accounts reports"),
                    ("add_payment_voucher", "Payment voucher | Add"),
                    ("change_payment_voucher", "Payment voucher | Change"),
                    ("delete_payment_voucher", "Payment voucher | Delete"),
                    ("print_payment_voucher", "Payment voucher | Print"),
                ],
            },
        ),
        migrations.RunPython(grant_payment_voucher_permissions, noop),
    ]
