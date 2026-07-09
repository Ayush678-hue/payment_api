# 🛡️ Idempotent Payment API Backend

A production-grade, fault-tolerant financial payment API built with **Python 3** and **Django REST Framework (DRF)**. Designed to guarantee **exactly-once processing**, prevent double-charging under high-concurrency multi-threaded load, and provide **zero-downtime self-healing failure recovery**.

---

## 🌐 Live Demo & Endpoints

| Resource | URL / Endpoint |
| :--- | :--- |
| **🟢 24/7 Live Cloud Demo** | [`https://payment-api-3fi4.onrender.com`](https://payment-api-3fi4.onrender.com) *(Hosted 24/7 on Render Cloud — Never goes offline!)* |
| **Local Tunnel Demo** | [`https://rude-breads-smell.loca.lt`](https://rude-breads-smell.loca.lt) *(Active only during active local dev sessions)* |
| **Admin Dashboard** | [`https://payment-api-3fi4.onrender.com/admin/`](https://payment-api-3fi4.onrender.com/admin/) *(Login: `Ayush` / `Tl02xd1@3140`)* |
| **List Payments** | `GET https://payment-api-3fi4.onrender.com/api/payments/` *(Requires `X-API-Key` header)* |
| **Process Payment** | `POST https://payment-api-3fi4.onrender.com/api/payments/process-payment/` *(Requires `Idempotency-Key` & `X-API-Key`)* |

---

## ⚡ Core Engineering & Architecture Highlights

### 1. Cryptographic Request Body Fingerprinting (`SHA-256`)
When a client sends an `Idempotency-Key` header alongside a payment request (`POST /api/payments/process-payment/`), the API calculates a **SHA-256 cryptographic hash** of the request body (`_hash_body()`). 
* **Payload Mismatch Protection:** If a malicious or buggy client reuses an existing `Idempotency-Key` with a different amount or currency, the API immediately intercepts and rejects the request with `422 Unprocessable Entity`.

### 2. Atomic Database Row-Level Locking (`SELECT ... FOR UPDATE`)
To eliminate race conditions when multiple worker threads or concurrent client loops retry the same transaction simultaneously:
* The transaction engine acquires an **exclusive database row lock** inside an atomic transaction using `IdempotencyRecord.objects.select_for_update(nowait=False)`.
* Concurrent threads attempting to process the same key block cleanly until the lock is released, guaranteeing zero double-charges.

### 3. Autonomous Self-Healing Failure Recovery
To fulfill core reliability principles and **build self-healing systems**, the API implements an autonomous dead-lock recovery engine (`_handle_existing_record`):
* If a server unexpectedly crashes, loses power, or drops a database connection mid-transaction while a record status is locked (`status = 'processing'`), the lock would normally orphan forever.
* **Automated Stale-Lock Detection:** The system continuously tracks `locked_at` timestamps. If a lock exceeds the 60-second threshold without finishing, the engine automatically purges the orphaned record and returns `409 Conflict (retry: true)`. 
* Client loops can safely self-heal and retry immediately without human intervention or manual database cleanup.

### 4. Hashed API-Key Authentication (`X-API-Key`)
* Custom DRF permission class (`HasAPIKey`) enforces secure header-based authentication across all endpoints.
* **Zero Plaintext Storage:** API keys (`pay_prefix.secret`) are displayed only once in the admin dashboard upon creation and stored exclusively as **SHA-256 hashes** (`hashed_key`).

---

## 🧪 Comprehensive Automated Regression Test Suite

The project includes **21 comprehensive automated regression tests** covering high-concurrency race conditions, API key security, payload tampering, and self-healing stale lock recovery.

Run the test suite locally:
```bash
python manage.py test payments.tests --verbosity=2
```

### Test Coverage Summary (`payments/tests.py`):
* ✅ `test_api_key_creation_and_hashing`: Verifies SHA-256 storage and one-time secret display.
* ✅ `test_payment_with_valid_api_key`: Verifies 201 Created and successful processing.
* ✅ `test_payment_missing_or_invalid_api_key`: Verifies 403 Forbidden security enforcement.
* ✅ `test_idempotency_retry_returns_cached_response`: Verifies exactly-once processing (returns cached 201 without charging twice).
* ✅ `test_idempotency_body_mismatch_returns_422`: Verifies SHA-256 body fingerprint verification.
* ✅ `test_stale_processing_lock_self_healing`: Verifies automated 60s timeout self-healing (`409 Conflict`).
* ✅ `test_cleanup_idempotency_keys_command`: Verifies automated background TTL expiration cleanup (`24 hours`).

---

## 🛠️ Quick-Start & cURL Examples

### 1. Process a Payment (`POST`)
```bash
curl -X POST https://rude-breads-smell.loca.lt/api/payments/process-payment/ \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: txn_998877_unique_key_001" \
  -H "X-API-Key: pay_2b4ce484.F_6jW5rNjpa9DDj-JH0NtYNMMB2WIJn07cLwE4uEdu4" \
  -d '{"amount": "250.00", "currency": "USD", "description": "Cloud Subscription"}'
```
**First Response (`201 Created`):**
```json
{
  "id": 1,
  "idempotency_key": "txn_998877_unique_key_001",
  "amount": "250.00",
  "currency": "USD",
  "status": "completed"
}
```

**Retry with Same Key (`201 Created` - Replayed from Cache without Double Charging):**
```json
{
  "id": 1,
  "idempotency_key": "txn_998877_unique_key_001",
  "amount": "250.00",
  "currency": "USD",
  "status": "completed"
}
```

---

## ☁️ Production Deployment

This repository is pre-configured for instant 1-click deployment on platforms like **Render**, **Railway**, or **Heroku**:
* **`requirements.txt`**: Clean production dependencies (`django`, `djangorestframework`, `python-dotenv`, `gunicorn`, `whitenoise`).
* **`Procfile`**: Configured for WSGI server (`web: gunicorn payment_api.wsgi:application`).
* **`settings.py`**: WhiteNoise middleware enabled for compressed static files (`/admin/` CSS/JS).
