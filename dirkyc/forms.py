from django import forms

from masters.models import Client, DIRECTOR_ELIGIBLE_CLIENT_TYPES

from .models import Dir3Kyc


def director_queryset():
    return (
        Client.approved_objects()
        .filter(
            client_type__in=sorted(DIRECTOR_ELIGIBLE_CLIENT_TYPES),
            is_director=True,
            din__isnull=False,
        )
        .exclude(din="")
        .order_by("client_name")
    )


class DirectorDinChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj: Client) -> str:
        name = (obj.client_name or "").strip()
        din = (obj.din or "").strip().upper()
        cid = (obj.client_id or "").strip()
        return f"{name} — DIN {din} — {cid}"


def _director_field():
    return DirectorDinChoiceField(
        queryset=director_queryset(),
        label="Director",
        widget=forms.HiddenInput(attrs={"data-dirkyc-director-hidden": "1"}),
    )


class _DirectorAutocompleteMixin:
    director_search = forms.CharField(
        label="Director",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Type director name, DIN, or Client ID…",
                "autocomplete": "off",
                "data-dirkyc-director-search": "1",
            }
        ),
        help_text="Choose a director from Client Master (Individual or Foreign Citizen, marked director, with DIN).",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if getattr(self.instance, "pk", None) and getattr(self.instance, "director_id", None):
            dr = getattr(self.instance, "director", None)
            if dr:
                self.fields["director_search"].initial = DirectorDinChoiceField(
                    queryset=Client.objects.none()
                ).label_from_instance(dr)

    def clean(self):
        data = super().clean()
        if not data.get("director"):
            self.add_error("director_search", "Please select a director from the suggestions.")
        return data


class Dir3KycForm(_DirectorAutocompleteMixin, forms.ModelForm):
    director = _director_field()

    class Meta:
        model = Dir3Kyc
        fields = ["director", "date_done", "srn"]
        widgets = {
            "date_done": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "srn": forms.TextInput(
                attrs={
                    "class": "form-control mono",
                    "placeholder": "MCA SRN",
                    "maxlength": "40",
                }
            ),
        }
