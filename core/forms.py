from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from .models import SiteSettings
from .theme import DEFAULT_PRIMARY, DEFAULT_SIDEBAR, normalize_hex

_LOGO_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "webp", "svg"})
_LOGO_MAX_BYTES = 2 * 1024 * 1024


class SiteSettingsForm(forms.ModelForm):
    remove_logo = forms.BooleanField(
        required=False,
        label="Remove current logo",
    )

    class Meta:
        model = SiteSettings
        fields = ("company_name", "gstin", "address", "logo", "theme_primary", "theme_sidebar")
        widgets = {
            "company_name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. Sharma & Associates",
                }
            ),
            "gstin": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "maxlength": "15",
                    "placeholder": "15-character GSTIN",
                    "style": "text-transform: uppercase;",
                }
            ),
            "address": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Office address",
                }
            ),
            "logo": forms.FileInput(
                attrs={
                    "class": "form-control",
                    "accept": ".png,.jpg,.jpeg,.gif,.webp,.svg,image/*",
                }
            ),
            "theme_primary": forms.TextInput(
                attrs={
                    "class": "form-control form-control-color",
                    "type": "color",
                }
            ),
            "theme_sidebar": forms.TextInput(
                attrs={
                    "class": "form-control form-control-color",
                    "type": "color",
                }
            ),
        }

    def clean_logo(self):
        uploaded = self.cleaned_data.get("logo")
        if not uploaded:
            return uploaded
        size = getattr(uploaded, "size", 0) or 0
        if size > _LOGO_MAX_BYTES:
            raise ValidationError("Logo must be 2 MB or smaller.")
        name = (getattr(uploaded, "name", "") or "").lower()
        ext = name.rsplit(".", 1)[-1] if "." in name else ""
        if ext not in _LOGO_EXTENSIONS:
            allowed = ", ".join(sorted(_LOGO_EXTENSIONS))
            raise ValidationError(f"Logo must be one of: {allowed}.")
        return uploaded

    def clean_gstin(self):
        return (self.cleaned_data.get("gstin") or "").strip().upper()

    def clean_theme_primary(self):
        raw = self.cleaned_data.get("theme_primary")
        if not (raw or "").strip():
            return normalize_hex(getattr(self.instance, "theme_primary", None), DEFAULT_PRIMARY)
        return normalize_hex(raw, DEFAULT_PRIMARY)

    def clean_theme_sidebar(self):
        raw = self.cleaned_data.get("theme_sidebar")
        if not (raw or "").strip():
            return normalize_hex(getattr(self.instance, "theme_sidebar", None), DEFAULT_SIDEBAR)
        return normalize_hex(raw, DEFAULT_SIDEBAR)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get("remove_logo") and instance.logo:
            instance.logo.delete(save=False)
            instance.logo = None
        elif self.cleaned_data.get("logo") and self.instance.pk and self.instance.logo:
            self.instance.logo.delete(save=False)
        if commit:
            instance.save()
        return instance
