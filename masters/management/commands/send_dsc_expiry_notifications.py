from django.core.management.base import BaseCommand

from masters.dsc_expiry_notifications import send_dsc_expiry_notifications


class Command(BaseCommand):
    help = (
        "Send DSC expiry in-app notifications (30 days before expiry, every 7 days) "
        "for the latest DSC per client when expiry notification is enabled."
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
        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}: {stats['notifications_created']} notification(s) "
                f"across {stats['sent_batches']} client DSC(s) "
                f"({stats['clients_checked']} clients with DSC checked)."
            )
        )
