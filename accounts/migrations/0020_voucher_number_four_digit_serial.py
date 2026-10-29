import re

from django.db import migrations


_GENERATED_NUMBER = re.compile(r"^([A-Za-z0-9]+)[/-](\d{4})[/-](\d{2})[/-](\d+)$")


def four_digit_serial(apps, schema_editor):
    Voucher = apps.get_model("accounts", "Voucher")
    for voucher in Voucher.objects.all().iterator():
        match = _GENERATED_NUMBER.match(voucher.number or "")
        if not match:
            continue
        series, year, month, serial = match.groups()
        number = f"{series}-{year}-{month}-{int(serial):04d}"
        if number == voucher.number:
            continue
        voucher.number = number
        voucher.save(update_fields=["number"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0019_voucher_number_hyphen"),
    ]

    operations = [
        migrations.RunPython(four_digit_serial, migrations.RunPython.noop),
    ]
