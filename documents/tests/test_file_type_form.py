from django.test import TestCase

from documents.file_types import extensions_from_file_type_choices
from documents.models import DocumentFolderTemplate, DocumentTypeTemplate
from documents.template_forms import DocumentTypeTemplateForm


class DocumentTypeTemplateFormTests(TestCase):
    def setUp(self):
        self.folder = DocumentFolderTemplate.objects.create(
            name="Test folder",
            slug="test-folder-form",
            sort_order=99,
        )

    def _form_data(self, **overrides):
        data = {
            "folder": str(self.folder.pk),
            "name": "MIS export",
            "allowed_file_types": ["csv", "xlsm", "xlsx"],
            "period_kind": "none",
            "name_template": "{document_type}-{client_name}",
            "sort_order": "0",
            "is_active": "on",
        }
        data.update(overrides)
        return data

    def test_save_csv_xlsm_xlsx(self):
        form = DocumentTypeTemplateForm(self._form_data())
        self.assertTrue(form.is_valid(), form.errors)
        obj = form.save()
        self.assertEqual(
            set(obj.allowed_extension_set()),
            {"csv", "xls", "xlsm", "xlsx"},
        )

    def test_extensions_from_choices(self):
        raw = extensions_from_file_type_choices(["csv", "xlsm", "xlsx"])
        self.assertEqual(set(raw.split(",")), {"csv", "xls", "xlsm", "xlsx"})

    def test_duplicate_name_blocked(self):
        DocumentTypeTemplate.objects.create(
            folder=self.folder,
            name="MIS export",
            slug="mis-export",
            allowed_extensions="pdf",
        )
        form = DocumentTypeTemplateForm(self._form_data())
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)
