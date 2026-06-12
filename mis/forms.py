from decimal import Decimal

from django import forms

from core.branch_access import approved_clients_for_user, client_allowed_for_user

from masters.models import Client, ExpenseCategory



from .models import ExpenseDetail, FeesDetail, Receipt, TenderDetail





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


def _mis_client_queryset(user, instance=None):
    """Clients allowed in the hidden client field (validated on save)."""
    if user is not None:
        qs = approved_clients_for_user(user)
    else:
        qs = Client.approved_objects().all()
    saved_pk = None
    if instance is not None and getattr(instance, "pk", None):
        saved_pk = getattr(instance, "client_id", None)
    if saved_pk and not qs.filter(pk=saved_pk).exists():
        return Client.objects.filter(pk=saved_pk).order_by("client_name")
    return qs.order_by("client_name")





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

        self.fields["client"] = _client_field(_mis_client_queryset(user, self.instance))

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

        fields = ["date", "client", "fees_amount", "expenses_invoice_amount", "gst_amount", "remarks"]

        widgets = {

            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),

            "fees_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),

            "expenses_invoice_amount": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "id": "id_expenses_invoice_amount"}
            ),

            "gst_amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "id": "id_gst_amount"}),

            "remarks": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Optional remarks"}
            ),

        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expenses_invoice_amount"].label = "Expenses invoice"
        self.fields["fees_amount"].widget.attrs.setdefault("id", "id_fees_amount")

    def clean(self):

        data = super().clean()

        fees = data.get("fees_amount") or Decimal("0.00")

        expenses_invoice = data.get("expenses_invoice_amount") or Decimal("0.00")

        gst = data.get("gst_amount") or Decimal("0.00")

        if gst < 0 or fees < 0 or expenses_invoice < 0:

            raise forms.ValidationError("Amounts cannot be negative.")

        if fees == Decimal("0.00") and expenses_invoice == Decimal("0.00") and gst > Decimal("0.00"):

            self.add_error(
                "gst_amount",
                "GST amount cannot be entered when Fees and Expenses invoice are both zero.",
            )

        return data





class ReceiptForm(_ClientAutocompleteMixin, forms.ModelForm):

    client = _client_field()

    class Meta:
        model = Receipt
        fields = ["date", "client", "fees_received", "expenses_received", "remarks"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "fees_received": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "expenses_received": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "remarks": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Optional remarks"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fees_received"].label = "Fees received"
        self.fields["expenses_received"].label = "Expenses received"
        self.fields["fees_received"].widget.attrs.setdefault("id", "id_fees_received")
        self.fields["expenses_received"].widget.attrs.setdefault("id", "id_expenses_received")

    def clean(self):
        data = super().clean()
        fees = data.get("fees_received") or Decimal("0")
        expenses = data.get("expenses_received") or Decimal("0")
        if fees <= 0 and expenses <= 0:
            raise forms.ValidationError(
                "Enter Fees received and/or Expenses received (at least one must be greater than zero)."
            )
        return data





class ExpenseDetailForm(_ClientAutocompleteMixin, forms.ModelForm):

    client = _client_field()

    class Meta:
        model = ExpenseDetail
        fields = ["date", "client", "category", "payment_mode", "expenses_paid", "remarks"]
        widgets = {
            "category": forms.Select(attrs={"class": "form-select"}),
            "payment_mode": forms.Select(attrs={"class": "form-select"}),
            "expenses_paid": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "remarks": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Optional remarks"}
            ),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        category_qs = ExpenseCategory.objects.filter(is_active=True)
        saved_cat = getattr(self.instance, "category_id", None) if getattr(self.instance, "pk", None) else None
        if saved_cat and not category_qs.filter(pk=saved_cat).exists():
            category_qs = ExpenseCategory.objects.filter(pk=saved_cat)
        self.fields["category"].queryset = category_qs.order_by("name")
        self.fields["category"].empty_label = "Select category…"
        self.fields["category"].label = "Category"
        self.fields["payment_mode"].label = "Payment mode"
        self.fields["expenses_paid"].label = "Amount"

    def clean(self):
        data = super().clean()
        amt = data.get("expenses_paid")
        if amt is not None and amt <= Decimal("0"):
            self.add_error("expenses_paid", "Amount must be greater than zero.")
        return data


class TenderDetailForm(_ClientAutocompleteMixin, forms.ModelForm):
    client = _client_field()

    class Meta:
        model = TenderDetail
        fields = ["date", "client", "tender_fees", "tender_deposit", "remarks"]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "tender_fees": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "tender_deposit": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "remarks": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Optional remarks"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tender_fees"].widget.attrs.setdefault("id", "id_tender_fees")
        self.fields["tender_deposit"].widget.attrs.setdefault("id", "id_tender_deposit")

    def clean(self):
        data = super().clean()
        fees = data.get("tender_fees") or Decimal("0.00")
        dep = data.get("tender_deposit") or Decimal("0.00")
        if fees < 0 or dep < 0:
            raise forms.ValidationError("Amounts cannot be negative.")
        if fees == Decimal("0.00") and dep == Decimal("0.00"):
            raise forms.ValidationError("Enter tender fees and/or tender deposit.")
        return data

