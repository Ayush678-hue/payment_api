import hashlib
import json
import logging

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import IdempotencyRecord, Payment
from .serializers import (
    PaymentCreateSerializer,
    PaymentResponseSerializer,
)

logger = logging.getLogger(__name__)


def _hash_body(body: bytes) -> str:
    """SHA-256 hash of the raw request body for fingerprint comparison."""
    return hashlib.sha256(body).hexdigest()


def _simulate_payment_processing(validated_data: dict) -> tuple[Payment, bool]:
    """
    Simulate a payment gateway call.
    Replace this with your actual payment processor integration
    (Stripe, Razorpay, etc.).

    Returns (payment_instance, success_bool).
    """
    payment = Payment.objects.create(
        amount=validated_data["amount"],
        currency=validated_data["currency"],
        payer_email=validated_data["payer_email"],
        description=validated_data.get("description", ""),
        metadata=validated_data.get("metadata", {}),
        status=Payment.Status.COMPLETED,
    )
    return payment, True


class PaymentView(APIView):
    """
    POST /api/payments/process-payment/
    Idempotent payment endpoint.

    Requires an `Idempotency-Key` header (client-generated UUID).
    Retries with the same key return the original response without
    re-processing the payment.
    """

    def post(self, request):
        # ── 1. Extract & validate the idempotency key ────────────────────
        key = request.headers.get("Idempotency-Key")
        if not key:
            return Response(
                {
                    "error": "Idempotency-Key header is required.",
                    "detail": "Send a unique UUID in the Idempotency-Key header "
                    "to ensure exactly-once processing.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if len(key) > 255:
            return Response(
                {"error": "Idempotency-Key must be at most 255 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        body_hash = _hash_body(request.body)

        # ── 2. Atomically check for an existing record ───────────────────
        #    select_for_update prevents two concurrent requests with the
        #    same key from both passing the existence check.
        try:
            with transaction.atomic():
                existing = (
                    IdempotencyRecord.objects.select_for_update(nowait=False)
                    .filter(idempotency_key=key)
                    .first()
                )

                if existing:
                    return self._handle_existing_record(existing, body_hash)

                # ── 3. Validate the payment payload ──────────────────────
                serializer = PaymentCreateSerializer(data=request.data)
                if not serializer.is_valid():
                    return Response(
                        serializer.errors,
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # ── 4. Acquire the lock by creating a 'processing' record ─
                record = IdempotencyRecord.objects.create(
                    idempotency_key=key,
                    request_method=request.method,
                    request_path=request.path,
                    request_body_hash=body_hash,
                    status=IdempotencyRecord.Status.PROCESSING,
                    locked_at=timezone.now(),
                )

            # ── 5. Process the payment (outside the select_for_update
            #       transaction so the lock row is already visible) ────────
            try:
                payment, success = _simulate_payment_processing(
                    serializer.validated_data
                )
            except Exception as exc:
                logger.exception("Payment processing failed for key=%s", key)
                # Mark idempotency record as completed with an error
                # so retries don't re-attempt.
                error_response = {
                    "error": "Payment processing failed.",
                    "detail": str(exc),
                }
                record.response_data = error_response
                record.status_code = status.HTTP_502_BAD_GATEWAY
                record.status = IdempotencyRecord.Status.COMPLETED
                record.save(update_fields=["response_data", "status_code", "status", "updated_at"])
                return Response(error_response, status=status.HTTP_502_BAD_GATEWAY)

            # ── 6. Build and persist the response ────────────────────────
            if success:
                response_data = {
                    "message": "Payment processed successfully.",
                    "payment": PaymentResponseSerializer(payment).data,
                }
                resp_status = status.HTTP_201_CREATED
            else:
                response_data = {
                    "error": "Payment declined by processor.",
                    "payment": PaymentResponseSerializer(payment).data,
                }
                resp_status = status.HTTP_402_PAYMENT_REQUIRED

            record.response_data = response_data
            record.status_code = resp_status
            record.status = IdempotencyRecord.Status.COMPLETED
            record.payment = payment
            record.save(
                update_fields=[
                    "response_data",
                    "status_code",
                    "status",
                    "payment",
                    "updated_at",
                ]
            )

            return Response(response_data, status=resp_status)

        except Exception as exc:
            logger.exception("Unexpected error in PaymentView for key=%s", key)
            return Response(
                {"error": "Internal server error.", "detail": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ── Helpers ──────────────────────────────────────────────────────────

    def _handle_existing_record(
        self, record: IdempotencyRecord, body_hash: str
    ) -> Response:
        """Return the cached response or an appropriate error for an
        existing idempotency record."""

        # Expired keys can be retried as new requests.
        if record.is_expired:
            record.delete()
            # Return a 409 so the client knows to retry; this avoids
            # silently re-processing inside the same transaction.
            return Response(
                {
                    "error": "Idempotency key has expired. Please retry with the same key.",
                    "retry": True,
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Stale lock (server crashed mid-processing) — delete and let
        # the client retry.  Must be checked before body-hash comparison
        # because the original request that crashed may have had a
        # different serialised body.
        if record.status == IdempotencyRecord.Status.PROCESSING and not record.is_locked:
            record.delete()
            return Response(
                {
                    "error": "Previous processing attempt timed out. Please retry.",
                    "retry": True,
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Still processing (another thread holds the lock).
        if record.is_locked:
            return Response(
                {
                    "error": "A request with this Idempotency-Key is currently being processed.",
                    "detail": "Please retry after a short delay.",
                    "retry_after_seconds": 5,
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Mismatched body = client reused a key for a different request.
        if record.request_body_hash != body_hash:
            return Response(
                {
                    "error": "Idempotency key has already been used with a different request payload.",
                    "detail": "Each unique request must use a unique Idempotency-Key.",
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Happy path: return the stored response.
        return Response(record.response_data, status=record.status_code)


class PaymentDetailView(APIView):
    """
    GET /api/payments/<uuid:payment_id>/
    Retrieve a single payment by its UUID.
    """

    def get(self, request, payment_id):
        try:
            payment = Payment.objects.get(pk=payment_id)
        except Payment.DoesNotExist:
            return Response(
                {"error": "Payment not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(PaymentResponseSerializer(payment).data)


class PaymentListView(APIView):
    """
    GET /api/payments/
    List all payments, newest first.
    """

    def get(self, request):
        payments = Payment.objects.all()[:50]
        serializer = PaymentResponseSerializer(payments, many=True)
        return Response(serializer.data)
