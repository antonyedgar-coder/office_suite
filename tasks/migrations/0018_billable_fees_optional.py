from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0017_remove_taskmaster_default_fees_amount"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "DROP INDEX IF EXISTS tasks_task_verifie_0f89e4_idx;"
                        "DROP INDEX IF EXISTS tasks_task_verifier_status_idx;"
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.RemoveIndex(
                    model_name="task",
                    name="tasks_task_verifie_0f89e4_idx",
                ),
            ],
        ),
        migrations.RemoveConstraint(
            model_name="task",
            name="tasks_task_billable_requires_fees",
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="CREATE INDEX IF NOT EXISTS tasks_task_status_idx ON tasks_task (status);",
                    reverse_sql="DROP INDEX IF EXISTS tasks_task_status_idx;",
                ),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="task",
                    index=models.Index(fields=["status"], name="tasks_task_status_idx"),
                ),
            ],
        ),
    ]
