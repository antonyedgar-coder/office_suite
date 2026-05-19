from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0009_document_checker_workflow"),
    ]

    operations = [
        migrations.AlterField(
            model_name="task",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending_assignment", "Awaiting assignment approval"),
                    ("assigned", "Pending"),
                    ("submitted", "Submitted"),
                    ("verified", "Verified"),
                    ("complete", "Complete"),
                    ("rework", "Rework"),
                    ("document_rework", "Document rework"),
                    ("cancelled", "Cancelled"),
                ],
                db_index=True,
                default="assigned",
                max_length=20,
            ),
        ),
    ]
