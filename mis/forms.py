from decimal import Decimal

from django import forms

from core.branch_access import approved_clients_for_user, client_allowed_for_user
from masters.models import Client

from .models import ExpenseDetail, FeesDetail, Receipt


class ClientNamePanChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj: Client) -> str:
        name = (obj.client_name or "").strip()
        pan = (obj.pan or "").strip().upper()
        if pan:
            return f"{name} — {pan}"
        return name


def _client_field(queryset=None):
    qs = queryset if queryset is not None else Client.approved_objects().order_by("client_name")
    return ClientNamePanChoiceField(
        queryset=qs,
        label="Client name",
        widget=forms.HiddenInput(attrs={"data-mis-client-hidden": "1"}),
    )


class _ClientAutocompleteMixin:
    client_search = forms.CharField(
        label="Client name",
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Type client name or PAN…",
                "autocomplete": "off",
                "data-mis-client-search": "1",
            }
        ),
        help_text="Start typing client name or PAN and choose from suggestions.",
    )

    def __init__(self, *args, user=None, **kwargs):
        self._mis_user = user
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["client"] = _client_field(approved_clients_for_user(user))
        if getattr(self.instance, "pk", None) and getattr(self.instance, "client_id", None):
            c = getattr(self.instance, "client", None)
            if c:
                self.fields["client_search"].initial = ClientNamePanChoiceField(
                    queryset=Client.objects.none()
                ).label_from_instance(c)

    def clean(self):
        data = super().clean()
        if not data.get("client"):
            self.add_error("client_search", "Please select a client from the suggestions.")
            return data
        client = data["client"]
        if self._mis_user and not client_allowed_for_user(self._mis_user, client):
            self.add_error("client_search", "This client is not in your branch.")
        return data


class FeesDetailForm(_ClientAutocompleteMixin, forms.ModelForm):
    client = _client_field()

    class Meta:
        model = FeesDetail
        fields = ["date", "client", "fees_amount", "gst_amount"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "fees_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "gst_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }

    def clean(self):
        data = super().clean()
        fees = data.get("fees_amount") or Decimal("0.00")
        gst = data.get("gst_amount") or Decimal("0.00")
        if gst < 0 or fees < 0:
            raise forms.ValidationError("Amounts cannot be negative.")
        if fees == Decimal("0.00") and gst > Decimal("0.00"):
            self.add_error("gst_amount", "GST amount cannot be entered when Fees amount is 0.")
        return data


class ReceiptForm(_ClientAutocompleteMixin, forms.ModelForm):
    client = _client_field()

    class Meta:
        model = Receipt
        fields = ["date", "client", "amount_received"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "amount_received": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }


class ExpenseDetailForm(_ClientAutocompleteMixin, forms.ModelForm):
    client = _client_field()

    class Meta:
        model = ExpenseDetail
        fields = ["date", "client", "expenses_paid", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "expenses_paid": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "notes": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional notes"}),
        }
