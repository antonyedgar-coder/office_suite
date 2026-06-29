from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase

from documents.models import ClientDocument, ClientDocumentFolder, DocumentFolderTemplate, DocumentTypeTemplate
from masters.models import Client, ClientGroup

User = get_user_model()


class TemplateDeleteRulesTests(TestCase):
    def setUp(self):
        self.folder = DocumentFolderTemplate.objects.create(
            name="Test folder",
            slug="test-folder",
            sort_order=99,
        )
        self.file_type = DocumentTypeTemplate.objects.create(
            folder=self.folder,
            name="Test file",
            slug="test-file",
            allowed_extensions="pdf",
        )

    def test_folder_not_deletable_with_file_types(self):
        self.assertFalse(self.folder.is_deletable)

    def test_folder_deletable_without_file_types(self):
        self.file_type.delete()
        self.assertTrue(self.folder.is_deletable)

    def test_system_folder_not_deletable(self):
        supporting = DocumentFolderTemplate.objects.create(
            name="Supporting Documents",
            slug="supporting-documents",
            sort_order=1,
        )
        self.assertFalse(supporting.is_deletable)

    def test_file_type_not_deletable_with_documents(self):
        grp = ClientGroup.objects.create(name="TEST")
        client = Client.objects.create(
            client_name="Doc Client",
            client_type="Individual",
            branch="Trivandrum",
            client_group=grp,
            approval_status=Client.APPROVED,
            pan="ABCDE1234F",
        )
        client_folder = ClientDocumentFolder.objects.create(
            client=client,
            template=self.folder,
        )
        user = User.objects.create_user(email="u@example.com", password="pass12345")
        ClientDocument.objects.create(
            client=client,
            folder=client_folder,
            document_type=self.file_type,
            generated_filename="test.pdf",
            period_key="once",
            status=ClientDocument.STATUS_ACTIVE,
            content_hash="deadbeef",
            file=ContentFile(b"pdf", name="test.pdf"),
            uploaded_by=user,
        )
        self.assertFalse(self.file_type.is_deletable)

    def test_file_type_deletable_without_documents(self):
        self.assertTrue(self.file_type.is_deletable)
