from django import forms


class FilteredSelect(forms.Select):
    """Select enhanced in the browser into a typeable, keyboard-navigable list."""

    def __init__(self, *args, **kwargs):
        attrs = dict(kwargs.pop("attrs", None) or {})
        classes = " ".join(
            part for part in (attrs.get("class", ""), "form-select", "js-filtered-select") if part
        )
        attrs["class"] = classes
        super().__init__(*args, attrs=attrs, **kwargs)


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
