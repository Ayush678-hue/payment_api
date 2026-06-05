from django.contrib import admin
from .models import Payment, IdempotencyRecord, APIKey


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


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "prefix", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "prefix")
    readonly_fields = ("prefix", "hashed_key", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not change:  # Only generate on creation
            import secrets
            import hashlib
            from django.contrib import messages
            from django.utils.safestring import mark_safe

            # Generate the key pair
            prefix = secrets.token_hex(4)  # 8 chars
            secret = secrets.token_urlsafe(32)  # Secure random string
            plaintext_key = f"pay_{prefix}.{secret}"

            obj.prefix = prefix
            obj.hashed_key = hashlib.sha256(plaintext_key.encode()).hexdigest()

            # Save the object
            super().save_model(request, obj, form, change)

            # Show the plaintext key to the user in a notice box
            messages.success(
                request,
                mark_safe(
                    f"<strong>API Key Created Successfully!</strong><br>"
                    f"Please copy this key now. <strong>You will not be able to see it again!</strong><br><br>"
                    f"<code style='background: #eef; padding: 6px 12px; border: 1px solid #aab; font-size: 1.2em; display: inline-block; font-family: monospace;'>{plaintext_key}</code>"
                )
            )
        else:
            super().save_model(request, obj, form, change)

