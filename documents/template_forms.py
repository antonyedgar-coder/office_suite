from django import forms
from django.utils.text import slugify

from .models import DocumentFolderTemplate, DocumentTypeTemplate
class DocumentFolderTemplateForm(forms.ModelForm):
    class Meta:
        model = DocumentFolderTemplate
        fields = ["name", "sort_order", "is_active", "client_types"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Financials"}),
            "sort_order": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "client_types": forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from masters.models import ClientType

        self.fields["client_types"].queryset = ClientType.objects.filter(is_active=True).order_by(
            "sort_order", "name"
        )
        self.fields["client_types"].required = False
        self.fields["client_types"].help_text = (
            "Leave all unchecked to allow every client type. Check types that should see this folder."
        )

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.slug:
            obj.slug = slugify(obj.name)[:80]
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class DocumentTypeTemplateForm(forms.ModelForm):
    class Meta:
        model = DocumentTypeTemplate
        fields = [
            "folder",
            "name",
            "allowed_extensions",
            "period_kind",
            "name_template",
            "sort_order",
            "is_active",
        ]
        widgets = {
            "folder": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. GSTR-3B filed"}
            ),
            "allowed_extensions": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "pdf or pdf,xlsx"}
            ),
            "period_kind": forms.Select(attrs={"class": "form-select"}),
            "name_template": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "{document_type}-{client_name}_{month_label}",
                }
            ),
            "sort_order": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, folder_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        folder_qs = DocumentFolderTemplate.objects.order_by("sort_order", "name")
        if not getattr(self.instance, "pk", None):
            folder_qs = folder_qs.filter(is_active=True)
        self.fields["folder"].queryset = folder_qs
        if folder_id:
            self.fields["folder"].initial = folder_id
        elif getattr(self.instance, "pk", None):
            self.fields["folder"].initial = self.instance.folder_id

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.slug:
            base = slugify(obj.name)[:80]
            obj.slug = base
        if commit:
            obj.save()
        return obj
