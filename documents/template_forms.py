from django import forms
from django.utils.text import slugify

from .file_types import (
    DOCUMENT_FILE_TYPE_CHOICES,
    extensions_from_file_type_choices,
    file_type_choices_from_extensions,
)
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
    allowed_file_types = forms.MultipleChoiceField(
        choices=DOCUMENT_FILE_TYPE_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        label="Allowed file types",
        help_text="Tick every format staff may upload for this file type.",
    )

    class Meta:
        model = DocumentTypeTemplate
        fields = [
            "folder",
            "name",
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
        if self.instance.pk:
            self.fields["allowed_file_types"].initial = file_type_choices_from_extensions(
                self.instance.allowed_extensions
            )
        elif not self.is_bound:
            self.fields["allowed_file_types"].initial = ["pdf"]

    def clean_allowed_file_types(self):
        selected = self.cleaned_data.get("allowed_file_types") or []
        if not selected:
            raise forms.ValidationError("Select at least one allowed file type.")
        return selected

    def clean(self):
        cleaned = super().clean()
        folder = cleaned.get("folder")
        name = (cleaned.get("name") or "").strip()
        if folder and name:
            base_slug = slugify(name)[:80] or "file"
            qs = DocumentTypeTemplate.objects.filter(folder=folder, slug=base_slug)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error(
                    "name",
                    "A file type with this name already exists in this folder. Use a different name.",
                )
        return cleaned

    def _unique_slug(self, folder: DocumentFolderTemplate, base_slug: str) -> str:
        slug = (base_slug or "file")[:80]
        n = 2
        while True:
            qs = DocumentTypeTemplate.objects.filter(folder=folder, slug=slug)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if not qs.exists():
                return slug
            suffix = f"-{n}"
            slug = f"{base_slug[: 80 - len(suffix)]}{suffix}"
            n += 1

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.allowed_extensions = extensions_from_file_type_choices(
            self.cleaned_data.get("allowed_file_types") or []
        )
        if not obj.slug:
            obj.slug = self._unique_slug(obj.folder, slugify(obj.name)[:80] or "file")
        if commit:
            obj.save()
        return obj
