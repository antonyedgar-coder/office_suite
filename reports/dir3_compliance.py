"""Director-level DIR-3 KYC compliance rows for the reports UI."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import OuterRef, Subquery

from dirkyc.fy import (
    earliest_next_dirkyc_allowed_date,
    fy_label_for_date,
    fy_label_to_date_range,
    fy_start_year,
    next_allowed_fy_label_for_done_date,
)
from dirkyc.models import Dir3Kyc
from masters.models import Client, DIRECTOR_ELIGIBLE_CLIENT_TYPES

from .forms import DirectorMappingReportForm


@dataclass
class DirectorDir3ComplianceRow:
    client_id: str
    director_name: str
    din: str
    last_kyc_date: date | None
    last_kyc_fy_label: str
    next_allowed_from: date | None
    next_allowed_fy_label: str
    fy_since_last: str
    not_done_3fy: bool


def build_director_dir3_compliance_rows(
    cleaned: dict,
    *,
    as_of: date,
    limit: int = 500,
) -> list[DirectorDir3ComplianceRow]:
    """Directors matching compliance filters (may be truncated at `limit`)."""
    y_as_of = fy_start_year(as_of)

    last_sq = (
        Dir3Kyc.objects.filter(director=OuterRef("pk")).order_by("-date_done", "-id").values("date_done")[:1]
    )
    qs = (
        Client.approved_objects()
        .filter(client_type__in=sorted(DIRECTOR_ELIGIBLE_CLIENT_TYPES), is_director=True)
        .exclude(din="")
        .annotate(last_kyc_date=Subquery(last_sq))
    )

    if cleaned.get("director_scope") == DirectorMappingReportForm.SCOPE_FILTER:
        din = (cleaned.get("director_din") or "").strip()
        if din:
            qs = qs.filter(din__icontains=din.upper())
        name = (cleaned.get("director_name") or "").strip()
        if name:
            qs = qs.filter(client_name__icontains=name.upper())

    fy_pick = (cleaned.get("last_kyc_fy") or "").strip()
    if fy_pick:
        rng = fy_label_to_date_range(fy_pick)
        if rng:
            lo, hi = rng
            qs = qs.filter(last_kyc_date__gte=lo, last_kyc_date__lte=hi)

    dlf = cleaned.get("date_last_kyc_from")
    dlt = cleaned.get("date_last_kyc_to")
    if dlf:
        qs = qs.filter(last_kyc_date__gte=dlf)
    if dlt:
        qs = qs.filter(last_kyc_date__lte=dlt)

    qs = qs.order_by("client_name")

    din_not_done_3fy = bool(cleaned.get("din_not_done_3fy"))
    rows: list[DirectorDir3ComplianceRow] = []
    for c in qs.iterator(chunk_size=256):
        ld: date | None = c.last_kyc_date
        if din_not_done_3fy:
            if ld is not None and (y_as_of - fy_start_year(ld) < 4):
                continue

        if ld:
            last_fy = fy_label_for_date(ld)
            nxt = earliest_next_dirkyc_allowed_date(ld)
            nxt_fy = next_allowed_fy_label_for_done_date(ld)
            gap = y_as_of - fy_start_year(ld)
            gap_s = str(gap)
            not_done_3 = y_as_of - fy_start_year(ld) >= 4
        else:
            last_fy = "—"
            nxt = None
            nxt_fy = "—"
            gap_s = "N/A"
            not_done_3 = True

        rows.append(
            DirectorDir3ComplianceRow(
                client_id=c.client_id,
                director_name=c.client_name,
                din=(c.din or "").strip().upper(),
                last_kyc_date=ld,
                last_kyc_fy_label=last_fy,
                next_allowed_from=nxt,
                next_allowed_fy_label=nxt_fy,
                fy_since_last=gap_s,
                not_done_3fy=not_done_3,
            )
        )
        if len(rows) >= limit:
            break

    return rows
