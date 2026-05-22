from django.core.management.base import BaseCommand

from documents.services import provision_client_document_folders
from masters.models import Client


class Command(BaseCommand):
    help = "Create document folders for approved clients that are missing them."

    def handle(self, *args, **options):
        total = 0
        for client in Client.approved_objects().iterator():
            total += provision_client_document_folders(client)
        self.stdout.write(self.style.SUCCESS(f"Provisioned {total} new folder(s)."))
