from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0011_client_group_file_no"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="dob",
            field=models.DateField(blank=True, null=True, verbose_name="DOB"),
        ),
    ]

