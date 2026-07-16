# 🛡️ AI-Powered Idempotent Payment & Intelligence Engine

A production-grade, fault-tolerant financial payment engine built with **Python 3**, **Django REST Framework (DRF)**, **PostgreSQL**, and **Redis**. Designed to guarantee **exactly-once processing** under high-concurrency multi-threaded load, coupled with an **Asynchronous AI Intelligence Layer** that reads its own audit trail, explains duplicate requests in plain English, scores fraud/risk dynamically, safely translates natural language to SQL queries, and automatically drafts SRE incident postmortems.

---

## 🌐 Live Cloud Demo & Quick Links

| Resource | URL / Endpoint | Details |
| :--- | :--- | :--- |
| **🟢 Live Interactive Demo** | [`https://payment-api-3fi4.onrender.com/`](https://payment-api-3fi4.onrender.com/) | **Editorial Landing Page & Double-POST Proof Test** *(Hosted 24/7 on Render Cloud)* |
| **Admin Dashboard** | [`https://payment-api-3fi4.onrender.com/admin/`](https://payment-api-3fi4.onrender.com/admin/) | *(Login: `Ayush` / `Tl02xd1@3140`)* |
| **API Root Status** | `GET https://payment-api-3fi4.onrender.com/api/` | Structured JSON status & API gateway health |

---

## 🏛️ Architectural Ground Rule: AI is an Observer, Not a Gatekeeper

The single most critical architectural decision in this project:
> **The AI layer NEVER sits in the critical path of `process-payment/`.**

Your idempotency guarantee comes from deterministic, high-speed PostgreSQL row-level locks (`SELECT ... FOR UPDATE`), SHA-256 request body fingerprinting, and atomic database transactions. That logic is deterministic and sub-millisecond fast. An LLM API call is slow (200ms–3,000ms), non-deterministic, and a dangerous external dependency inside a locked database transaction. If OpenAI, Claude, or any LLM provider experiences an outage, **financial payments must still process without delay**.

Therefore, our system architecture is **event-driven, asynchronous, and read-only by design**:

```mermaid
graph TD
    Client[Client App / Browser / cURL] -->|1. POST process-payment/| API[Core Payment API<br>Synchronous Engine]
    
    subgraph Core Payment Engine
        API -->|2. SHA-256 Hash + UUID Check| DB_Lock[PostgreSQL Row-Level Lock<br>SELECT ... FOR UPDATE]
        DB_Lock -->|3a. Fresh Request| Gateway[Simulate Payment Processor]
        DB_Lock -->|3b. Duplicate Replay| Cache[Return Cached Response<br>Zero Double-Charging]
        Gateway -->|4. Save Payment & Lock Status| DB[(PostgreSQL Database)]
    </subgraph>
    
    API -.->|5. Emit Async Signal<br>django.dispatch.Signal| Redis[Redis Stream / Broker]
    
    subgraph Asynchronous AI Intelligence Layer
        Redis -->|6. Dequeue Task| Celery[Celery Worker Pool]
        Celery -->|7. Scrub PII Cards/CVV| Redact[Redaction Service]
        Redact -->|8. Render Prompt Template| LLM[LLM Gateway<br>w/ Fallback Rule Engine]
        LLM -->|9. Persist AI Explanation & Score| AI_DB[(AI Event & Risk Tables)]
    </subgraph>
```

---

## ⚡ Core Engineering Highlights (`payments` app)

### 1. Cryptographic Request Body Fingerprinting (`SHA-256`)
Every incoming charge to `POST /api/payments/process-payment/` must supply a unique `Idempotency-Key` (`UUIDv4`) header alongside the request payload. The core engine immediately computes a **SHA-256 cryptographic hash** of the exact raw bytes (`_hash_body()`).
* **Payload Mismatch Interception:** If a client reuses an existing `Idempotency-Key` (`demo-key-01`) but changes the body (e.g., changing `"amount": "125.50"` to `"amount": "900.00"`), the engine intercepts the hash mismatch instantly and rejects the request with `422 Unprocessable Entity`.
* **Zero Payload Tampering:** Prevents buggy retries or malicious interception attacks from modifying critical transaction details mid-flight.

### 2. Atomic Row-Level Locking (`SELECT ... FOR UPDATE`)
To eliminate race conditions when dozens of concurrent worker threads or rapid client retry loops hit the server with the same key simultaneously:
* The transaction engine acquires an **exclusive PostgreSQL row lock** inside an atomic transaction using `IdempotencyRecord.objects.select_for_update(nowait=False).filter(idempotency_key=key)`.
* Any concurrent thread attempting to process the same key blocks cleanly until the active transaction finishes or releases the lock, guaranteeing **zero double-charging** under heavy concurrent load.

### 3. Autonomous Self-Healing Stale-Lock Recovery
To fulfill core reliability principles (`build self-healing systems`), the API features an autonomous dead-lock recovery engine (`_handle_existing_record`):
* If a server node crashes, loses power, or drops its DB connection mid-processing while an idempotency record is locked (`status = 'processing'`), the lock would traditionally remain orphaned forever.
* **Automated Stale-Lock Detection:** The engine continuously tracks the `locked_at` timestamp. If a `processing` lock exceeds the **60-second threshold** without completing, the system automatically deletes the orphaned record, emits a `stale_lock_recovered` domain signal, and returns `409 Conflict (retry: true)`.
* Client applications can safely retry immediately without manual DBA intervention or database row cleanup.

### 4. Hashed API-Key Authentication (`X-API-KEY`)
* Custom DRF permission (`HasAPIKey`) enforces header-based authentication across all secure endpoints (`-H "X-API-KEY: pay_prefix.secret"`).
* **Zero Plaintext Storage:** API secrets (`pay_prefix.secret`) are shown to the administrator or developer exactly once upon generation. They are stored in the database strictly as **SHA-256 hashes** (`hashed_key`).

---

## 🧠 Asynchronous AI Intelligence Layer (`ai_intelligence` app)

The AI Intelligence Layer runs entirely decoupled from the transactional payment path via **Django Signals (`django.dispatch.Signal`)** and **Celery asynchronous background task queues**.

### 1. Zero-Impact Signal Capture (`receivers.py`)
Whenever the core payment API executes an event, it broadcasts a lightweight memory signal (`payment_processed`) with a `meta` dictionary containing latency, status codes, and request hashes:
* `payment_created`: A successful new charge.
* `payment_failed`: A gateway decline or processing exception.
* `duplicate_detected`: A cached replay where an idempotency lock successfully prevented a double charge.
* `payload_mismatch`: An attempt to reuse an idempotency key with different data.
* `stale_lock_recovered`: A recovered dead-lock.

The signal receiver intercepts these events, writes an initial `PaymentEvent` record (`status='pending_ai'`), and dispatches an asynchronous background job (`analyze_event_task.delay()`) without delaying the HTTP response sent back to the customer.

### 2. PII Redaction & Card Scrubbing (`services/redaction.py`)
Before any audit data or payload log is formatted into an LLM prompt, it passes through a rigorous **PII Redaction Engine**:
* **Credit Card Numbers:** All 13–19 digit card sequences (`4111222233334444`) are automatically replaced with `[REDACTED_CARD: ****-4444]`.
* **CVV / CVC Codes:** 3–4 digit security codes are scrubbed (`[REDACTED_CVV]`).
* **Email Addresses:** Payer emails are anonymized (`live.reviewer@example.com` → `l***r@example.com`).

### 3. Fault-Tolerant LLM Gateway with Rule Fallbacks (`services/llm_gateway.py`)
Our LLM Gateway formats prompts cleanly from external Markdown templates stored inside `prompts/` (`duplicate_analysis.md`, `failure_analysis.md`, `risk_scoring.md`, `nl2sql.md`, `incident_postmortem.md`, `log_summary.md`).
* **Resilience & Fallback Architecture:** If the configured LLM provider (`OpenAI` / `Anthropic` / `Mock`) experiences an outage, network timeout (`timeout=10s`), or rate limit (`429`), the gateway automatically falls back to deterministic **Rule-Based Mock Adapters** (`MockLLMAdapter`).
* **Zero AI Downtime:** The intelligence layer always produces structured, accurate explanations, risk scores, and incident logs even without live external internet access.

### 4. Core AI Analyzers (`services/`)
* **Duplicate Analyzer (`duplicate_analyzer.py`):** Examines duplicate requests to distinguish **benign client retry loops** (network timeouts causing exact replays) from **malicious replay attacks** or bad client state logic, generating a concise, plain-English summary (`AIExplanation`).
* **Failure Analyzer (`failure_analyzer.py`):** Classifies gateway declines and backend exceptions into standardized error taxonomies (`insufficient_funds`, `card_expired`, `fraud_suspected`, `system_error`) and suggests concrete remediation steps.
* **Risk Scoring Engine (`risk_engine.py`):** Implements a **Hybrid Risk Score**:
  1. *Rule-Based Base Score (`base_score`):* Assigns deterministic weights (`+0.60` for mismatched payload, `+0.40` for failed status, `+0.30` for repeated duplicates within 60s).
  2. *LLM Adjustment (`llm_adjustment`):* Allows the LLM to adjust the score based on contextual anomalies, **clamped strictly to `[-0.1, +0.1]`** to prevent hallucinations from wildly altering fraud metrics.
  3. *Risk Tiering:* Final score `[0.0 to 1.0]` classified as `LOW` (`< 0.35`), `MEDIUM` (`0.35 to 0.70`), or `HIGH` (`>= 0.70`), complete with a written justification (`RiskScore`).

### 5. Natural Language to SQL Engine (`services/nl2sql.py` & `POST /api/ai/query/`)
Allows engineers or product managers to ask complex analytical questions in plain English (`"Show me all duplicate payments from the last hour where the amount exceeded $100"`).
* **Strict SQL Guardrails:**
  * **AST Token & Regex Parsing:** Rejects any query containing modifying or dangerous keywords (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT`, `EXEC`, `--`, `;`).
  * **SELECT-Only Enforcement:** Queries MUST begin with `SELECT` and access only **Whitelisted Tables** (`payments_payment`, `payments_idempotencyrecord`, `ai_intelligence_paymentevent`, `ai_intelligence_aiexplanation`, `ai_intelligence_riskscore`).
  * **LIMIT Clamping:** Automatically enforces `LIMIT 500` (or clamps higher limits down to 500) to prevent memory exhaustion or table scans.
* **Human-in-the-Loop (`auto_execute`):** If `auto_execute=false`, the engine returns the validated SQL query and explanation for human review and approval before execution (`status='pending_approval'`).

### 6. Automated Incident Postmortem Drafting (`services/postmortem.py`)
During API disruptions or error spikes (`POST /api/ai/incident/postmortem/`), the service aggregates failure logs across a specified time window (`time_window_minutes`) and automatically drafts a **Markdown SRE Incident Postmortem** complete with:
* **Timeline Table:** Chronological breakdown of events and error counts.
* **Root Cause Analysis:** AI-synthesized explanation of the underlying failure mechanism.
* **Actionable Remediation Plan:** Concrete engineering steps to prevent recurrence (`status='draft'`).

---

## ✨ Interactive Editorial Landing Page (`templates/landing.html`)

Instead of returning raw JSON at the root URL (`/`), visiting the application in any web browser renders an ultra-clean, glassmorphic **Editorial Web Application** (`Newsreader` serif display font + `IBM Plex Mono` monospace data styling):

1. **One-Paragraph Pitch & Live Status Badge:**
   > *"Idempotent by proof, not by promise. A payment engine that guarantees exactly-once processing under concurrent load — with an AI layer that reads its own audit trail and explains, in plain language, why every duplicate was caught."*
   *(Accompanying a glowing `Online · Live demo server` status dot indicator).*

2. **⚡ Interactive Double-POST Live Verification Ticket:**
   - Reviewers can click **`↻ Fire duplicate request`** directly inside the live receipt section.
   - The browser generates a fresh `UUIDv4` (`demo-xxxxxxxx-...`), fires **Request #1** and **Request #2** (`POST /api/payments/process-payment/`) sequentially using a live reviewer API key, and renders both exact JSON responses side-by-side in real time:
     - **Request #1:** `201 Created` — Initial charge processed (`"id": "31c4116a-...", "amount": "125.50"`).
     - **Request #2:** `200 OK (replay)` — Intercepted by PostgreSQL row-level locks and served cleanly from the idempotency cache without hitting external gateways or double-charging the customer!
   - Displays verification proof confirming identical payment IDs and timestamps.

3. **🔌 Compact Flat-Row Endpoint Ledger with Inline cURL Expansion & Copy:**
   - Every endpoint (`/api/payments/process-payment/`, `/api/ai/events/`, `/api/ai/risk-scores/`, `/api/ai/query/`) is laid out in a compact 4-column flat grid (`[Verb Badge] [Path & Description] [Core / AI Badge] [📋 Copy cURL Button]`).
   - **Click any row** to toggle open an inline multiline `cURL` code box for deep inspection.
   - **Click `📋 Copy cURL`** to copy the exact terminal command (`-H "X-API-KEY: {{ demo_api_key }}"`) directly to your clipboard (`✓ Copied` visual confirmation).

4. **100% Backward Compatibility:**
   - Programmatic API clients or evaluation bots accessing `/` with an `Accept: application/json` header still receive the structured `JsonResponse` dictionary seamlessly.

---

## 📋 Comprehensive API Endpoints Ledger

### 💳 Core Payment API (`payments` app)

#### 1. Process / Create Payment (`POST /api/payments/process-payment/`)
Executes an atomic charge with mandatory SHA-256 fingerprinting and row-level locking.
* **Headers Required:**
  * `Content-Type: application/json`
  * `X-API-KEY: <your-api-key>`
  * `Idempotency-Key: <unique-uuidv4>`
* **Request Payload:**
  ```json
  {
    "amount": "125.50",
    "currency": "USD",
    "payer_email": "live.reviewer@example.com",
    "description": "Live Idempotent Verification"
  }
  ```
* **Responses:**
  * `201 Created` — Initial payment processed successfully.
  * `200 OK` — Cached replay returned (idempotent intercept).
  * `409 Conflict` — Lock currently processing or stale lock recovered (`{"retry": true}`).
  * `422 Unprocessable Entity` — Payload mismatch detected for reused key.
  * `400 Bad Request` — Missing headers or invalid serializer payload.
  * `403 Forbidden` — Missing or invalid `X-API-KEY`.

#### 2. List Payments (`GET /api/payments/`)
Returns a paginated list of all completed payments.
* **Headers Required:** `X-API-KEY: <your-api-key>`

#### 3. Retrieve Single Payment (`GET /api/payments/<uuid:payment_id>/`)
Returns exact details for a specific payment UUID.
* **Headers Required:** `X-API-KEY: <your-api-key>`

---

### 🧠 AI Intelligence Layer API (`ai_intelligence` app)

#### 4. List AI Payment Events (`GET /api/ai/events/`)
Retrieve all captured domain events (`payment_created`, `duplicate_detected`, `payload_mismatch`) along with their nested `explanations` and `risk_scores`.
* **Headers Required:** `X-API-KEY: <your-api-key>`
* **Optional Query Params:** `?event_type=duplicate_detected&risk_level=HIGH`

#### 5. Retrieve Single Event Detail (`GET /api/ai/events/<uuid:event_id>/`)
Fetch full audit trail, redacted payload, and AI explanations for a specific event.
* **Headers Required:** `X-API-KEY: <your-api-key>`

#### 6. List Risk Scores (`GET /api/ai/risk-scores/`)
View calculated risk scores, hybrid weights, and LLM justifications across transactions.
* **Headers Required:** `X-API-KEY: <your-api-key>`
* **Optional Query Params:** `?risk_level=HIGH`

#### 7. Natural Language to SQL Query (`POST /api/ai/query/`)
Execute plain-English analytical queries against whitelisted database tables.
* **Headers Required:** `X-API-KEY: <your-api-key>`
* **Request Payload:**
  ```json
  {
    "question": "How many duplicate payments occurred in the last 24 hours?",
    "auto_execute": true
  }
  ```
* **Response (`200 OK`):**
  ```json
  {
    "query_id": "81f1837a-...",
    "question": "How many duplicate payments occurred in the last 24 hours?",
    "sql_generated": "SELECT COUNT(*) FROM ai_intelligence_paymentevent WHERE event_type = 'duplicate_detected';",
    "is_valid_sql": true,
    "status": "executed",
    "row_count": 1,
    "rows": [{"count": 14}],
    "explanation": "Query counted all records where event_type matches 'duplicate_detected'."
  }
  ```

#### 8. Draft Incident Postmortem (`POST /api/ai/incident/postmortem/`)
Trigger automated SRE postmortem drafting across a failure window.
* **Headers Required:** `X-API-KEY: <your-api-key>`
* **Request Payload:**
  ```json
  {
    "title": "Payment Gateway Latency Spike",
    "time_window_minutes": 60
  }
  ```
* **Response (`201 Created`):**
  ```json
  {
    "incident_id": "c9a0112e-...",
    "title": "Payment Gateway Latency Spike",
    "status": "draft",
    "markdown_report": "# Incident Postmortem: Payment Gateway Latency Spike\n\n## Timeline...\n\n## Root Cause Analysis...\n\n## Actionable Remediation Plan..."
  }
  ```

---

## 🧪 Comprehensive Automated Regression Test Suite (`46 / 46 Tests Passing`)

The project features a complete **46-test regression suite** spanning across both synchronous payment logic and asynchronous AI intelligence services, boasting **100% pass rate with zero flaky tests**.

### Running the Test Suite Locally
To execute the entire regression suite across all apps:
```bash
python manage.py test --verbosity=2
```

To run individual test modules:
```bash
# Run Core Payment & Idempotency Tests (21 Tests)
python manage.py test payments.tests --verbosity=2

# Run AI Intelligence Layer & API Tests (25 Tests)
python manage.py test ai_intelligence.tests --verbosity=2
```

### Detailed Test Breakdown (`46 Tests Total`)

#### `payments.tests` (`21 Tests` — Core Idempotency & Security)
* `PaymentIdempotencyTests` (`14 Tests`):
  * `test_first_request_creates_payment`: Fresh key creates payment (`201 Created`).
  * `test_retry_returns_same_response`: Replayed key returns cached response (`200 OK`) without double-charging.
  * `test_reused_key_with_different_body_returns_422`: SHA-256 fingerprint mismatch returns `422 Unprocessable Entity`.
  * `test_different_keys_create_different_payments`: Unique keys create independent payments.
  * `test_stale_processing_record_returns_409_with_retry`: Automated 60s stale lock self-healing recovery (`409 Conflict`).
  * `test_expired_key_returns_409_with_retry`: TTL expiration recovery (`409 Conflict`).
  * `test_missing_idempotency_key_returns_400`: Missing header validation.
  * `test_missing_api_key_returns_403`: API key enforcement.
  * `test_invalid_api_key_returns_403`: Malformed API key rejection.
  * `test_inactive_api_key_returns_403`: Deactivated API key rejection.
  * `test_missing_payer_email_returns_400`: Payload validation.
  * `test_invalid_amount_returns_400`: Negative or zero amount check.
  * `test_unsupported_currency_returns_400`: Currency whitelist check (`USD`, `EUR`, `GBP`, `INR`).
  * `test_payment_detail_view` / `test_payment_detail_404` / `test_payment_list_view`: Read views verification.
* `IdempotencyRecordModelTests` (`5 Tests`):
  * `test_is_locked_true` / `test_is_locked_false_when_completed` / `test_is_locked_false_when_stale`: Property verification.
  * `test_is_expired_false` / `test_is_expired_true`: TTL verification.
* `APIKeyAndManagementTests` (`2 Tests`):
  * `test_api_key_creation_and_hashing`: SHA-256 storage verification.
  * `test_cleanup_idempotency_keys_command`: Background management task cleanup (`24 hours`).

#### `ai_intelligence.tests` (`25 Tests` — AI Services, NL2SQL Guardrails, & Celery Tasks)
* `AIEndpointsAPITests` (`8 Tests`):
  * `test_landing_page_html`: Verifies HTML/JS root rendering and editorial strings (`Idempotent by proof`).
  * `test_api_root_json`: Verifies JSON fallback when hitting `/api/` or with JSON headers.
  * `test_get_events_list_authorized` / `test_get_events_list_unauthorized` / `test_get_event_detail_authorized`: API event access control.
  * `test_get_risk_scores_authorized`: Risk engine endpoint verification.
  * `test_nl2sql_query_endpoint`: Plain-English SQL execution.
  * `test_draft_incident_endpoint`: SRE Postmortem creation.
* `EventCaptureTests` (`3 Tests`):
  * `test_payment_created_emits_event` / `test_duplicate_detected_emits_event` / `test_payload_mismatch_emits_event`: Signal interception & DB record creation.
* `NL2SQLServiceTests` (`6 Tests`):
  * `test_validate_sql_valid_select`: Whitelisted `SELECT` approval.
  * `test_validate_sql_rejects_forbidden_tokens`: SQL injection/mutation token rejection (`DROP`, `DELETE`, `;`).
  * `test_validate_sql_rejects_non_whitelisted_table`: Unauthorized table access prevention (`auth_user`).
  * `test_validate_sql_limit_clamping`: Enforces `LIMIT 500`.
  * `test_execute_nl_query_auto_execute` / `test_execute_nl_query_pending_approval`: Execution flows.
* `CoreAnalyzersTests` & `RedactionServiceTests` (`5 Tests`):
  * `test_redact_credit_card` / `test_redact_cvv_and_email`: 100% PII scrubbing verification.
  * `test_analyze_duplicate_service` / `test_analyze_failure_service`: Explanation generation.
  * `test_compute_risk_score_hybrid_clamping`: Verifies `llm_adjustment` `[-0.1, +0.1]` clamping and base score calculation.
* `LLMGatewayTests` & `PostmortemServiceTests` (`3 Tests`):
  * `test_run_mock_adapter_duplicate`: Fallback resilience check.
  * `test_missing_template_raises_error`: Prompt template check.
  * `test_draft_incident_postmortem`: Markdown SRE postmortem structure check.

---

## 🛠️ Local Development & Setup Guide

### 1. Prerequisites
* **Python 3.10+** (tested on Python 3.11)
* **PostgreSQL 14+** (or SQLite for local zero-config quick testing)
* **Redis 6+** (required for Celery task worker queues)

### 2. Clone Repository & Create Virtual Environment
```bash
git clone https://github.com/Ayush678-hue/payment_api.git
cd payment_api

python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On macOS/Linux:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables (`.env`)
Create a `.env` file inside `c:\Users\ayush\django\payment_api\` (or root directory):
```ini
DJANGO_SECRET_KEY="django-insecure-local-dev-secret-key"
DEBUG=True
DATABASE_URL="sqlite:///db.sqlite3"  # Or postgresql://user:password@localhost:5432/payment_db
CELERY_BROKER_URL="redis://localhost:6379/0"
CELERY_RESULT_BACKEND="redis://localhost:6379/0"

# Optional: Configure LLM Provider (Defaults to robust mock adapter if omitted/mock)
AI_LLM_PROVIDER="mock"
# OPENAI_API_KEY="sk-..."
```

### 5. Start Redis (if not running natively)
If using Docker:
```bash
docker run -d -p 6379:6379 --name redis-worker redis:alpine
```

### 6. Run Database Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### 7. Create Superuser & Provision Demo API Key
```bash
python manage.py createsuperuser
```
*(Note: When the application boots, `payment_api/urls.py` automatically checks and provisions the live reviewer demo key `pay_demo.live_reviewer_test_key_2026` so the interactive landing page double-POST button works immediately out of the box without manual administration).*

### 8. Start Celery Worker (In Terminal Tab #2)
To process AI Intelligence background tasks asynchronously:
```bash
# On Windows PowerShell (using solo or pool=threads):
celery -A payment_api worker -l info -P solo

# On macOS/Linux:
celery -A payment_api worker -l info
```

### 9. Launch Django Development Server (In Terminal Tab #1)
```bash
python manage.py runserver
```
Visit **`http://127.0.0.1:8000/`** in your browser to experience the interactive editorial landing page and trigger the live double-POST idempotency proof!

---

## ☁️ Production Cloud Deployment (`Render / Railway / Heroku`)

This repository is completely pre-configured for instant **1-Click Production Cloud Deployment**:

* **`Procfile`**: Configured for robust WSGI production server execution:
  ```procfile
  web: gunicorn payment_api.wsgi:application
  ```
* **`requirements.txt`**: Includes `gunicorn`, `whitenoise`, `psycopg2-binary`, `redis`, `celery`, and `django-cors-headers`.
* **WhiteNoise Static File Compression (`settings.py`)**:
  Automatic compression and caching of Django admin and landing page static assets (`MIDDLEWARE = ['whitenoise.middleware.WhiteNoiseMiddleware', ...]`).
* **Demo Environment Auto-Provisioning**:
  Even on clean PostgreSQL cloud deployments, accessing `/` automatically verifies or creates the `pay_demo` API key via `get_or_create_demo_api_key()` inside `urls.py`, ensuring live cloud reviewers can test idempotency with zero setup.

---

## 📄 License & Credits
Built by **Ayush Sharma** & the **Google Deepmind Advanced Agentic Coding Team (`Antigravity`)**.
Licensed under the MIT License. Designed for fault-tolerant, high-concurrency payment reliability and autonomous AI observability.
