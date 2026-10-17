"""Create Sundry Debtor ledgers for approved Client Master records.

Examples:
  python manage.py sync_client_ledgers --dry-run
  python manage.py sync_client_ledgers
"""

from django.core.management.base import BaseCommand, CommandError

from core.feature_flags import accounts_module_enabled


class Command(BaseCommand):
    help = "One-time: create Account ledgers under Sundry Debtors for approved clients."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count what would be created without writing ledgers.",
        )

    def handle(self, *args, **options):
        if not accounts_module_enabled():
            raise CommandError("ENABLE_ACCOUNTS_MODULE must be on.")
        from accounts.services import backfill_approved_client_ledgers

        result = backfill_approved_client_ledgers(dry_run=options["dry_run"])
        prefix = "Would create" if result["dry_run"] else "Created"
        self.stdout.write(
            f"{prefix} {result['created']} ledger(s); "
            f"already linked {result['updated']}; "
            f"skipped unapproved {result['skipped_unapproved']}."
        )
        for row in result["errors"]:
            self.stdout.write(self.style.WARNING(row))
        if result["errors"]:
            raise CommandError(f"{len(result['errors'])} client(s) failed.")
