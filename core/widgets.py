from django import forms


class DualListSelectMultiple(forms.SelectMultiple):
    """Multi-select enhanced in the browser into available / allowed boxes."""

    def __init__(
        self,
        *args,
        available_label="Available activities",
        assigned_label="Allowed",
        size=14,
        **kwargs,
    ):
        attrs = dict(kwargs.pop("attrs", None) or {})
        classes = " ".join(part for part in (attrs.get("class", ""), "form-select", "js-dual-list") if part)
        attrs.update(
            {
                "class": classes,
                "size": str(size),
                "data-available-label": available_label,
                "data-assigned-label": assigned_label,
            }
        )
        super().__init__(*args, attrs=attrs, **kwargs)
