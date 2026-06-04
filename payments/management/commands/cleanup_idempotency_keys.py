"""
Management command to clean up expired IdempotencyRecord rows.
Run periodically via cron or Django-Q / Celery beat:

    python manage.py cleanup_idempotency_keys
    python manage.py cleanup_idempotency_keys --older-than 48   # hours
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from payments.models import IdempotencyRecord


class Command(BaseCommand):
    help = "Delete expired idempotency records to keep the table lean."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than",
            type=int,
            default=24,
            help="Delete records whose expires_at is older than N hours ago (default: 24).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print how many records would be deleted without actually deleting.",
        )

    def handle(self, *args, **options):
        hours = options["older_than"]
        cutoff = timezone.now() - timedelta(hours=hours)
        qs = IdempotencyRecord.objects.filter(expires_at__lt=cutoff)
        count = qs.count()

        if options["dry_run"]:
            self.stdout.write(
                self.style.WARNING(f"[DRY RUN] Would delete {count} expired record(s).")
            )
            return

        deleted, _ = qs.delete()
        self.stdout.write(
            self.style.SUCCESS(f"Deleted {deleted} expired idempotency record(s).")
        )
