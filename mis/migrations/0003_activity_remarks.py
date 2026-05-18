from django.db import migrations, models


def copy_expense_notes_to_remarks(apps, schema_editor):
    ExpenseDetail = apps.get_model("mis", "ExpenseDetail")
    for row in ExpenseDetail.objects.exclude(notes="").iterator():
        if not (row.remarks or "").strip() and (row.notes or "").strip():
            row.remarks = (row.notes or "").strip()[:500]
            row.save(update_fields=["remarks"])


class Migration(migrations.Migration):

    dependencies = [
        ("mis", "0002_tenderdetail"),
    ]

    operations = [
        migrations.AddField(
            model_name="feesdetail",
            name="remarks",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="receipt",
            name="remarks",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="expensedetail",
            name="remarks",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="tenderdetail",
            name="remarks",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.RunPython(copy_expense_notes_to_remarks, migrations.RunPython.noop),
    ]
