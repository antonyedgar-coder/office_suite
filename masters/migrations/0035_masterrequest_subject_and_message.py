from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0034_created_by"),
    ]

    operations = [
        migrations.AddField(
            model_name="masterrequest",
            name="subject",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.RenameField(
            model_name="masterrequest",
            old_name="remarks",
            new_name="message",
        ),
    ]
