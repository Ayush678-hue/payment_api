Idempotent Payment API

A production-grade, fault-tolerant Payment API designed to ensure transactional integrity and prevent double-charging through idempotency.

🚀 The Problem
In financial systems, network timeouts during requests are inevitable. A standard API might process a payment, but if the client doesn't receive the confirmation due to a network glitch, they might retry the request. Without proper handling, this leads to double-charging.

🛠 The Solution
This API implements an Idempotency Pattern. By requiring an ⁠Idempotency-Key⁠ header, the system checks the transaction history before processing funds. If a key matches a previous request, the system returns the stored result instead of performing a duplicate action.

⚙️ Key Engineering Features
 Idempotency Logic: Implements a strict "Check-then-Act" pattern to ensure each request is processed exactly once.
 
 Transactional Integrity: Designed with database atomicity in mind to ensure account balances and transaction logs remain perfectly synchronized.
 
 Audit-Ready: Every transaction is logged, providing a clear "Source of Truth" for debugging and fraud monitoring.
 Modular Architecture: Clean separation between routing, business logic, and data models for easy scalability.
 
🚀 Getting Started

Prerequisites

 Python 3.x
 
 Django 5.x


