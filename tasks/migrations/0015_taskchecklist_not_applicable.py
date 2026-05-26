from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0014_alter_task_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskchecklistitem",
            name="is_not_applicable",
            field=models.BooleanField(
                default=False,
                help_text="Marked N/A when this step does not apply to this task.",
            ),
        ),
    ]
