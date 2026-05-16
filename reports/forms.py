from datetime import date

from django import forms

from core.branch_access import branch_access_for_user
from dirkyc.fy import fy_start_year, mis_report_financial_year_choices
from masters.models import BRANCH_CHOICES, CLIENT_TYPES, Client


class ClientMasterReportFilterForm(forms.Form):
    """All filters optional; combined with AND when multiple are filled."""

    client_type = forms.ChoiceField(
        choices=[("", "— Any type —")] + list(CLIENT_TYPES),
        required=False,
    )
    branch = forms.ChoiceField(
        label="Branch",
        choices=[("", "— Any branch —")] + list(BRANCH_CHOICES),
        required=False,
    )
    client_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Contains (any part of name)"}),
    )
    din = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "DIN (partial match)", "maxlength": "8"}),
    )
    pan = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "PAN (partial match)", "maxlength": "10"}),
    )
    gstin = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "GSTIN (partial match)", "maxlength": "15"}),
    )
    cin = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "CIN (partial match)", "maxlength": "21"}),
    )
    llpin = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "LLPIN (partial match)", "maxlength": "8"}),
    )
    is_director = forms.ChoiceField(
        label="Director",
        choices=[
            ("", "— All clients —"),
            ("1", "Directors only"),
            ("0", "Non-directors only"),
        ],
        required=False,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name in ("client_type", "branch", "is_director"):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control form-control-sm")


class MISPeriodFilterForm(forms.Form):
    from_date = forms.DateField(widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    to_date = forms.DateField(widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))

    def clean(self):
        data = super().clean()
        f = data.get("from_date")
        t = data.get("to_date")
        if f and t and f > t:
            self.add_error("to_date", "To Date must be on/after From Date.")
        return data


class MISClientWiseFilterForm(MISPeriodFilterForm):
    clients = forms.ModelMultipleChoiceField(
        queryset=Client.approved_objects().order_by("client_name"),
        required=False,
        label="Client(s)",
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "8"}),
        help_text="Leave blank for all clients, or select one/multiple clients.",
    )


class MISTypeWiseFilterForm(MISPeriodFilterForm):
    client_type = forms.ChoiceField(
        choices=[("", "— All types —")] + list(CLIENT_TYPES),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Type of client",
    )


class MISFlexibleReportForm(MISPeriodFilterForm):
    VIEW_TRANSACTIONS = "transactions"
    VIEW_CLIENT_WISE = "client_wise"
    VIEW_TYPE_WISE = "type_wise"
    VIEW_MONTH_WISE = "month_wise"

    DETAILS_ALL = "ALL"
    DETAILS_FEES = "FEES"
    DETAILS_GST = "GST"
    DETAILS_RECEIPTS = "RECEIPTS"
    DETAILS_EXPENSES = "EXPENSES"

    report_view = forms.ChoiceField(
        choices=[
            (VIEW_TRANSACTIONS, "Transactions (date-wise)"),
            (VIEW_CLIENT_WISE, "Client Wise Report (consolidated)"),
            (VIEW_TYPE_WISE, "Type of Client Wise Report (consolidated)"),
            (VIEW_MONTH_WISE, "Month wise report"),
        ],
        required=False,
        initial=VIEW_TRANSACTIONS,
        label="Client report type",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    financial_years = forms.MultipleChoiceField(
        required=False,
        label="Financial year (FY)",
        choices=[],
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "6"}),
        help_text="",
    )

    branch = forms.ChoiceField(
        choices=[("", "All")] + list(BRANCH_CHOICES),
        required=False,
        label="Branch",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    details = forms.ChoiceField(
        required=False,
        choices=[
            (DETAILS_ALL, "ALL"),
            (DETAILS_FEES, "Fees"),
            (DETAILS_GST, "GST"),
            (DETAILS_RECEIPTS, "Receipts"),
            (DETAILS_EXPENSES, "Expenses"),
        ],
        initial=DETAILS_ALL,
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="",
    )

    client_id = forms.CharField(
        required=False,
        label="Client ID",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Type to search…",
                "list": "clientIdList",
                "autocomplete": "off",
            }
        ),
    )
    client_name = forms.CharField(
        required=False,
        label="Client name",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Type to search…",
                "list": "clientNameList",
                "autocomplete": "off",
            }
        ),
    )
    pan = forms.CharField(
        required=False,
        label="PAN No",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "maxlength": "10",
                "placeholder": "Type to search…",
                "list": "panList",
                "autocomplete": "off",
            }
        ),
    )
    client_type = forms.ChoiceField(
        choices=[("", "ALL")] + list(CLIENT_TYPES),
        required=False,
        label="Type of client",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["from_date"].required = False
        self.fields["to_date"].required = False
        self.fields["financial_years"].choices = mis_report_financial_year_choices(today=date.today())
        scope = branch_access_for_user(user)
        if scope:
            self.fields["branch"].choices = [(scope, scope)]
            if not self.data:
                self.fields["branch"].initial = scope
            self.fields["branch"].help_text = "Your user account is limited to this branch."

    def clean(self):
        data = super().clean()
        rv = (data.get("report_view") or self.VIEW_TRANSACTIONS).strip()
        if rv == self.VIEW_MONTH_WISE:
            fys = data.get("financial_years") or []
            if not fys:
                self.add_error("financial_years", "Select at least one financial year for month wise report.")
        else:
            if not data.get("from_date"):
                self.add_error("from_date", "Enter From date (or choose Month wise report).")
            if not data.get("to_date"):
                self.add_error("to_date", "Enter To date (or choose Month wise report).")
        return data

    def selected_details(self) -> list[str]:
        if not self.is_valid():
            return [self.DETAILS_FEES, self.DETAILS_GST, self.DETAILS_RECEIPTS, self.DETAILS_EXPENSES]
        v = self.cleaned_data.get("details") or self.DETAILS_ALL
        if v == self.DETAILS_ALL:
            return [self.DETAILS_FEES, self.DETAILS_GST, self.DETAILS_RECEIPTS, self.DETAILS_EXPENSES]
        return [v]


class DirectorMappingReportForm(forms.Form):
    """
    Flat view (both sides filtered, multiple companies and directors): one row per active
    appointment as on `as_of_date`, with full detail columns.

    "All companies": company-wise HTML table — client ID and company name merged (rowspan)
    per company; each current director seat as on `as_of_date` on its own row with DIN
    and appointment / cessation dates.

    "All directors": director-wise HTML table — DIN and director name merged per director;
    each company mapping (full history) on its own row with dates.

    Filter-only results for exactly one company or one director use the same merged layout.
    """

    SCOPE_ALL = "all"
    SCOPE_FILTER = "filter"

    as_of_date = forms.DateField(
        label="As on date",
        widget=forms.DateInput(attrs={"class": "form-control form-control-sm", "type": "date"}),
    )
    director_scope = forms.ChoiceField(
        label="Directors",
        choices=[
            (SCOPE_FILTER, "Filter by DIN / director name"),
            (SCOPE_ALL, "All directors"),
        ],
        initial=SCOPE_FILTER,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    director_din = forms.CharField(
        required=False,
        label="Director DIN",
        widget=forms.TextInput(
            attrs={"placeholder": "Type to search / filter", "maxlength": "8", "autocomplete": "off"}
        ),
    )
    director_name = forms.CharField(
        required=False,
        label="Director name",
        widget=forms.TextInput(attrs={"placeholder": "Type to search / filter", "autocomplete": "off"}),
    )
    company_scope = forms.ChoiceField(
        label="Companies",
        choices=[
            (SCOPE_FILTER, "Filter by company/LLP name or CIN/LLPIN"),
            (SCOPE_ALL, "All companies"),
        ],
        initial=SCOPE_FILTER,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    company_name = forms.CharField(
        required=False,
        label="Company / LLP name",
        widget=forms.TextInput(attrs={"placeholder": "Contains (any part of name)", "autocomplete": "off"}),
    )
    company_cin = forms.CharField(
        required=False,
        label="CIN / LLPIN",
        widget=forms.TextInput(attrs={"placeholder": "Partial match", "maxlength": "21", "autocomplete": "off"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.data and "as_of_date" not in (self.initial or {}):
            self.fields["as_of_date"].initial = date.today()
        for name, field in self.fields.items():
            if name not in ("as_of_date", "director_scope", "company_scope"):
                field.widget.attrs.setdefault("class", "form-control form-control-sm")


class Dir3KycReportForm(forms.Form):
    VIEW_FILINGS = "filings"
    VIEW_COMPLIANCE = "compliance"

    view_mode = forms.ChoiceField(
        label="Report layout",
        choices=[
            (VIEW_FILINGS, "All DIR-3 filings (one row per filing)"),
            (VIEW_COMPLIANCE, "Latest per director (compliance)"),
        ],
        initial=VIEW_FILINGS,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    director_scope = forms.ChoiceField(
        label="Directors",
        choices=[
            (DirectorMappingReportForm.SCOPE_FILTER, "Filter by DIN / director name"),
            (DirectorMappingReportForm.SCOPE_ALL, "All directors"),
        ],
        initial=DirectorMappingReportForm.SCOPE_FILTER,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    director_din = forms.CharField(
        required=False,
        label="Director DIN",
        widget=forms.TextInput(
            attrs={"placeholder": "Type to search / filter", "maxlength": "8", "autocomplete": "off"}
        ),
    )
    director_name = forms.CharField(
        required=False,
        label="Director name",
        widget=forms.TextInput(attrs={"placeholder": "Type to search / filter", "autocomplete": "off"}),
    )
    date_done_from = forms.DateField(
        required=False,
        label="KYC date from (filings view)",
        widget=forms.DateInput(attrs={"class": "form-control form-control-sm", "type": "date"}),
    )
    date_done_to = forms.DateField(
        required=False,
        label="KYC date to (filings view)",
        widget=forms.DateInput(attrs={"class": "form-control form-control-sm", "type": "date"}),
    )
    as_of_date = forms.DateField(
        required=False,
        label="As on date (compliance view)",
        widget=forms.DateInput(attrs={"class": "form-control form-control-sm", "type": "date"}),
        help_text='Used for "FY since last filing" and the >=3 FY rule.',
    )
    last_kyc_fy = forms.ChoiceField(
        required=False,
        label="DIR-3 KYC last FY",
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    din_not_done_3fy = forms.BooleanField(
        required=False,
        label="Only DINs with no DIR-3 for >=3 FY since last filing FY (or never filed)",
    )
    date_last_kyc_from = forms.DateField(
        required=False,
        label="Date of last KYC from",
        widget=forms.DateInput(attrs={"class": "form-control form-control-sm", "type": "date"}),
    )
    date_last_kyc_to = forms.DateField(
        required=False,
        label="Date of last KYC to",
        widget=forms.DateInput(attrs={"class": "form-control form-control-sm", "type": "date"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        y0 = fy_start_year(date.today())
        fy_choices = [("", "— Any —")]
        for dy in range(y0 - 15, y0 + 3):
            lbl = f"{dy}-{str(dy + 1)[-2:]}"
            fy_choices.append((lbl, lbl))
        self.fields["last_kyc_fy"].choices = fy_choices
        if not self.data and "as_of_date" not in (self.initial or {}):
            self.fields["as_of_date"].initial = date.today()
        for name, field in self.fields.items():
            if name in (
                "view_mode",
                "director_scope",
                "last_kyc_fy",
                "date_done_from",
                "date_done_to",
                "as_of_date",
                "date_last_kyc_from",
                "date_last_kyc_to",
            ):
                continue
            if name == "din_not_done_3fy":
                field.widget.attrs.setdefault("class", "form-check-input")
                continue
            field.widget.attrs.setdefault("class", "form-control form-control-sm")

    def clean(self):
        data = super().clean()
        df = data.get("date_done_from")
        dt = data.get("date_done_to")
        if df and dt and df > dt:
            self.add_error("date_done_to", "KYC date to must be on/after KYC date from.")
        dlf = data.get("date_last_kyc_from")
        dlt = data.get("date_last_kyc_to")
        if dlf and dlt and dlf > dlt:
            self.add_error("date_last_kyc_to", "Date of last KYC to must be on/after Date of last KYC from.")
        return data

    def is_compliance_view(self) -> bool:
        return bool(self.is_valid() and self.cleaned_data.get("view_mode") == self.VIEW_COMPLIANCE)
