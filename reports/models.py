from django.db import models


class ReportPolicy(models.Model):
    """
    Anchor model for report-related permissions only (no business data).
    """

    label = models.CharField(max_length=80, default="default")

    class Meta:
        verbose_name = "Report access policy"
        verbose_name_plural = "Report access policies"
        default_permissions = ()
        permissions = [
            ("access_reports_menu", "Can access Reports menu and index"),
            ("view_client_master_report", "Can view Client Master report"),
            ("export_client_master_report", "Can export Client Master report CSV"),
            ("export_mis_period_report", "Can export MIS Period report CSV"),
            ("export_mis_client_wise_report", "Can export MIS Client Wise report CSV"),
            ("export_mis_type_wise_report", "Can export MIS Type Wise report CSV"),
            ("export_mis_report", "Can export MIS report CSV"),
            ("view_director_mapping_report", "Can view Director Mapping report"),
            ("export_director_mapping_report", "Can export Director Mapping report CSV"),
            ("view_dir3kyc_report", "Can view DIR-3 KYC report"),
            ("export_dir3kyc_report", "Can export DIR-3 KYC report CSV"),
        ]

    def __str__(self) -> str:
        return "Report permissions"
