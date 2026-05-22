from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("mis", "0006_alter_expensedetail_expenses_paid_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="expensedetail",
            options={
                "ordering": ["-date", "-id"],
                "verbose_name": "client expense",
                "verbose_name_plural": "client expenses",
            },
        ),
    ]
