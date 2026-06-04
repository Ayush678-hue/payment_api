import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from payments.models import IdempotencyRecord, Payment


class PaymentIdempotencyTests(TestCase):
    """Test suite for the idempotent payment API."""

    def setUp(self):
        self.client = APIClient()
        self.url = "/api/payments/process-payment/"
        self.valid_payload = {
            "amount": "100.00",
            "currency": "USD",
            "payer_email": "test@example.com",
            "description": "Test payment",
        }

    def _make_key(self):
        return str(uuid.uuid4())

    # ── Basic idempotency ────────────────────────────────────────────────

    def test_first_request_creates_payment(self):
        """A fresh idempotency key should create a payment and return 201."""
        key = self._make_key()
        resp = self.client.post(
            self.url,
            data=self.valid_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIn("payment", resp.data)
        self.assertEqual(resp.data["payment"]["status"], "completed")
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_retry_returns_same_response(self):
        """Retrying with the same key and body returns the cached response
        without creating a second payment."""
        key = self._make_key()
        resp1 = self.client.post(
            self.url,
            data=self.valid_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        resp2 = self.client.post(
            self.url,
            data=self.valid_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(resp1.status_code, resp2.status_code)
        self.assertEqual(resp1.data, resp2.data)
        # Only one payment should exist.
        self.assertEqual(Payment.objects.count(), 1)

    def test_different_keys_create_different_payments(self):
        """Different idempotency keys should create separate payments."""
        for _ in range(3):
            self.client.post(
                self.url,
                data=self.valid_payload,
                format="json",
                HTTP_IDEMPOTENCY_KEY=self._make_key(),
            )
        self.assertEqual(Payment.objects.count(), 3)

    # ── Validation errors ────────────────────────────────────────────────

    def test_missing_idempotency_key_returns_400(self):
        resp = self.client.post(self.url, data=self.valid_payload, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.data)

    def test_invalid_amount_returns_400(self):
        payload = {**self.valid_payload, "amount": "-5.00"}
        resp = self.client.post(
            self.url,
            data=payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=self._make_key(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_unsupported_currency_returns_400(self):
        payload = {**self.valid_payload, "currency": "XYZ"}
        resp = self.client.post(
            self.url,
            data=payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=self._make_key(),
        )
        self.assertEqual(resp.status_code, 400)

    def test_missing_payer_email_returns_400(self):
        payload = {**self.valid_payload}
        del payload["payer_email"]
        resp = self.client.post(
            self.url,
            data=payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=self._make_key(),
        )
        self.assertEqual(resp.status_code, 400)

    # ── Body mismatch detection ──────────────────────────────────────────

    def test_reused_key_with_different_body_returns_422(self):
        """Reusing a key with a different payload must be rejected."""
        key = self._make_key()
        self.client.post(
            self.url,
            data=self.valid_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        different_payload = {**self.valid_payload, "amount": "999.99"}
        resp = self.client.post(
            self.url,
            data=different_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(resp.status_code, 422)

    # ── Expired key handling ─────────────────────────────────────────────

    def test_expired_key_returns_409_with_retry(self):
        """An expired idempotency record should be deleted and a 409
        returned so the client retries."""
        key = self._make_key()
        # First create a completed record, then backdate its expiry.
        self.client.post(
            self.url,
            data=self.valid_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        IdempotencyRecord.objects.filter(idempotency_key=key).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )
        resp = self.client.post(
            self.url,
            data=self.valid_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(resp.data.get("retry"))

    # ── Stale lock recovery ──────────────────────────────────────────────

    def test_stale_processing_record_returns_409_with_retry(self):
        """A 'processing' record whose lock has expired should be cleaned
        up and a retry suggested."""
        import hashlib, json

        key = self._make_key()
        # Compute the hash that the view will compute for our payload.
        body_bytes = json.dumps(self.valid_payload).encode("utf-8")
        body_hash = hashlib.sha256(body_bytes).hexdigest()

        IdempotencyRecord.objects.create(
            idempotency_key=key,
            request_method="POST",
            request_path=self.url,
            request_body_hash=body_hash,
            status=IdempotencyRecord.Status.PROCESSING,
            locked_at=timezone.now() - timedelta(seconds=120),  # well past 60s
        )
        resp = self.client.post(
            self.url,
            data=self.valid_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(resp.data.get("retry"))

    # ── Detail & list views ──────────────────────────────────────────────

    def test_payment_detail_view(self):
        key = self._make_key()
        resp = self.client.post(
            self.url,
            data=self.valid_payload,
            format="json",
            HTTP_IDEMPOTENCY_KEY=key,
        )
        payment_id = resp.data["payment"]["id"]
        detail_resp = self.client.get(f"/api/payments/{payment_id}/")
        self.assertEqual(detail_resp.status_code, 200)
        self.assertEqual(detail_resp.data["id"], payment_id)

    def test_payment_detail_404(self):
        fake_id = uuid.uuid4()
        resp = self.client.get(f"/api/payments/{fake_id}/")
        self.assertEqual(resp.status_code, 404)

    def test_payment_list_view(self):
        for _ in range(3):
            self.client.post(
                self.url,
                data=self.valid_payload,
                format="json",
                HTTP_IDEMPOTENCY_KEY=self._make_key(),
            )
        resp = self.client.get("/api/payments/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 3)


class IdempotencyRecordModelTests(TestCase):
    """Unit tests for the IdempotencyRecord model properties."""

    def test_is_expired_true(self):
        record = IdempotencyRecord(
            expires_at=timezone.now() - timedelta(hours=1)
        )
        self.assertTrue(record.is_expired)

    def test_is_expired_false(self):
        record = IdempotencyRecord(
            expires_at=timezone.now() + timedelta(hours=1)
        )
        self.assertFalse(record.is_expired)

    def test_is_locked_true(self):
        record = IdempotencyRecord(
            status=IdempotencyRecord.Status.PROCESSING,
            locked_at=timezone.now() - timedelta(seconds=10),
        )
        self.assertTrue(record.is_locked)

    def test_is_locked_false_when_completed(self):
        record = IdempotencyRecord(
            status=IdempotencyRecord.Status.COMPLETED,
            locked_at=timezone.now(),
        )
        self.assertFalse(record.is_locked)

    def test_is_locked_false_when_stale(self):
        record = IdempotencyRecord(
            status=IdempotencyRecord.Status.PROCESSING,
            locked_at=timezone.now() - timedelta(seconds=120),
        )
        self.assertFalse(record.is_locked)
