from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0036_portalname_portal_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="clientdsc",
            name="remarks",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AlterField(
            model_name="clientdsc",
            name="dsc_password",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
