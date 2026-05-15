from datetime import date

from django.core.exceptions import ValidationError
from django.db import models

from masters.models import Client, DIRECTOR_ELIGIBLE_CLIENT_TYPES

from .fy import earliest_next_dirkyc_allowed_date, fy_label_for_date, next_allowed_fy_label_for_done_date


class Dir3Kyc(models.Model):
    """
    One MCA DIR-3 / DIR e-KYC filing record for a director from Client Master.
    """

    director = models.ForeignKey(
        "masters.Client",
        on_delete=models.PROTECT,
        related_name="dir3_kyc_records",
        help_text="Individual or Foreign Citizen director with DIN from Client Master.",
    )
    date_done = models.DateField("Date of DIR-3 KYC done")
    srn = models.CharField("SRN (DIR e-KYC)", max_length=40)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_done", "-id"]
        verbose_name = "DIR-3 KYC record"
        verbose_name_plural = "DIR-3 KYC records"

    def __str__(self) -> str:
        return f"DIR-3 KYC {self.director_id} {self.date_done}"

    def clean(self):
        super().clean()
        errors: dict[str, list[str]] = {}

        if self.director_id:
            d = self.director
            if d.client_type not in DIRECTOR_ELIGIBLE_CLIENT_TYPES:
                errors.setdefault("director", []).append(
                    "Director must be an Individual or Foreign Citizen client marked as a director."
                )
            if d.approval_status != Client.APPROVED:
                errors.setdefault("director", []).append(
                    "Director must be an approved Client Master record before recording DIR-3 KYC."
                )
            if not d.is_director:
                errors.setdefault("director", []).append(
                    "Selected client is not marked as a director in Client Master."
                )
            if not (d.din or "").strip():
                errors.setdefault("director", []).append("Director DIN is required in Client Master.")

        if self.director_id and self.date_done:
            qs = Dir3Kyc.objects.filter(director_id=self.director_id)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            prev = qs.order_by("-date_done", "-id").first()
            if prev:
                earliest = earliest_next_dirkyc_allowed_date(prev.date_done)
                if self.date_done < earliest:
                    errors.setdefault("date_done", []).append(
                        f"The next DIR-3 e-KYC for this director is allowed only from {earliest.strftime('%d-%m-%Y')} "
                        f"(start of FY {fy_label_for_date(earliest)}). "
                        "Cadence is by financial year: any date in the same FY as the last filing counts the same "
                        f"(last filing FY was {fy_label_for_date(prev.date_done)})."
                    )

        if errors:
            raise ValidationError(errors)

    @property
    def fy_when_done_label(self) -> str:
        return fy_label_for_date(self.date_done)

    @property
    def next_allowed_from_date(self) -> date:
        return earliest_next_dirkyc_allowed_date(self.date_done)

    @property
    def next_allowed_fy_label(self) -> str:
        return next_allowed_fy_label_for_done_date(self.date_done)
