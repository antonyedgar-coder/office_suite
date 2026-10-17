from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0009_receiptallocation"),
    ]

    operations = [
        migrations.AddField(
            model_name="receiptallocation",
            name="is_opening",
            field=models.BooleanField(default=False),
        ),
    ]
