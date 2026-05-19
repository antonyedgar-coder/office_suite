from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0007_task_pending_assignment"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="taskmaster",
            name="default_is_billable",
        ),
        migrations.RemoveField(
            model_name="taskmaster",
            name="default_verifier",
        ),
        migrations.AlterField(
            model_name="taskmaster",
            name="default_fees_amount",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Suggested fee when creating a billable task (each task stores its own copy).",
                max_digits=12,
                null=True,
            ),
        ),
    ]
