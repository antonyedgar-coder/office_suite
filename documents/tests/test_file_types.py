from django.test import SimpleTestCase

from documents.file_types import (
    extensions_from_file_type_choices,
    file_type_choices_from_extensions,
    format_extension_labels,
)


class DocumentFileTypesTests(SimpleTestCase):
    def test_extensions_from_multiple_choices(self):
        raw = extensions_from_file_type_choices(["pdf", "word", "xlsx", "zip"])
        self.assertEqual(set(raw.split(",")), {"pdf", "doc", "docx", "xlsx", "xls", "zip"})

    def test_choices_from_stored_extensions(self):
        keys = file_type_choices_from_extensions("pdf,docx,xlsm,zip,rar")
        self.assertIn("pdf", keys)
        self.assertIn("word", keys)
        self.assertIn("xlsm", keys)
        self.assertIn("zip", keys)
        self.assertIn("rar", keys)

    def test_format_extension_labels(self):
        label = format_extension_labels({"pdf", "docx", "xlsm", "csv"})
        self.assertIn("PDF", label)
        self.assertIn("Word", label)
        self.assertIn("XLSM", label)
        self.assertIn("CSV", label)
