from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_activitylog"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="branch_access",
            field=models.CharField(
                blank=True,
                choices=[("", "All branches"), ("Trivandrum", "Trivandrum"), ("Nagercoil", "Nagercoil")],
                default="",
                help_text="Restrict this user to one branch, or leave as All branches.",
                max_length=32,
                verbose_name="Branch access",
            ),
        ),
    ]
