from django.core.management.base import BaseCommand

from documents.services import provision_client_document_folders, provision_standard_client_folders
from masters.models import Client


class Command(BaseCommand):
    help = "Create document folders for clients that are missing them."

    def add_arguments(self, parser):
        parser.add_argument(
            "--standard-only",
            action="store_true",
            help="Only provision Supporting Documents and KYC Documents folders.",
        )

    def handle(self, *args, **options):
        total = 0
        clients = Client.objects.all().order_by("client_id")
        for client in clients.iterator():
            if options["standard_only"]:
                total += provision_standard_client_folders(client)
            else:
                total += provision_standard_client_folders(client)
                if client.approval_status == Client.APPROVED:
                    total += provision_client_document_folders(client)
        self.stdout.write(self.style.SUCCESS(f"Provisioned {total} new folder(s)."))
