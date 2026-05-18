from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dirkyc", "0002_alter_dir3kyc_director"),
    ]

    operations = [
        migrations.AddField(
            model_name="dir3kyc",
            name="remarks",
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
