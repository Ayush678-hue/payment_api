from django.contrib import admin
from .models import Payment, IdempotencyRecord


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "amount", "currency", "status", "payer_email", "created_at")
    list_filter = ("status", "currency", "created_at")
    search_fields = ("id", "payer_email", "description")
    readonly_fields = ("id", "created_at", "updated_at")
    ordering = ("-created_at",)


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    list_display = (
        "idempotency_key",
        "status",
        "status_code",
        "request_method",
        "request_path",
        "created_at",
        "expires_at",
    )
    list_filter = ("status", "request_method")
    search_fields = ("idempotency_key",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-created_at",)
