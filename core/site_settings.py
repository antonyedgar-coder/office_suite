"""Load singleton office branding settings."""

from __future__ import annotations

from .models import SiteSettings


def get_site_settings() -> SiteSettings:
    return SiteSettings.load()
