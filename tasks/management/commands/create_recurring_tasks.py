from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tasks.services import run_create_recurring_tasks


class Command(BaseCommand):
    help = (
        "Idempotently create recurring tasks whose scheduled create date is today "
        "(or --date). Run daily (GitHub Actions or a platform job)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            dest="run_date",
            default="",
            help="YYYY-MM-DD in Asia/Kolkata. Default: today.",
        )

    def handle(self, *args, **options):
        raw = (options.get("run_date") or "").strip()
        if raw:
            try:
                today = datetime.strptime(raw, "%Y-%m-%d").date()
            except ValueError as exc:
                raise CommandError("Use --date YYYY-MM-DD.") from exc
        else:
            today = timezone.localdate()

        self.stdout.write(f"Recurring task run for {today.isoformat()}")
        result = run_create_recurring_tasks(today)
        for line in result.get("error_details") or []:
            self.stderr.write(self.style.ERROR(line))
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Created={result['created']}, skipped={result['skipped']}, "
                f"errors={result['errors']}"
            )
        )
