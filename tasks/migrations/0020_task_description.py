from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0019_rename_tasks_task_status_idx_tasks_task_status_4a0a95_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="description",
            field=models.CharField(blank=True, max_length=50),
        ),
    ]
