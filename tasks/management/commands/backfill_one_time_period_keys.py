"""Renumber one-time task period keys per client and calendar month."""

from django.core.management.base import BaseCommand

from masters.models import Client
from tasks.one_time_period import backfill_one_time_period_keys_for_client


class Command(BaseCommand):
    help = (
        "Renumber existing one-time tasks per client and due-date month "
        "(April 2026, April 2026 2, …). Safe to run more than once."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--client-id",
            help="Only this Client Master ID (e.g. M00018). Default: all clients.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many rows would change without saving.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        client_id = (options.get("client_id") or "").strip().upper()
        qs = Client.objects.order_by("client_id")
        if client_id:
            qs = qs.filter(client_id=client_id)
        if not qs.exists():
            self.stderr.write(self.style.ERROR("No matching clients."))
            return

        total = 0
        for client in qs.iterator():
            n = backfill_one_time_period_keys_for_client(client, dry_run=dry_run)
            if n:
                action = "Would update" if dry_run else "Updated"
                self.stdout.write(f"{action} {n} task(s) for {client.client_id} — {client.client_name}")
            total += n

        label = "Would update" if dry_run else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{label} {total} one-time task(s) in total."))
