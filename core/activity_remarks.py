"""Shared optional remarks on transactional forms (client activity log)."""

from __future__ import annotations

from django import forms

ACTIVITY_REMARKS_MAX_LENGTH = 500

REMARKS_FORM_FIELD = forms.CharField(
    label="Remarks",
    required=False,
    max_length=ACTIVITY_REMARKS_MAX_LENGTH,
    widget=forms.Textarea(
        attrs={
            "class": "form-control",
            "rows": 2,
            "placeholder": "Optional remarks",
        }
    ),
)
