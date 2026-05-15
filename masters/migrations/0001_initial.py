from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClientSequence",
            fields=[
                ("prefix", models.CharField(max_length=1, primary_key=True, serialize=False)),
                ("last_value", models.PositiveIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name="Client",
            fields=[
                ("client_id", models.CharField(editable=False, max_length=6, primary_key=True, serialize=False)),
                ("client_type", models.CharField(choices=[("Individual", "Individual"), ("Partnership", "Partnership"), ("LLP", "LLP"), ("Private Limited", "Private Limited"), ("Public Limited", "Public Limited"), ("Nidhi Co", "Nidhi Co"), ("FPO", "FPO"), ("Trust", "Trust"), ("Sec 8 Co", "Sec 8 Co"), ("Society", "Society"), ("None", "None")], max_length=32)),
                ("client_name", models.CharField(max_length=200)),
                ("pan", models.CharField(blank=True, max_length=10)),
                ("gstin", models.CharField(blank=True, max_length=15)),
                ("llpin", models.CharField(blank=True, max_length=8)),
                ("cin", models.CharField(blank=True, max_length=21)),
                ("is_director", models.BooleanField(default=False)),
                ("din", models.CharField(blank=True, max_length=8)),
                ("address", models.CharField(blank=True, max_length=255)),
                ("contact_person", models.CharField(blank=True, max_length=120)),
                ("mobile", models.CharField(blank=True, max_length=20)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddIndex(
            model_name="client",
            index=models.Index(fields=["client_name"], name="masters_cli_client__ccf7fa_idx"),
        ),
        migrations.AddIndex(
            model_name="client",
            index=models.Index(fields=["pan"], name="masters_cli_pan_43a7a0_idx"),
        ),
        migrations.CreateModel(
            name="Director",
            fields=[
                ("name", models.CharField(max_length=200)),
                ("din", models.CharField(blank=True, max_length=8)),
                ("pan", models.CharField(blank=True, max_length=10)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("client", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name="director", serialize=False, to="masters.client")),
            ],
        ),
    ]

