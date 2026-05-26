from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0035_masterrequest_subject_and_message"),
    ]

    operations = [
        migrations.AddField(
            model_name="portalname",
            name="portal_url",
            field=models.URLField(
                blank=True,
                help_text="Optional login URL for this portal (shown in password management).",
                max_length=500,
            ),
        ),
    ]
