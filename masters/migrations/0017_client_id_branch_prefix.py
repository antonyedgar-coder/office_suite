from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("masters", "0016_alter_client_options_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="clientsequence",
            name="prefix",
            field=models.CharField(max_length=2, primary_key=True, serialize=False),
        ),
    ]
