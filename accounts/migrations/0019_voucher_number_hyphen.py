import re

from django.db import migrations


_GENERATED_NUMBER = re.compile(r"^([A-Za-z0-9]+)/(\d{4})/(\d{2})/(\d+)$")


def hyphenate_generated_numbers(apps, schema_editor):
    Voucher = apps.get_model("accounts", "Voucher")
    for voucher in Voucher.objects.all().iterator():
        match = _GENERATED_NUMBER.match(voucher.number or "")
        if not match:
            continue
        series, year, month, serial = match.groups()
        voucher.number = f"{series}-{year}-{month}-{int(serial):04d}"
        voucher.save(update_fields=["number"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0018_voucher_activity_permissions"),
    ]

    operations = [
        migrations.RunPython(hyphenate_generated_numbers, migrations.RunPython.noop),
    ]
