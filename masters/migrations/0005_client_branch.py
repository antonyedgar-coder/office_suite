from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0004_directormapping_reason_for_cessation"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="branch",
            field=models.CharField(
                choices=[("Trivandrum", "Trivandrum"), ("Nagercoil", "Nagercoil")],
                default="Trivandrum",
                max_length=32,
            ),
            preserve_default=False,
        ),
    ]
