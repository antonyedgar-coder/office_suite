from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseFormSet, formset_factory, inlineformset_factory
from django.utils import timezone

from .models import (
    MAIN_HEAD_CHOICES,
    VOUCHER_CONTRA,
    VOUCHER_PAYMENT,
    VOUCHER_PURCHASE,
    VOUCHER_RECEIPT,
    VOUCHER_SALES,
    VOUCHER_TYPE_CHOICES,
    Account,
    AccountGroup,
    Voucher,
    VoucherLine,
)


class MainHeadForm(forms.ModelForm):
    class Meta:
        model = AccountGroup
        fields = ["name", "main_head", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "main_head": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["main_head"].choices = MAIN_HEAD_CHOICES
        self.fields["main_head"].label = "Main head"

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.parent = None
        if commit:
            obj.save()
        return obj


class ParentGroupForm(forms.ModelForm):
    class Meta:
        model = AccountGroup
        fields = ["name", "parent", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "parent": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].label = "Primary group name"
        self.fields["parent"].label = "Main head"
        self.fields["parent"].queryset = AccountGroup.main_heads().filter(is_active=True).order_by("name")
        self.fields["parent"].required = True

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")
        if not parent or not parent.is_main_head():
            raise forms.ValidationError("Select a main head.")
        return parent


class AccountGroupForm(forms.ModelForm):
    class Meta:
        model = AccountGroup
        fields = ["name", "parent", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "parent": forms.HiddenInput(attrs={"id": "id_parent"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].label = "Account group name"
        self.fields["parent"].label = "Primary group"
        self.fields["parent"].queryset = AccountGroup.parent_groups().filter(is_active=True).order_by("name")
        self.fields["parent"].required = True

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")
        if not parent or not parent.is_parent_group():
            raise forms.ValidationError("Select a primary group.")
        return parent


class AccountForm(forms.ModelForm):
    primary_group = forms.ModelChoiceField(
        queryset=AccountGroup.objects.none(),
        widget=forms.Select(attrs={"class": "form-select", "id": "id_primary_group"}),
        label="Primary group",
        empty_label="Select primary group…",
    )
    secondary_group = forms.ModelChoiceField(
        queryset=AccountGroup.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select", "id": "id_secondary_group"}),
        label="Account group",
        empty_label="None — under primary group",
    )

    class Meta:
        model = Account
        fields = [
            "name",
            "address",
            "gstin",
            "gst_rate",
            "is_pure_agent",
            "hsn_code",
            "pan",
            "opening_balance",
            "is_active",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
            "gstin": forms.TextInput(attrs={"class": "form-control", "maxlength": "15"}),
            "gst_rate": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "is_pure_agent": forms.CheckboxInput(attrs={"class": "form-check-input", "id": "id_is_pure_agent"}),
            "hsn_code": forms.TextInput(attrs={"class": "form-control", "maxlength": "16"}),
            "pan": forms.TextInput(attrs={"class": "form-control", "maxlength": "10"}),
            "opening_balance": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        primary_qs = AccountGroup.parent_groups().filter(is_active=True).select_related("parent").order_by("name")
        secondary_qs = AccountGroup.account_groups().filter(is_active=True).select_related("parent").order_by("name")
        self.fields["primary_group"].queryset = primary_qs
        self.fields["secondary_group"].queryset = secondary_qs
        self.secondary_options = [
            {"id": g.pk, "label": g.name, "parent": g.parent_id} for g in secondary_qs
        ]
        self.fields["gst_rate"].required = False
        self.fields["is_pure_agent"].required = False
        self.fields["is_pure_agent"].label = "Pure agent"
        self.fields["hsn_code"].required = False
        self.fields["hsn_code"].label = "HSN / SAC"
        group = getattr(self.instance, "group", None)
        if group and group.pk:
            if group.is_account_group():
                self.fields["primary_group"].initial = group.parent_id
                self.fields["secondary_group"].initial = group.pk
            elif group.is_parent_group():
                self.fields["primary_group"].initial = group.pk

    def clean(self):
        data = super().clean()
        if data.get("is_pure_agent"):
            data["gst_rate"] = None
        primary = data.get("primary_group")
        secondary = data.get("secondary_group")
        if not primary or not primary.is_parent_group():
            self.add_error("primary_group", "Select a primary group (parent group).")
            return data
        if secondary:
            if not secondary.is_account_group() or secondary.parent_id != primary.pk:
                self.add_error("secondary_group", "Account group must belong to the selected primary group.")
                return data
            self.instance.group = secondary
        else:
            self.instance.group = primary
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if getattr(self.instance, "group_id", None):
            obj.group = self.instance.group
        if commit:
            obj.save()
        return obj


class VoucherForm(forms.ModelForm):
    class Meta:
        model = Voucher
        fields = ["voucher_type", "date", "narration"]
        widgets = {
            "voucher_type": forms.Select(attrs={"class": "form-select"}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "narration": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, locked_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["voucher_type"].choices = VOUCHER_TYPE_CHOICES
        if locked_type:
            self.fields["voucher_type"].initial = locked_type
            self.fields["voucher_type"].widget = forms.HiddenInput()
        if not self.is_bound and not self.instance.pk:
            self.fields["date"].initial = timezone.localdate()


class VoucherLineForm(forms.ModelForm):
    bill_alloc = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"class": "js-bill-alloc"}),
    )

    class Meta:
        model = VoucherLine
        fields = ["account", "debit", "credit"]
        widgets = {
            "account": forms.Select(attrs={"class": "form-select js-jv-account"}),
            "debit": forms.NumberInput(
                attrs={"class": "form-control js-jv-debit", "step": "0.01", "min": "0"}
            ),
            "credit": forms.NumberInput(
                attrs={"class": "form-control js-jv-credit", "step": "0.01", "min": "0"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(is_active=True).order_by("name")
        self.fields["account"].required = False
        self.fields["debit"].required = False
        self.fields["credit"].required = False
        self.fields["debit"].initial = Decimal("0.00")
        self.fields["credit"].initial = Decimal("0.00")


VoucherLineFormSet = inlineformset_factory(
    Voucher,
    VoucherLine,
    form=VoucherLineForm,
    extra=4,
    min_num=0,
    validate_min=False,
    can_delete=True,
)

JournalLineFormSet = inlineformset_factory(
    Voucher,
    VoucherLine,
    form=VoucherLineForm,
    extra=2,
    min_num=0,
    validate_min=False,
    can_delete=False,
)


class InvoicePartyForm(forms.Form):
    party = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        widget=forms.HiddenInput(attrs={"id": "id_party"}),
    )
    tax_kind = forms.ChoiceField(
        choices=(("gst", "GST"), ("ngst", "NON GST")),
        widget=forms.HiddenInput(),
        initial="ngst",
        required=False,
    )

    def __init__(self, *args, voucher_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .services import sundry_debtors_ledgers

        self.fields["party"].empty_label = "Select…"
        if voucher_type == VOUCHER_PURCHASE:
            self.fields["party"].queryset = Account.objects.filter(is_active=True).order_by("name")
            self.fields["party"].label = "Supplier"
            self.fields.pop("tax_kind", None)
        elif voucher_type == VOUCHER_RECEIPT:
            from .services import cash_equivalent_ledgers

            self.fields["party"].queryset = cash_equivalent_ledgers()
            self.fields["party"].label = "Mode of receipt"
            self.fields.pop("tax_kind", None)
        elif voucher_type == VOUCHER_PAYMENT:
            from .services import cash_equivalent_ledgers

            self.fields["party"].queryset = cash_equivalent_ledgers()
            self.fields["party"].label = "Mode of payment"
            self.fields.pop("tax_kind", None)
        else:
            self.fields["party"].queryset = sundry_debtors_ledgers()
            self.fields["party"].label = "Buyer"
        if voucher_type == VOUCHER_SALES:
            self.fields["tax_kind"].required = True
            self.fields["tax_kind"].label = "Invoice type"


class InvoiceItemForm(forms.Form):
    account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        required=False,
        widget=forms.HiddenInput(attrs={"class": "js-invoice-account"}),
    )
    amount = forms.DecimalField(
        required=False,
        min_value=Decimal("0.00"),
        decimal_places=2,
        max_digits=14,
        widget=forms.NumberInput(
            attrs={"class": "form-control text-end js-invoice-amount", "step": "0.01", "min": "0"}
        ),
    )
    bill_alloc = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"class": "js-bill-alloc"}),
    )

    def __init__(self, *args, voucher_type=None, **kwargs):
        super().__init__(*args, **kwargs)
        from .services import non_cash_ledgers

        if voucher_type == VOUCHER_PAYMENT:
            self.fields["account"].queryset = non_cash_ledgers()
        elif voucher_type == VOUCHER_CONTRA:
            from .services import cash_equivalent_ledgers

            self.fields["account"].queryset = cash_equivalent_ledgers()
        else:
            self.fields["account"].queryset = Account.objects.filter(is_active=True).order_by("name")
        self.fields["account"].empty_label = "Select account"
        self.fields["account"].label = "Account"
        self.fields["amount"].label = "Amount"

    def clean(self):
        data = super().clean()
        account = data.get("account")
        amount = data.get("amount") or Decimal("0.00")
        if account and amount <= 0:
            raise ValidationError("Enter an amount for the selected account.")
        if amount > 0 and not account:
            raise ValidationError("Select an account for the amount.")
        return data


class InvoiceItemBaseFormSet(BaseFormSet):
    def __init__(self, *args, voucher_type=None, **kwargs):
        self.voucher_type = voucher_type
        super().__init__(*args, **kwargs)

    def get_form_kwargs(self, index):
        kwargs = super().get_form_kwargs(index)
        kwargs["voucher_type"] = self.voucher_type
        return kwargs


InvoiceItemFormSet = formset_factory(InvoiceItemForm, extra=1, formset=InvoiceItemBaseFormSet)


class UnbilledInvoiceForm(forms.Form):
    invoice_date = forms.DateField(
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    with_gst = forms.TypedChoiceField(
        choices=(
            ("1", "GST series"),
            ("0", "Non-GST series"),
        ),
        coerce=str,
        widget=forms.Select(attrs={"class": "form-select"}),
        initial="1",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields["invoice_date"].initial = timezone.localdate()


class ReportPeriodForm(forms.Form):
    date_from = forms.DateField(
        label="From date",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    date_to = forms.DateField(
        label="To date",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )

    def clean(self):
        data = super().clean()
        date_from = data.get("date_from")
        date_to = data.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise ValidationError("From date cannot be after To date.")
        return data


class ReportDateForm(forms.Form):
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(is_active=True).order_by("name")


ALL_LEDGERS = "all"


class LedgerReportForm(forms.Form):
    date_from = forms.DateField(
        label="From date",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    date_to = forms.DateField(
        label="To date",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    account = forms.ChoiceField(
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "---------"), (ALL_LEDGERS, "All Ledger")]
        choices.extend(
            (str(pk), name)
            for pk, name in Account.objects.filter(is_active=True).order_by("name").values_list("pk", "name")
        )
        self.fields["account"].choices = choices
        self.fields["account"].label = "Account"

    def clean(self):
        data = super().clean()
        date_from = data.get("date_from")
        date_to = data.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise ValidationError("From date cannot be after To date.")
        return data


class TrialBalanceForm(forms.Form):
    date_from = forms.DateField(
        label="From date",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    date_to = forms.DateField(
        label="To date",
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    tb_report = forms.ChoiceField(
        label="TB Report",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    report_format = forms.ChoiceField(
        label="Report Format",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        from .services import TB_FORMAT_CHOICES, TB_FORMAT_TB, TB_REPORT_CHOICES, TB_REPORT_GROUP

        super().__init__(*args, **kwargs)
        self.fields["tb_report"].choices = TB_REPORT_CHOICES
        self.fields["report_format"].choices = TB_FORMAT_CHOICES
        self.fields["tb_report"].initial = TB_REPORT_GROUP
        self.fields["report_format"].initial = TB_FORMAT_TB

    def clean(self):
        data = super().clean()
        date_from = data.get("date_from")
        date_to = data.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise ValidationError("From date cannot be after To date.")
        return data
