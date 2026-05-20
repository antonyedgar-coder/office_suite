from django.db import migrations, models


def _truncate_or_reset_client_sequences(apps, schema_editor):
    """
    Sequence keys used to be 2 characters (name+branch). New format is 1 character (name only).
    This app is currently in a test phase; safest behavior is to drop existing sequence rows.
    """
    ClientSequence = apps.get_model("masters", "ClientSequence")
    ClientSequence.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0027_client_type_new_client_one_off"),
    ]

    operations = [
        migrations.AlterField(
            model_name="clientsequence",
            name="prefix",
            field=models.CharField(max_length=1, primary_key=True, serialize=False),
        ),
        migrations.RunPython(_truncate_or_reset_client_sequences, migrations.RunPython.noop),
    ]

