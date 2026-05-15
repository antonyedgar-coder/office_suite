from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0002_reportpolicy_mis_export_perms"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="reportpolicy",
            options={
                "default_permissions": (),
                "permissions": [
                    ("access_reports_menu", "Can access Reports menu and index"),
                    ("view_client_master_report", "Can view Client Master report"),
                    ("export_client_master_report", "Can export Client Master report CSV"),
                    ("export_mis_period_report", "Can export MIS Period report CSV"),
                    ("export_mis_client_wise_report", "Can export MIS Client Wise report CSV"),
                    ("export_mis_type_wise_report", "Can export MIS Type Wise report CSV"),
                    ("export_mis_report", "Can export MIS report CSV"),
                ],
                "verbose_name": "Report access policy",
                "verbose_name_plural": "Report access policies",
            },
        )
    ]

