from django import forms

from .models import ClientDocumentFolder, DocumentTypeTemplate
from .periods import HALF_YEAR_CHOICES, QUARTER_CHOICES, fy_choices, month_value_choices
from .services import default_document_type_for_folder, parse_upload_period


class ClientDocumentUploadForm(forms.Form):
    folder = forms.ModelChoiceField(
        queryset=ClientDocumentFolder.objects.none(),
        widget=forms.Select(attrs={"class": "form-select", "id": "id_doc_folder"}),
        label="Folder",
    )
    document_type = forms.ModelChoiceField(
        queryset=DocumentTypeTemplate.objects.none(),
        widget=forms.Select(attrs={"class": "form-select", "id": "id_doc_type"}),
        label="File",
    )
    period_month = forms.ChoiceField(
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": "form-select", "id": "id_doc_period_month"}),
        label="Month",
    )
    period_fy = forms.ChoiceField(
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": "form-select", "id": "id_doc_period_fy"}),
        label="Financial year",
    )
    period_quarter = forms.ChoiceField(
        required=False,
        choices=[("", "— Quarter —")] + list(QUARTER_CHOICES),
        widget=forms.Select(attrs={"class": "form-select", "id": "id_doc_period_quarter"}),
        label="Quarter",
    )
    period_half = forms.ChoiceField(
        required=False,
        choices=[("", "— Half-year —")] + list(HALF_YEAR_CHOICES),
        widget=forms.Select(attrs={"class": "form-select", "id": "id_doc_period_half"}),
        label="Half-year",
    )
    file = forms.FileField(
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "id": "id_doc_file", "accept": ""}
        ),
        label="File",
    )
    custom_display_name = forms.CharField(
        required=False,
        max_length=120,
        widget=forms.TextInput(
            attrs={"class": "form-control", "id": "id_doc_custom_name", "maxlength": "120"}
        ),
        label="File name",
    )

    def __init__(self, *args, client, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = client
        self.fields["folder"].queryset = (
            ClientDocumentFolder.objects.filter(client=client)
            .select_related("template")
            .order_by("template__sort_order", "template__name")
        )
        self.fields["folder"].empty_label = "— Select folder —"
        self.fields["document_type"].empty_label = "— Select file —"
        self.fields["document_type"].queryset = DocumentTypeTemplate.objects.filter(
            is_active=True,
            folder__is_active=True,
        )
        self.fields["document_type"].required = False
        month_choices = [("", "— Select month —")] + month_value_choices()
        fy_choices_list = [("", "— Select FY —")] + fy_choices()
        self.fields["period_month"].choices = month_choices
        self.fields["period_fy"].choices = fy_choices_list

    def clean_folder(self):
        folder = self.cleaned_data.get("folder")
        if folder and folder.client_id != self.client.pk:
            self.add_error("folder", "Invalid folder for this client.")
        return folder

    def clean(self):
        data = super().clean()
        folder = data.get("folder")
        doc_type = data.get("document_type")
        if folder:
            default_type = default_document_type_for_folder(folder)
            if default_type:
                data["document_type"] = default_type
                doc_type = default_type
        if folder and doc_type and doc_type.folder_id != folder.template_id:
            self.add_error("document_type", "This file type does not belong to the selected folder.")
        elif folder and not doc_type and not default_document_type_for_folder(folder):
            self.add_error("document_type", "Select a file type.")
        if folder and folder.template.allow_custom_filename:
            name = (data.get("custom_display_name") or "").strip()
            if not name:
                self.add_error("custom_display_name", "Enter a name for this file.")
            else:
                data["custom_display_name"] = name
        if doc_type:
            try:
                pk, pl = parse_upload_period(doc_type, data)
                data["period_key"] = pk
                data["period_label"] = pl
            except Exception as exc:
                from django.core.exceptions import ValidationError as DJValidationError

                if isinstance(exc, DJValidationError):
                    self.add_error(None, exc)
                else:
                    raise
        return data


class ClientDocumentReplaceForm(forms.Form):
    file = forms.FileField(
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "id": "id_doc_replace_file", "accept": ""}
        ),
        label="New file",
    )
