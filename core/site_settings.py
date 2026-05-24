"""Load singleton office branding settings."""

from __future__ import annotations

from django.db.utils import OperationalError, ProgrammingError

from .models import SiteSettings


def get_site_settings() -> SiteSettings:
    try:
        return SiteSettings.load()
    except (OperationalError, ProgrammingError):
        # Fail-safe for live: if migrations aren't applied yet,
        # don't take down the whole site just to render branding.
        return SiteSettings(company_name="", logo=None)
