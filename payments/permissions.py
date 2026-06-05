import hashlib
from rest_framework import permissions
from .models import APIKey


class HasAPIKey(permissions.BasePermission):
    """
    Custom permission class that checks for a valid, active API Key.
    Supports either:
      - X-API-Key: pay_abc123.xyz...
      - Authorization: Api-Key pay_abc123.xyz...
    """

    message = "Invalid or missing API key."

    def has_permission(self, request, view):
        # 1. Look for key in X-API-Key header
        api_key = request.headers.get("X-API-Key")

        # 2. If not found, look in Authorization header
        if not api_key:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Api-Key "):
                api_key = auth_header.split(" ", 1)[1]

        if not api_key:
            return False

        # Hash the incoming key to compare it with the stored hash
        hashed_key = hashlib.sha256(api_key.encode()).hexdigest()

        # Query the database
        return APIKey.objects.filter(hashed_key=hashed_key, is_active=True).exists()
