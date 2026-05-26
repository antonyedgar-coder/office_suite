from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0016_multiple_verifiers"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="taskmaster",
            name="default_fees_amount",
        ),
    ]
