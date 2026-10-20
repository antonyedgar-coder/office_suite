"""Office layout colours derived from Company branding."""

from __future__ import annotations

import re

DEFAULT_PRIMARY = "#0369a1"
DEFAULT_SIDEBAR = "#f1f5f9"

THEME_PRESETS: tuple[dict[str, str], ...] = (
    {"name": "Sky", "primary": "#0369a1", "sidebar": "#f1f5f9"},
    {"name": "Navy", "primary": "#1e3a5f", "sidebar": "#e8eef5"},
    {"name": "Teal", "primary": "#0f766e", "sidebar": "#ecfdf5"},
    {"name": "Forest", "primary": "#166534", "sidebar": "#f0fdf4"},
    {"name": "Maroon", "primary": "#9f1239", "sidebar": "#fff1f2"},
)

_HEX = re.compile(r"^#?[0-9A-Fa-f]{6}$")

_CHART_FALLBACK = (
    "#34d399",
    "#fbbf24",
    "#fb7185",
    "#a78bfa",
    "#22c55e",
    "#f97316",
    "#94a3b8",
    "#0ea5e9",
    "#e879f9",
)


def normalize_hex(value: str | None, default: str) -> str:
    raw = (value or "").strip()
    if not _HEX.fullmatch(raw):
        return default
    if not raw.startswith("#"):
        raw = f"#{raw}"
    return raw.lower()


def darken_hex(hex_color: str, factor: float = 0.18) -> str:
    color = normalize_hex(hex_color, DEFAULT_PRIMARY)
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    r = max(0, min(255, int(r * (1 - factor))))
    g = max(0, min(255, int(g * (1 - factor))))
    b = max(0, min(255, int(b * (1 - factor))))
    return f"#{r:02x}{g:02x}{b:02x}"


def chart_palette(primary: str) -> list[str]:
    lead = normalize_hex(primary, DEFAULT_PRIMARY)
    return [lead, *[c for c in _CHART_FALLBACK if c.lower() != lead]]


def resolved_theme(settings=None) -> dict[str, object]:
    primary = normalize_hex(getattr(settings, "theme_primary", None), DEFAULT_PRIMARY)
    sidebar = normalize_hex(getattr(settings, "theme_sidebar", None), DEFAULT_SIDEBAR)
    return {
        "primary": primary,
        "primary_hover": darken_hex(primary),
        "sidebar": sidebar,
        "chart_palette": chart_palette(primary),
    }
