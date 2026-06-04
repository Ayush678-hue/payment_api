from rest_framework import serializers
from .models import Payment, IdempotencyRecord


class PaymentCreateSerializer(serializers.Serializer):
    """Validates incoming payment requests."""

    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
    currency = serializers.CharField(max_length=3, default="USD")
    payer_email = serializers.EmailField()
    description = serializers.CharField(required=False, allow_blank=True, default="")
    metadata = serializers.JSONField(required=False, default=dict)

    def validate_currency(self, value):
        allowed = {"USD", "EUR", "GBP", "INR", "JPY", "CAD", "AUD"}
        value = value.upper()
        if value not in allowed:
            raise serializers.ValidationError(
                f"Unsupported currency '{value}'. Allowed: {', '.join(sorted(allowed))}"
            )
        return value


class PaymentResponseSerializer(serializers.ModelSerializer):
    """Read-only serializer for payment responses."""

    class Meta:
        model = Payment
        fields = [
            "id",
            "amount",
            "currency",
            "status",
            "description",
            "payer_email",
            "metadata",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class IdempotencyRecordSerializer(serializers.ModelSerializer):
    """Read-only serializer for idempotency record inspection."""

    class Meta:
        model = IdempotencyRecord
        fields = [
            "idempotency_key",
            "request_method",
            "request_path",
            "status",
            "status_code",
            "payment",
            "created_at",
            "expires_at",
        ]
        read_only_fields = fields
