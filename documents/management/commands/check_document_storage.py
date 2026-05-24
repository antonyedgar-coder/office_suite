"""Verify document storage (local or DigitalOcean Spaces) can write and read."""

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Upload a small test file to document storage and delete it."

    def handle(self, *args, **options):
        storage_kind = getattr(settings, "DOCUMENT_STORAGE", "local")
        self.stdout.write(f"DOCUMENT_STORAGE={storage_kind}")
        self.stdout.write(f"Backend={default_storage.__class__.__name__}")

        key = "_healthcheck/upload-test.txt"
        body = b"ca-office-suite storage check\n"
        try:
            if default_storage.exists(key):
                default_storage.delete(key)
            default_storage.save(key, ContentFile(body))
            if not default_storage.exists(key):
                self.stderr.write(self.style.ERROR("File not found after save."))
                return
            with default_storage.open(key, "rb") as handle:
                read_back = handle.read()
            default_storage.delete(key)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Storage check FAILED: {exc}"))
            if storage_kind == "spaces":
                self.stderr.write(
                    "Verify DO_SPACES_KEY, DO_SPACES_SECRET, DO_SPACES_BUCKET, "
                    "DO_SPACES_ENDPOINT, DO_SPACES_REGION on the app."
                )
            raise SystemExit(1) from exc

        if read_back != body:
            self.stderr.write(self.style.ERROR("Read back content did not match."))
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS("Storage check OK (write + read + delete)."))
