<div align="center">

# Renvue

### Autonomous revenue recovery for PayPal merchants

[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141%2B-009688.svg)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agentic%20Orchestration-blueviolet.svg)](https://langchain-ai.github.io/langgraph/)
[![React](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev)
[![PayPal](https://img.shields.io/badge/PayPal-Orders%20%C2%B7%20Subscriptions%20%C2%B7%20Invoicing-003087.svg)](https://developer.paypal.com)

<p align="center">
  <b>Renvue</b> turns failed PayPal payments, halted subscriptions, abandoned checkouts, and overdue invoices into recovered revenue. A deterministic policy decides the next best action; PayPal APIs execute it; an LLM handles the customer conversation when one happens.
</p>

</div>

---

## The problem

Every merchant loses revenue to payments that fail for recoverable reasons: an expired card, a temporary insufficient-funds decline, an abandoned checkout, or an overdue invoice. Most dunning systems send the same reminder on the same schedule to every customer.

Renvue treats each failed payment as a case with its own history and picks one of nine recovery plays:

| Play | What it does |
| --- | --- |
| `no_contact` | Hold the case; do not contact the customer |
| `email_link` | Send a PayPal payment link by email |
| `sms_link` | Send a PayPal payment link by SMS/WhatsApp |
| `paypal_invoice_reminder` | Send a PayPal invoice reminder |
| `retry_now` | Retry the payment now |
| `retry_payday` | Schedule a retry around a payday signal |
| `update_method_link` | Send a PayPal link to update the payment method |
| `discount_link` | Offer a bounded concession with a payment link |
| `human_escalation` | Stop automation and hand the case to a human |

## How it works

```text
PayPal webhook
    -> case upsert
    -> feature snapshot
    -> policy score over eligible plays
    -> deterministic guardrails (veto power)
    -> execute exactly one play through PayPal
    -> observe outcome
    -> append-only decision / action / outcome logs
```

- **The policy decides.** Routine outbound decisions make zero LLM calls. The policy scores only plays that are already eligible for the case.
- **Guardrails hold veto power.** Max 3 touches, contact windows, discount bounds of 5–30%, a 7-day cumulative grace cap, dispute freeze, opt-out/STOP, currency and amount sanity, and a human-approval threshold are enforced in code and tests.
- **The LLM only communicates.** LangGraph + Mistral is invoked for inbound replies, negotiation, promise-to-pay extraction, and free-text responses, always inside guardrail bounds. It never chooses the action or generates training labels.
- **Every decision is auditable.** Decision, action, and outcome rows carry the feature snapshot hash, policy version, alternatives considered, and guardrail result.

## PayPal integration

The backend talks to the PayPal REST API directly (no vendor SDK):

- **OAuth 2.0** client-credentials token with a shared cache.
- **Orders v2** — create recovery orders, return `payer-action` links, capture approved orders.
- **Subscriptions v1** — read subscription state and create update-method links.
- **Invoicing v2** — create and remind on recovery invoices.
- **Disputes** — freeze dunning when a dispute is opened.
- **Webhooks** — verify `PAYPAL-TRANSMISSION-*` headers with `POST /v1/notifications/verify-webhook-signature`, then de-duplicate on `event.id`.
- **Buyer redirects** — `/api/paypal/return` captures approved orders and updates the matching case; `/api/paypal/cancel` confirms that no capture occurred.

Handled events include `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `PAYMENT.CAPTURE.PENDING`, `BILLING.SUBSCRIPTION.PAYMENT.FAILED`, `INVOICING.INVOICE.PAID`, `CUSTOMER.DISPUTE.CREATED`, and related lifecycle events. Unknown events are acknowledged and ignored.

## Stack

| Layer | Technology |
| --- | --- |
| API | FastAPI, Pydantic |
| Persistence | PostgreSQL, SQLModel, append-only audit tables |
| Agent | LangGraph, LangChain, Mistral |
| Background jobs | Taskiq, Redis |
| Realtime | Redis pub/sub, Server-Sent Events |
| Dashboard | React 19, Vite, Tailwind CSS v4 |
| Payments | PayPal REST APIs |

## Repository layout

```text
renvue/
├── backend/
│   ├── pyproject.toml
│   ├── .env.example
│   ├── scripts/paypal_proof.py        # $10 sandbox order / capture proof
│   └── src/
│       ├── agent/                     # LangGraph graph, nodes, prompts, tools
│       ├── background/                # Taskiq worker and scheduler
│       ├── config/                    # settings, DB, clients
│       ├── data/generate.py           # synthetic demo data
│       ├── models/                    # SQLModel tables and tool schemas
│       ├── paypal/                    # auth, orders, subscriptions, invoicing, disputes, webhooks
│       ├── policy/                    # locked Play/Observation/Action/Outcome contracts
│       ├── router/                    # PayPal webhooks, inbound replies, API, simulator
│       ├── service/                   # event loop, guardrails, decisions, money
│       └── tests/                     # six regression suites
├── frontend/                          # React operations dashboard
├── docker-compose.yml                 # local PostgreSQL + Redis
├── Dockerfile
└── LICENSE
```

## Quick start

### Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and `npm`
- Docker (for local PostgreSQL and Redis)
- A PayPal sandbox REST app from [developer.paypal.com](https://developer.paypal.com/dashboard/applications/sandbox)

### 1. Start infrastructure

```bash
docker compose up -d
```

### 2. Configure the backend

```bash
cp backend/.env.example backend/.env
```

Fill in `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` from the sandbox app. Keep `PAYPAL_API_BASE=https://api-m.sandbox.paypal.com` for sandbox work. Real credentials belong only in `backend/.env`, which is gitignored.

### 3. Install and run

```bash
cd backend
uv sync

# Terminal 1 — API
uv run uvicorn src.main:app --reload --port 8000

# Terminal 2 — worker
uv run taskiq worker -d src background.worker:broker

# Terminal 3 — scheduler
uv run taskiq scheduler -d src background.worker:scheduler
```

### 4. Start the dashboard

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### 5. Expose the webhook

PayPal requires a public HTTPS endpoint. Tunnel the API and register the URL in **Apps & Credentials → Webhooks**:

```bash
ngrok http 8000
# Webhook URL: https://<tunnel>/webhooks/paypal
```

Set `PAYPAL_WEBHOOK_ID` (or comma-separated `PAYPAL_WEBHOOK_IDS`) in `backend/.env` so signature verification can use the registered webhook.

## PayPal sandbox proof

The proof script creates a $10.00 USD order, prints the buyer approval URL, and captures the order after approval.

```bash
cd backend
uv run python scripts/paypal_proof.py
```

Open the printed `checkoutnow?token=...` URL with a **separate PayPal sandbox personal buyer account** and approve the payment. PayPal redirects to `/api/paypal/return`, which captures the approved order automatically. Record the capture evidence with:

```bash
uv run python scripts/paypal_proof.py --capture <ORDER_ID>
```

The script writes local evidence to `backend/data/paypal_proof.json` (gitignored) and refuses non-sandbox hosts unless `--allow-live` is passed. It never prints or stores the client secret or OAuth token.

Verified sandbox capture (2026-10-31): order `79239162G4187994B` → capture `52M84231CC782152A`, status `COMPLETED`, `$10.00 USD`.

## Tests

Six regression suites cover the lifecycle, promise-to-pay, B2B invoices, subscriptions, checkout concessions, and webhook security:

```bash
cd backend
PYTHONPATH=src uv run python src/tests/runner.py
```

Run one suite directly, for example:

```bash
PYTHONPATH=src uv run python src/tests/test_webhook_security.py
```

Frontend production build:

```bash
cd frontend
npm run build
```

## Demo simulator

The dashboard includes a PayPal-shaped event simulator for local demos. It is a test rig, not evidence about real merchants. Every simulated case is labeled as simulated in the UI and logs.

The API also exposes `/fake-event` and `/fake-action` for scripted demo runs.

## Security notes

- Secrets are read from `backend/.env` only; `.env.example` contains placeholders.
- Webhook deliveries are verified with PayPal's signature API before they are processed.
- Webhook events are de-duplicated on `event.id`, and processing failures are logged without causing PayPal retry loops.
- `.opencode/`, `opencode.json`, logs, local databases, and generated proof files are gitignored.

## License

MIT — see [LICENSE](LICENSE).
