import secrets
import hashlib
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from payments.models import APIKey
from ai_intelligence.models import PaymentEvent, RiskScore


class AIEndpointsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.prefix = secrets.token_hex(4)
        self.secret = secrets.token_urlsafe(32)
        self.raw_key = f"pay_{self.prefix}.{self.secret}"
        hashed_key = hashlib.sha256(self.raw_key.encode()).hexdigest()

        self.api_key_obj = APIKey.objects.create(
            name="Test AI Client",
            prefix=self.prefix,
            hashed_key=hashed_key,
            is_active=True,
        )
        self.headers = {"HTTP_X_API_KEY": self.raw_key}

        self.event = PaymentEvent.objects.create(
            event_type="payment_created",
            payment_id="pay_uuid_123",
            idempotency_key="idemp_123",
            request_fingerprint="hash_123",
            api_key_prefix=self.prefix,
            status_code=201,
            latency_ms=25,
        )
        self.risk = RiskScore.objects.create(
            payment_id="pay_uuid_123",
            idempotency_key="idemp_123",
            score=0.15,
            risk_band="low",
            factors={"base": 0.15},
        )

    def test_get_events_list_unauthorized(self):
        resp = self.client.get(reverse("ai-event-list"))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_events_list_authorized(self):
        resp = self.client.get(reverse("ai-event-list"), **self.headers)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.json()), 1)

    def test_get_event_detail_authorized(self):
        resp = self.client.get(reverse("ai-event-detail", kwargs={"pk": self.event.id}), **self.headers)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["payment_id"], "pay_uuid_123")

    def test_get_risk_scores_authorized(self):
        resp = self.client.get(reverse("ai-risk-list"), **self.headers)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.json()), 1)

    def test_nl2sql_query_endpoint(self):
        payload = {"question": "How many events?", "auto_execute": True}
        resp = self.client.post(reverse("ai-nl2sql-query"), data=payload, format="json", **self.headers)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("rows", resp.json())

    def test_draft_incident_endpoint(self):
        payload = {"title": "API Disruption Incident", "time_window_minutes": 30}
        resp = self.client.post(reverse("ai-incident-draft"), data=payload, format="json", **self.headers)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.json()["status"], "draft")
        self.assertEqual(resp.json()["title"], "API Disruption Incident")

    def test_landing_page_html(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("not by promise.", resp.content.decode('utf-8'))
        self.assertIn("Fire duplicate request", resp.content.decode('utf-8'))

    def test_api_root_json(self):
        resp = self.client.get("/api/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["status"], "Online & Active")

