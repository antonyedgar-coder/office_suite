"""Wipe local test data before cloud deploy.

Examples:
  python manage.py reset_local_data --all
  python manage.py reset_local_data --all --keep-email you@firm.com
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.reset_data import count_local_data, wipe_all_local_data, wipe_local_data, WipeOptions

User = get_user_model()


class Command(BaseCommand):
    help = "Delete local test data (clients, tasks, MIS, users, etc.) in a safe order."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Delete everything except the kept login user(s).",
        )
        parser.add_argument(
            "--keep-email",
            action="append",
            default=[],
            help="Email(s) to keep (repeatable). Default: all superusers when using --all.",
        )
        parser.add_argument(
            "--no-input",
            action="store_true",
            help="Skip confirmation prompt.",
        )

    def handle(self, *args, **options):
        if not options["all"]:
            raise CommandError("Use --all to wipe local data, or use the superuser UI: Admin tools → Reset test data.")

        keep_ids = self._resolve_keep_ids(options["keep_email"])
        counts = count_local_data()

        self.stdout.write("Current row counts:")
        for key in sorted(counts):
            self.stdout.write(f"  {key}: {counts[key]}")

        if not options["no_input"]:
            self.stdout.write(
                self.style.WARNING(
                    "\nThis will DELETE the data above (except kept user logins). "
                    "Type 'yes' to continue:"
                )
            )
            if input().strip().lower() != "yes":
                self.stdout.write("Aborted.")
                return

        deleted = wipe_all_local_data(keep_user_ids=keep_ids)
        self.stdout.write(self.style.SUCCESS("\nDeleted:"))
        for key in sorted(deleted):
            self.stdout.write(f"  {key}: {deleted[key]}")

    def _resolve_keep_ids(self, keep_emails: list[str]) -> set[int]:
        if keep_emails:
            ids = set(
                User.objects.filter(email__in=[e.strip().lower() for e in keep_emails if e.strip()]).values_list(
                    "pk", flat=True
                )
            )
            if not ids:
                raise CommandError("No users matched --keep-email.")
            return ids
        return set(User.objects.filter(is_superuser=True).values_list("pk", flat=True))
