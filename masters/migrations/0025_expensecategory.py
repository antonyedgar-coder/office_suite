from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0024_clientdsc_expiry_notification"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExpenseCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "expense category",
                "verbose_name_plural": "expense categories",
                "ordering": ["name"],
            },
        ),
    ]
