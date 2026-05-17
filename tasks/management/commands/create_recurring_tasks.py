from django.core.management.base import BaseCommand
from django.utils import timezone

from tasks.models import TaskRecurrenceEnrollment
from tasks.services import try_create_recurring_for_enrollment


class Command(BaseCommand):
    help = "Idempotently create recurring tasks due today for active enrollments."

    def handle(self, *args, **options):
        today = timezone.localdate()
        created = 0
        skipped = 0
        for enrollment in TaskRecurrenceEnrollment.objects.filter(is_active=True).select_related(
            "client", "task_master", "verifier"
        ).prefetch_related("assignees"):
            task = try_create_recurring_for_enrollment(enrollment, today)
            if task:
                created += 1
                self.stdout.write(f"Created task {task.pk} for {enrollment}")
            else:
                skipped += 1
        self.stdout.write(self.style.SUCCESS(f"Done. Created={created}, skipped={skipped}"))
