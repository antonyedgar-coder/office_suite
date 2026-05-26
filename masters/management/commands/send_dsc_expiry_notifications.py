from django.conf import settings
from django.core.management.base import BaseCommand

from masters.dsc_expiry_notifications import (
    dsc_expiry_days_before,
    send_dsc_expiry_notifications,
)


class Command(BaseCommand):
    help = (
        "Send DSC expiry in-app notifications once per day for the latest DSC per client "
        "(expiry notification = Yes, within the pre-expiry window). "
        "Recipients: users with DSC view permission in User management (branch-scoped). "
        "Schedule on the server at DSC_EXPIRY_NOTIFY_RUN_TIME (see settings / .env)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many notifications would be sent without creating them.",
        )

    def handle(self, *args, **options):
        stats = send_dsc_expiry_notifications(dry_run=options["dry_run"])
        prefix = "Would send" if options["dry_run"] else "Sent"
        run_time = getattr(settings, "DSC_EXPIRY_NOTIFY_RUN_TIME", "08:00")
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}: {stats['notifications_created']} notification(s) "
                f"across {stats['sent_batches']} client DSC(s) "
                f"({stats['clients_checked']} clients with DSC checked). "
                f"Window: {dsc_expiry_days_before()} days before expiry; "
                f"intended daily run time: {run_time} (server timezone)."
            )
        )
