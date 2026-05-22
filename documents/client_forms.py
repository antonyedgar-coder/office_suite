from django import forms

from core.branch_access import approved_clients_for_user
from masters.models import Client


class ApprovedClientChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj: Client) -> str:
        name = (obj.client_name or "").strip()
        pan = (obj.pan or "").strip().upper()
        if pan:
            return f"{name} — {pan}"
        return name


class ClientDocumentClientForm(forms.Form):
    """Pick an approved client (search + hidden id)."""

    client = ApprovedClientChoiceField(
        queryset=Client.objects.none(),
        widget=forms.HiddenInput(attrs={"data-doc-client-hidden": "1"}),
    )
    client_search = forms.CharField(
        required=False,
        label="Client",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "id": "docClientSearch",
                "list": "docClientSuggestions",
                "placeholder": "Type client name or PAN…",
                "autocomplete": "off",
            }
        ),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = approved_clients_for_user(user).filter(approval_status=Client.APPROVED).order_by(
            "client_name"
        )
        self.fields["client"] = ApprovedClientChoiceField(
            queryset=qs,
            widget=forms.HiddenInput(attrs={"data-doc-client-hidden": "1"}),
        )

    def clean(self):
        data = super().clean()
        client = data.get("client")
        search = (data.get("client_search") or "").strip()
        if client is None and search:
            self.add_error("client_search", "Select a client from the suggestions.")
        return data
