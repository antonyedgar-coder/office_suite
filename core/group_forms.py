from django import forms
from django.contrib.auth.models import Group, Permission

from .permission_utils import manageable_permissions
from .widgets import DualListSelectMultiple


class GroupAccessForm(forms.ModelForm):
    assigned_permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),
        required=False,
        label="Permissions",
        help_text="Move activities into Allowed so everyone in this group can do them. Users can also have extra permissions assigned directly.",
        widget=DualListSelectMultiple(assigned_label="Allowed"),
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
