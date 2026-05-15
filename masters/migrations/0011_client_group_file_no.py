from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0010_client_maker_checker_approval"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="client_group",
            field=models.CharField(blank=True, max_length=120, verbose_name="Group"),
        ),
        migrations.AddField(
            model_name="client",
            name="file_no",
            field=models.CharField(blank=True, max_length=120, verbose_name="File No"),
        ),
    ]
