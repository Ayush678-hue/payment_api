import hashlib
from django.apps import AppConfig
from django.db.models.signals import post_migrate


def seed_default_credentials(sender, **kwargs):
    from django.contrib.auth import get_user_model
    from .models import APIKey

    User = get_user_model()
    # Auto-seed superuser if it doesn't exist
    if not User.objects.filter(username="Ayush").exists():
        User.objects.create_superuser("Ayush", "ayush@example.com", "Tl02xd1@3140")

    # Auto-seed submitted API key if it doesn't exist
    default_key = "pay_2b4ce484.F_6jW5rNjpa9DDj-JH0NtYNMMB2WIJn07cLwE4uEdu4"
    hashed = hashlib.sha256(default_key.encode()).hexdigest()
    if not APIKey.objects.filter(hashed_key=hashed).exists():
        APIKey.objects.create(
            name="Submitted Demo Key",
            prefix="pay_2b4c",
            hashed_key=hashed,
            is_active=True
        )


class PaymentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'payments'

    def ready(self):
        post_migrate.connect(seed_default_credentials, sender=self)
