from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.forms import BaseFormSet, formset_factory

from core.activity_remarks import ACTIVITY_REMARKS_MAX_LENGTH

from .models import (
    CESSATION_REASON_CHOICES,
    Client,
    ClientDSC,
    ClientGroup,
    ClientPortalCredential,
    DSCInOut,
    ExpenseCategory,
    PortalName,
    DIRECTOR_COMPANY_TYPES,
    DIRECTOR_ELIGIBLE_CLIENT_TYPES,
    DirectorMapping,
)

REMARKS_WIDGET = forms.Textarea(
    attrs={"class": "form-control", "rows": 2, "placeholder": "Optional remarks"}
)


class ExpenseCategoryForm(forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ["name", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Category name"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class ClientGroupForm(forms.ModelForm):
    class Meta:
        model = ClientGroup
        fields = ["name", "notes", "is_active"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault("class", "form-check-input")
            elif isinstance(w, forms.Select):
                w.attrs.setdefault("class", "form-select")
            else:
                w.attrs.setdefault("class", "form-control")
        self.fields["name"].widget.attrs.setdefault("placeholder", "Group name (stored uppercase)")


class ClientForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for name, field in self.fields.items():
            widget = field.widget
            # Checkbox
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
                continue

            # Select
            if isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
                continue

            # Text-like inputs
            widget.attrs.setdefault("class", "form-control")

        # Small UX defaults
        self.fields["client_name"].widget.attrs.setdefault("placeholder", "Client Name")
        cg = self.fields.get("client_group")
        if cg:
            qs = ClientGroup.objects.filter(is_active=True).order_by("name")
            if self.instance and self.instance.pk and getattr(self.instance, "client_group_id", None):
                qs = ClientGroup.objects.filter(
                    Q(is_active=True) | Q(pk=self.instance.client_group_id)
                ).order_by("name")
            cg.queryset = qs
            cg.required = False
            cg.widget = forms.HiddenInput(attrs={"data-client-group-hidden": "1"})
        self.fields["file_no"].widget.attrs.setdefault("placeholder", "File No (optional)")
        self.fields["pan"].widget.attrs.setdefault("placeholder", "AAAAA9999A (optional for Foreign Citizen)")
        self.fields["passport_no"].widget.attrs.setdefault(
            "placeholder", "Individual or Foreign Citizen only"
        )
        self.fields["aadhaar_no"].widget.attrs.setdefault(
            "placeholder", "12 digits (optional, Individual or Foreign Citizen)"
        )
        self.fields["gstin"].widget.attrs.setdefault("placeholder", "15 characters (optional)")
        self.fields["dob"].widget.attrs.setdefault("placeholder", "DD-MM-YYYY (optional)")
        self.fields["llpin"].widget.attrs.setdefault("placeholder", "AAA-9999 (LLP only)")
        self.fields["cin"].widget.attrs.setdefault("placeholder", "21 characters (optional)")
        self.fields["din"].widget.attrs.setdefault("placeholder", "8 digits (Individual Director only)")

    class Meta:
        model = Client
        fields = [
            "client_type",
            "branch",
            "client_name",
            "client_group",
            "file_no",
            "pan",
            "passport_no",
            "aadhaar_no",
            "gstin",
            "dob",
            "llpin",
            "cin",
            "is_director",
            "din",
            "address",
            "contact_person",
            "mobile",
            "email",
            "remarks",
        ]
        widgets = {
            "address": forms.TextInput(attrs={"placeholder": "Address"}),
            "dob": forms.DateInput(attrs={"type": "date"}),
            "remarks": REMARKS_WIDGET,
        }


class _DirectorClientChoiceField(forms.ModelChoiceField):
    """Display label for datalist search (director = Individual or Foreign Citizen + DIN in Client Master)."""

    def label_from_instance(self, obj: Client) -> str:
        name = (obj.client_name or "").strip()
        din = (obj.din or "").strip()
        cid = obj.pk
        return f"{name} — DIN {din} — {cid}"


class _CompanyClientChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj: Client) -> str:
        name = (obj.client_name or "").strip()
        reg_bits = []
        if (obj.cin or "").strip():
            reg_bits.append(f"CIN {obj.cin.strip().upper()}")
        if (obj.llpin or "").strip():
            reg_bits.append(f"LLPIN {obj.llpin.strip().upper()}")
        reg = " · ".join(reg_bits)
        base = f"{name} — {obj.pk} ({obj.client_type})"
        return f"{base} — {reg}" if reg else base


class DirectorForm(forms.ModelForm):
    director = _DirectorClientChoiceField(
        queryset=Client.objects.none(),
        label="Director",
        widget=forms.HiddenInput(attrs={"data-dir-mapping-hidden": "director"}),
    )
    company = _CompanyClientChoiceField(
        queryset=Client.objects.none(),
        label="Company / LLP",
        widget=forms.HiddenInput(attrs={"data-dir-mapping-hidden": "company"}),
    )

    class Meta:
        model = DirectorMapping
        fields = [
            "company",
            "director",
            "appointed_date",
            "cessation_date",
            "reason_for_cessation",
            "remarks",
        ]
        widgets = {
            "appointed_date": forms.DateInput(attrs={"type": "date"}),
            "cessation_date": forms.DateInput(attrs={"type": "date"}),
            "reason_for_cessation": forms.Select(attrs={"class": "form-select"}),
            "remarks": REMARKS_WIDGET,
        }

    def clean(self):
        data = super().clean()
        ad = data.get("appointed_date")
        cd = data.get("cessation_date")
        reason = (data.get("reason_for_cessation") or "").strip()
        if cd and not ad:
            self.add_error("cessation_date", "Cessation date cannot be chosen without an appointment date.")
        if cd and ad and cd < ad:
            self.add_error("cessation_date", "Cessation date cannot be before appointment date.")
        if cd and not reason:
            self.add_error("reason_for_cessation", "Reason for cessation is required when a cessation date is entered.")
        if reason and not cd:
            self.add_error("reason_for_cessation", "Reason for cessation should be blank unless a cessation date is entered.")
        return data

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        from core.branch_access import approved_clients_for_user

        dir_qs = (
            approved_clients_for_user(user)
            .filter(client_type__in=sorted(DIRECTOR_ELIGIBLE_CLIENT_TYPES), is_director=True)
            .exclude(din="")
            .order_by("client_name")
        )
        comp_qs = approved_clients_for_user(user).filter(client_type__in=sorted(DIRECTOR_COMPANY_TYPES)).order_by("client_name")
        self.fields["director"].queryset = dir_qs
        self.fields["company"].queryset = comp_qs
        self.fields["appointed_date"].required = False
        self.fields["reason_for_cessation"].required = False
        self.fields["reason_for_cessation"].choices = [("", "---------")] + list(CESSATION_REASON_CHOICES)

        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.HiddenInput):
                continue
            if name == "reason_for_cessation":
                continue  # Meta.widgets already set class
            if isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class DirectorCompanyPickForm(forms.Form):
    """Company / LLP chosen first when mapping multiple directors in one go."""

    company = _CompanyClientChoiceField(
        queryset=Client.objects.none(),
        label="Company / LLP",
        widget=forms.HiddenInput(attrs={"data-dir-mapping-hidden": "company"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from core.branch_access import approved_clients_for_user

        comp_qs = approved_clients_for_user(user).filter(client_type__in=sorted(DIRECTOR_COMPANY_TYPES)).order_by("client_name")
        self.fields["company"].queryset = comp_qs


class DirectorMappingRowForm(forms.Form):
    """One director line under a fixed company (used in a formset on create)."""

    director = _DirectorClientChoiceField(
        queryset=Client.objects.none(),
        label="Director",
        required=False,
        widget=forms.HiddenInput(attrs={"class": "js-dm-dir-hidden"}),
    )
    appointed_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    cessation_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
    )
    reason_for_cessation = forms.ChoiceField(
        choices=[("", "---------")] + list(CESSATION_REASON_CHOICES),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    remarks = forms.CharField(
        required=False,
        max_length=ACTIVITY_REMARKS_MAX_LENGTH,
        widget=REMARKS_WIDGET,
        label="Remarks",
    )

    def __init__(self, *args, director_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = director_queryset if director_queryset is not None else Client.objects.none()
        self.fields["director"].queryset = qs

    def clean(self):
        data = super().clean()
        director = data.get("director")
        ad = data.get("appointed_date")
        cd = data.get("cessation_date")
        reason = (data.get("reason_for_cessation") or "").strip()
        remarks = (data.get("remarks") or "").strip()

        if not director and not ad and not cd and not reason and not remarks:
            return data

        if ad and not director:
            self.add_error("director", "Director is required when an appointed date is entered.")

        if cd and not ad:
            self.add_error("cessation_date", "Cessation date cannot be chosen without an appointment date.")
        if cd and ad and cd < ad:
            self.add_error("cessation_date", "Cessation date cannot be before appointment date.")
        if cd and not reason:
            self.add_error(
                "reason_for_cessation",
                "Reason for cessation is required when a cessation date is entered.",
            )
        if reason and not cd:
            self.add_error(
                "reason_for_cessation",
                "Reason for cessation should be blank unless a cessation date is entered.",
            )
        return data


class BaseDirectorMappingRowFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        seen_dated: set[tuple[int, object]] = set()
        seen_no_appointed: set[int] = set()
        filled = 0
        for form in self.forms:
            if not form.cleaned_data:
                continue
            director = form.cleaned_data.get("director")
            ad = form.cleaned_data.get("appointed_date")
            cd = form.cleaned_data.get("cessation_date")
            reason = (form.cleaned_data.get("reason_for_cessation") or "").strip()
            remarks = (form.cleaned_data.get("remarks") or "").strip()
            if not director and not ad and not cd and not reason and not remarks:
                continue
            if not director:
                continue
            filled += 1
            if ad is not None:
                key = (director.pk, ad)
                if key in seen_dated:
                    form.add_error(None, "The same director and appointed date cannot appear twice on this page.")
                else:
                    seen_dated.add(key)
            else:
                if director.pk in seen_no_appointed:
                    form.add_error(
                        None,
                        "The same director cannot appear twice without an appointed date on this page.",
                    )
                else:
                    seen_no_appointed.add(director.pk)
        if filled == 0:
            raise ValidationError("Add at least one director row (select a director for each line you use).")


DirectorMappingRowFormSet = formset_factory(
    DirectorMappingRowForm,
    formset=BaseDirectorMappingRowFormSet,
    extra=0,
    min_num=0,
    can_delete=False,
)


class ClientNamePanChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj: Client) -> str:
        name = (obj.client_name or "").strip()
        pan = (obj.pan or "").strip().upper()
        if pan:
            return f"{name} — {pan}"
        return name


class ClientPortalCredentialForm(forms.ModelForm):
    client_search = forms.CharField(
        required=False,
        label="Client name",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "id": "portalClientSearch",
                "list": "portalClientSuggestions",
                "placeholder": "Type client name or PAN…",
                "autocomplete": "off",
            }
        ),
    )

    class Meta:
        model = ClientPortalCredential
        fields = ["client", "portal", "portal_username", "portal_password"]
        widgets = {
            "portal": forms.Select(attrs={"class": "form-select", "id": "id_portal"}),
            "portal_username": forms.TextInput(attrs={"class": "form-control"}),
            "portal_password": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        from core.branch_access import approved_clients_for_user

        qs = approved_clients_for_user(user).order_by("client_name") if user else Client.approved_objects().order_by("client_name")
        self.fields["client"] = ClientNamePanChoiceField(
            queryset=qs,
            label="Client",
            widget=forms.HiddenInput(attrs={"data-portal-client-hidden": "1"}),
        )
        self.fields["client"].required = True
        self.fields["portal"].queryset = PortalName.objects.filter(is_active=True).order_by("name")
        self.fields["portal"].label = "Portal name"
        self.fields["portal"].required = True
        self.fields["portal_username"].required = True
        if self.instance and self.instance.pk:
            self.fields["portal_password"].required = False
            self.fields["portal_password"].help_text = "Leave blank to keep the current password."
        else:
            self.fields["portal_password"].required = True

    def clean_portal_password(self):
        value = (self.cleaned_data.get("portal_password") or "").strip()
        if self.instance and self.instance.pk and not value:
            return self.instance.portal_password
        if not value:
            raise ValidationError("Password is required.")
        return value

    def clean(self):
        data = super().clean()
        client = data.get("client")
        search = (data.get("client_search") or "").strip()
        if client is None and search:
            self.add_error("client_search", "Select a client from the suggestions.")
        return data


def individual_clients_for_user(user):
    from core.branch_access import approved_clients_for_user

    return (
        approved_clients_for_user(user)
        .filter(client_type="Individual")
        .select_related("client_group")
        .order_by("client_name")
    )


class ClientDSCForm(forms.ModelForm):
    client_search = forms.CharField(
        required=False,
        label="Client name",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "id": "dscClientSearch",
                "list": "dscClientSuggestions",
                "placeholder": "Type client name or PAN…",
                "autocomplete": "off",
            }
        ),
    )

    class Meta:
        model = ClientDSC
        fields = ["client", "issue_date", "expiry_date", "expiry_notification", "dsc_password"]
        widgets = {
            "issue_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "expiry_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "expiry_notification": forms.RadioSelect(
                choices=[(True, "Yes"), (False, "No")],
                attrs={"class": "form-check-input"},
            ),
            "dsc_password": forms.TextInput(attrs={"class": "form-control", "autocomplete": "off"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = individual_clients_for_user(user) if user else Client.approved_objects().filter(client_type="Individual")
        self.fields["client"] = ClientNamePanChoiceField(
            queryset=qs,
            label="Client",
            widget=forms.HiddenInput(attrs={"data-dsc-client-hidden": "1"}),
        )
        self.fields["client"].required = True
        self.fields["issue_date"].required = True
        self.fields["expiry_date"].required = True
        self.fields["expiry_notification"].label = "Expiry notification"
        self.fields["expiry_notification"].required = True
        self.fields["expiry_notification"].help_text = (
            "If Yes, reminders are sent from 30 days before expiry every 7 days "
            "(for this client's latest DSC only). Stops when set to No or a newer DSC is added."
        )
        if self.instance and self.instance.pk:
            self.fields["dsc_password"].required = False
            self.fields["dsc_password"].help_text = "Leave blank to keep the current password."
        else:
            self.fields["dsc_password"].required = True

    def clean_client(self):
        client = self.cleaned_data.get("client")
        if client and client.client_type != "Individual":
            raise ValidationError("DSC can only be created for Individual clients.")
        return client

    def clean_dsc_password(self):
        value = (self.cleaned_data.get("dsc_password") or "").strip()
        if self.instance and self.instance.pk and not value:
            return self.instance.dsc_password
        if not value:
            raise ValidationError("DSC password is required.")
        return value

    def clean(self):
        data = super().clean()
        client = data.get("client")
        search = (data.get("client_search") or "").strip()
        if client is None and search:
            self.add_error("client_search", "Select a client from the suggestions (Individual only).")
        issue = data.get("issue_date")
        expiry = data.get("expiry_date")
        if issue and expiry and expiry < issue:
            self.add_error("expiry_date", "Expiry date must be on or after issue date.")
        return data


class DSCInOutForm(forms.ModelForm):
    """Record handover: out date and remarks (in date is set when New DSC is created)."""

    class Meta:
        model = DSCInOut
        fields = ["out_date", "remarks"]
        widgets = {
            "out_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "remarks": REMARKS_WIDGET,
        }

    def clean(self):
        data = super().clean()
        out_d = data.get("out_date")
        if self.instance and self.instance.pk and self.instance.in_date and out_d and out_d < self.instance.in_date:
            self.add_error("out_date", "Out date cannot be before in date.")
        return data

