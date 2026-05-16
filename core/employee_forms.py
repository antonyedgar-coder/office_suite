from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

from masters.models import Client

from .models import Employee
from .permission_utils import manageable_permissions

User = get_user_model()


class EmployeeCreateForm(forms.ModelForm):
    """Official email becomes username; password set by admin. Client users must match Client Master email."""

    official_email = forms.EmailField(
        label="Email ID (login)",
        help_text="For Client users this must match the email stored in Client Master.",
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
        min_length=8,
        label="Initial password",
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
        label="Confirm password",
    )
    force_password_change = forms.BooleanField(
        required=False,
        initial=False,
        label="Require password change on first login",
        help_text="If checked, the user must choose a new password before using the rest of the app.",
    )
    is_active = forms.BooleanField(
        required=False,
        initial=True,
        label="Active (can sign in)",
        help_text="Uncheck to mark inactive — they cannot log in until reactivated.",
    )
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        required=False,
        label="Access groups",
        help_text="Permissions from these groups apply to this user.",
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "6"}),
    )
    user_permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),
        required=False,
        label="Direct permissions",
        help_text="Extra permissions for this user only (on top of groups).",
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "10"}),
    )

    class Meta:
        model = Employee
        fields = [
            "user_type",
            "full_name",
            "contact_no",
            "address",
            "date_of_joining",
            "contact_person",
            "aadhar_no",
            "branch_access",
        ]
        widgets = {
            "user_type": forms.Select(attrs={"class": "form-select", "id": "id_user_type"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user_permissions"].queryset = manageable_permissions()
        self.fields["full_name"].required = False
        self.fields["date_of_joining"].required = False
        self.fields["full_name"].label = "Name of employee"
        self.fields["full_name"].help_text = "Required when type is Employee."
        self.fields["branch_access"].widget.attrs.setdefault("class", "form-select")
        self.fields["branch_access"].help_text = (
            "All branches: full access. Trivandrum or Nagercoil: user sees only that branch "
            "in Client Master, MIS, directors, and DIR-3 KYC."
        )

        for name, field in self.fields.items():
            if name in (
                "user_type",
                "is_active",
                "force_password_change",
                "groups",
                "user_permissions",
                "password",
                "password_confirm",
            ):
                continue
            if isinstance(field.widget, forms.DateInput):
                field.widget.attrs.setdefault("class", "form-control")
                field.widget.input_type = "date"
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-check-input")
            else:
                field.widget.attrs.setdefault("class", "form-control")

        self.fields["is_active"].widget.attrs.setdefault("class", "form-check-input")
        self.fields["force_password_change"].widget.attrs.setdefault("class", "form-check-input")

    def clean_official_email(self):
        email = (self.cleaned_data.get("official_email") or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with this email already exists.")
        return email

    def clean(self):
        data = super().clean()
        ut = data.get("user_type")
        email = (data.get("official_email") or "").strip().lower()

        if ut == Employee.USER_TYPE_CLIENT:
            qs = Client.objects.filter(email__iexact=email)
            n = qs.count()
            if n == 0:
                self.add_error(
                    "official_email",
                    "No client in Client Master has this email address. Add or correct it in Client Master first.",
                )
            elif n > 1:
                self.add_error(
                    "official_email",
                    "Several clients share this email. Ensure only one Client Master record uses this email.",
                )
            else:
                c = qs.first()
                data["full_name"] = c.client_name
                data["contact_no"] = (c.mobile or "").strip()
                data["address"] = (c.address or "").strip()
                data["contact_person"] = (c.contact_person or "").strip()
                data["aadhar_no"] = ""
                dj = data.get("date_of_joining")
                if not dj:
                    data["date_of_joining"] = c.created_at.date() if c.created_at else None
                if not data["date_of_joining"]:
                    from datetime import date

                    data["date_of_joining"] = date.today()
                data["_linked_client_pk"] = c.pk
        else:
            if not (data.get("full_name") or "").strip():
                self.add_error("full_name", "Enter the employee name.")
            if not data.get("date_of_joining"):
                self.add_error("date_of_joining", "Date of joining is required for employees.")
            data.pop("_linked_client_pk", None)

        p1 = data.get("password") or ""
        p2 = data.get("password_confirm") or ""
        if p1 != p2:
            self.add_error("password_confirm", "Passwords do not match.")
        return data


class EmployeeEditForm(forms.ModelForm):
    is_active = forms.BooleanField(
        required=False,
        label="Active (can sign in)",
        help_text="Uncheck to mark inactive — they cannot log in until reactivated.",
    )
    force_password_change = forms.BooleanField(
        required=False,
        label="Require password change on next login",
        help_text="Forces the password-change screen after the next successful login.",
    )
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        required=False,
        label="Access groups",
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "6"}),
    )
    user_permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),
        required=False,
        label="Direct permissions",
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "10"}),
    )
    new_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
        label="New password (optional)",
        help_text="Leave blank to keep the current password.",
    )
    new_password_confirm = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}),
        label="Confirm new password",
    )

    class Meta:
        model = Employee
        fields = [
            "full_name",
            "contact_no",
            "address",
            "date_of_joining",
            "contact_person",
            "aadhar_no",
            "branch_access",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user_permissions"].queryset = manageable_permissions()
        user = getattr(self.instance, "user", None)
        if user:
            self.fields["is_active"].initial = user.is_active
            self.fields["force_password_change"].initial = user.force_password_change
            self.fields["groups"].initial = user.groups.all()
            self.fields["user_permissions"].initial = user.user_permissions.filter(
                pk__in=manageable_permissions().values_list("pk", flat=True)
            )

        self.fields["branch_access"].widget.attrs.setdefault("class", "form-select")

        if self.instance.pk and self.instance.user_type == Employee.USER_TYPE_CLIENT:
            self.fields["full_name"].label = "Client name (from Client Master)"
            for name in (
                "full_name",
                "contact_no",
                "address",
                "date_of_joining",
                "contact_person",
                "aadhar_no",
                "branch_access",
            ):
                if name in self.fields:
                    self.fields[name].disabled = True
        else:
            self.fields["full_name"].label = "Name of employee"

        for name, field in self.fields.items():
            if name in (
                "is_active",
                "force_password_change",
                "groups",
                "user_permissions",
                "new_password",
                "new_password_confirm",
            ):
                if name in ("is_active", "force_password_change"):
                    field.widget.attrs.setdefault("class", "form-check-input")
                continue
            if isinstance(field.widget, forms.DateInput):
                field.widget.attrs.setdefault("class", "form-control")
                field.widget.input_type = "date"
            else:
                field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        data = super().clean()
        n1 = (data.get("new_password") or "").strip()
        n2 = (data.get("new_password_confirm") or "").strip()
        if n1 or n2:
            if len(n1) < 8:
                self.add_error("new_password", "Password must be at least 8 characters.")
            if n1 != n2:
                self.add_error("new_password_confirm", "Passwords do not match.")
        return data


class FirstPasswordChangeForm(forms.Form):
    current_password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))
    new_password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))

    def clean(self):
        data = super().clean()
        n = data.get("new_password") or ""
        c = data.get("confirm_password") or ""
        if n != c:
            self.add_error("confirm_password", "Passwords do not match.")
        if len(n) < 8:
            self.add_error("new_password", "Password must be at least 8 characters.")
        return data
