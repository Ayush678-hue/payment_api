import uuid
from django.db import models
from django.utils import timezone
from datetime import timedelta


class Payment(models.Model):
    """Represents a payment transaction."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    description = models.TextField(blank=True, default="")
    payer_email = models.EmailField()
    metadata = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["payer_email"]),
        ]

    def __str__(self):
        return f"Payment {self.id} — {self.amount} {self.currency} [{self.status}]"


def default_expires_at():
    """Idempotency keys expire after 24 hours by default."""
    return timezone.now() + timedelta(hours=24)


class IdempotencyRecord(models.Model):
    """
    Stores the result of a previously-processed request so that retries with
    the same Idempotency-Key return the exact same response without
    re-executing side-effects.

    Lifecycle:
      1. Client sends POST with `Idempotency-Key` header.
      2. Middleware/view creates a record with status='processing' *inside a
         transaction with select_for_update* to act as a distributed lock.
      3. After the request is processed the record is updated to 'completed'
         with the response body and status code.
      4. Subsequent requests with the same key return the stored response.
      5. If the server crashed mid-processing the record stays 'processing';
         a configurable lock-timeout lets a later retry reclaim it.
    """

    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"

    idempotency_key = models.CharField(max_length=255, unique=True, db_index=True)
    request_method = models.CharField(max_length=10)
    request_path = models.CharField(max_length=512)
    request_body_hash = models.CharField(
        max_length=64,
        help_text="SHA-256 hash of the request body to detect mismatched retries.",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PROCESSING
    )
    response_data = models.JSONField(null=True, blank=True)
    status_code = models.IntegerField(null=True, blank=True)
    payment = models.ForeignKey(
        Payment, null=True, blank=True, on_delete=models.SET_NULL, related_name="idempotency_records"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(default=default_expires_at)
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["expires_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"Idempotency {self.idempotency_key} [{self.status}]"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_locked(self):
        """A processing record is considered locked for 60 seconds."""
        if self.status != self.Status.PROCESSING:
            return False
        if self.locked_at is None:
            return False
        return (timezone.now() - self.locked_at) < timedelta(seconds=60)
