from django import forms
from django.contrib.auth.models import Group, Permission

from .permission_utils import manageable_permissions


class GroupAccessForm(forms.ModelForm):
    assigned_permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),
        required=False,
        label="Permissions",
        help_text="Users in this group receive all selected permissions (in addition to any permissions assigned directly to the user).",
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "16"}),
    )

    class Meta:
        model = Group
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        perm_qs = manageable_permissions()
        self.fields["assigned_permissions"].queryset = perm_qs
        if self.instance.pk:
            allowed_pks = perm_qs.values_list("pk", flat=True)
            self.fields["assigned_permissions"].initial = self.instance.permissions.filter(pk__in=allowed_pks)

    def save(self, commit=True):
        group = super().save(commit=commit)
        if commit:
            group.permissions.set(self.cleaned_data["assigned_permissions"])
        return group
