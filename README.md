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

<div align="center">
  <br/>
  <img src="agent_workflowv2.png" alt="Renvue LangGraph Agent Workflow" width="460" />
  <p><sub><em>Compiled LangGraph StateGraph showing pre-flight compliance guardrails, dual-path deterministic vs tool routing, and human-in-the-loop escalation gates.</em></sub></p>
  <br/>
</div>

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
| Agent | LangGraph, LangChain, Mistral (or Gemini / Groq) |
| Background jobs | Taskiq, Redis / Valkey |
| Realtime | Redis pub/sub, Server-Sent Events |
| Dashboard | React 19, Vite, Tailwind CSS v4 |
| Data grid | AG Grid Community v36 (Quartz Graphite, virtualized, multi-sort, CSV export) |
| Deployment | Render Blueprint (`render.yaml` isolated Web + Worker architecture) |
| Payments | PayPal REST APIs (Orders v2, Subscriptions v1, Invoicing v2, Disputes) |

## Repository layout

```text
renvue/
├── agent_workflowv2.png               # Compiled LangGraph StateGraph visual
├── render.yaml                        # Render Infrastructure as Code Blueprint
├── docker-compose.yml                 # Local PostgreSQL + Redis
├── Dockerfile                         # Unified multi-process container (supervisord)
├── start-tmux.sh                      # 4-quadrant tmux development launcher
├── backend/
│   ├── pyproject.toml
│   ├── Dockerfile                     # Production-ready slim backend container
│   ├── .env.example
│   ├── scripts/
│   │   ├── paypal_proof.py            # $10 sandbox order / capture proof
│   │   ├── seed_diverse_cases.py      # Seeds 34 diverse recovery cases
│   │   └── start-worker.sh            # Taskiq worker & scheduler entrypoint
│   └── src/
│       ├── agent/                     # LangGraph graph, nodes, prompts, tools
│       ├── background/                # Taskiq worker and scheduler
│       ├── config/                    # settings, DB, clients
│       ├── data/generate.py           # synthetic demo data
│       ├── ml/                        # empirical Bayes, runtime scoring, nightly retrain
│       ├── models/                    # SQLModel tables and tool schemas
│       ├── paypal/                    # auth, orders, subscriptions, invoicing, disputes, webhooks
│       ├── policy/                    # locked Play/Observation/Action/Outcome contracts
│       ├── router/                    # PayPal webhooks, inbound replies, API, simulator, learning
│       ├── service/                   # event loop, guardrails, decisions, money
│       └── tests/                     # eight regression suites
├── frontend/                          # React operations dashboard
│   ├── src/components/CaseGrid.tsx    # AG Grid Community v36 implementation
│   └── src/components/AgentLab.tsx    # Policy simulator & empirical Bayes panel
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

`DEMO_MODE=false` (the default in `.env.example`) calls the PayPal sandbox. Set it to `true` only for an offline demo: PayPal links and outbound email/WhatsApp are mocked, and the case drawer labels the link as a mock.

Outbound delivery is reported honestly per audit entry: `delivery_status` is `sent`, `captured`, or `failed`. `captured` means a sandbox/test double accepted the message because no provider credentials were configured (or `DEMO_MODE=true`); it does **not** mean the customer received it. Failed sends are recorded as `outreach_failed` and the executor falls back to the other real channel.

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

Open `http://localhost:5173`. The dashboard defaults to `http://localhost:8000/api`; if the API runs elsewhere, set `VITE_API_URL` (for example `http://localhost:8001/api`) before starting Vite.

### Alternative: One-command tmux development environment

Instead of 4 separate terminals, launch the full system (FastAPI backend, Vite frontend, Taskiq worker, Taskiq scheduler) tiled in a single 2x2 tmux session:

```bash
./start-tmux.sh
```

- Mouse scrolling and clicking work across all 4 quadrants.
- `Ctrl+b` then `d` to detach (all background services keep running).
- `./start-tmux.sh stop` terminates all 4 processes cleanly.

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

The return URL must point at the Renvue backend. If another app owns that port, set `BACKEND_URL` to the Renvue port and restart the backend before creating the order.

Verified sandbox capture (2026-10-31): order `79239162G4187994B` → capture `52M84231CC782152A`, status `COMPLETED`, `$10.00 USD`.

Verified sandbox recovery (2026-11-01):

- Simulated failed payment → case `failed_1793526831_992` ($125.00 USD)
- Policy `rules-v0` → `retry_payday`; guardrails passed
- PayPal order `43F2483513474512X` → buyer approval → capture `1TY06259TY549621D`, status `COMPLETED`
- Case marked `recovered`; dashboard recovered total `$125.00 USD`
- Signed `CHECKOUT.ORDER.APPROVED` and `PAYMENT.CAPTURE.COMPLETED` webhooks verified against the registered webhook and de-duplicated

The failure event was seeded by the demo simulator. The order, buyer approval, capture, and webhooks are real PayPal sandbox activity.

## Online learning & empirical Bayes loop

Renvue closes the feedback loop between real payment outcomes and future outreach decisions without risky live exploration:

- **Empirical Bayes updates:** The recovery policy blends an offline-trained LightGBM model prior with play-level Beta-Bernoulli empirical Bayes updates from observed attempt outcomes ($w = \frac{n}{n + s}$). When learning updates rates, decisions are tagged with `+eb`.
- **Offline model vs online updates:** The LightGBM tree weights remain frozen offline; online learning continuously updates observational play response rates.
- **Strict provenance separation:** Live outcomes from production webhooks (`provenance="live"`) are never mixed with simulated cases or sandbox experiments (`provenance="sandbox"`).
- **Delivery verification:** A failed email or WhatsApp delivery is an operational failure, not customer silence. Only attempts with verified delivery (`sent` or `captured`) can ever produce an `unresponsive_timeout` non-response learning sample.
- **Safety gates & retraining:** Nightly retraining is real, wired via Taskiq, and strictly gated behind 5 thresholds (100 samples, 20 recoveries, 3 eligible plays, 7 days, 5 samples/play). Auto-promotion is disabled by default (`RETRAIN_ENABLED=false`).
- **Honest metrics:** The measured ML-vs-rules difference on the calibrated simulator is $6.75 per 1,000 cases with a 95% CI of `[-$877.52, +$979.73]`. We do not claim causal lift.

## Tests

Eight regression suites cover the lifecycle, promise-to-pay, B2B invoices, subscriptions, checkout concessions, webhook security, ML policy / Agent Lab API, and empirical Bayes learning with retrain safety gates:

```bash
cd backend
PYTHONPATH=src uv run python src/tests/runner.py
```

Run one suite directly, for example:

```bash
cd backend
PYTHONPATH=src uv run python src/tests/test_learning.py
```

Frontend production build:

```bash
cd frontend
npm run build
```

## AG Grid unified case grid

Renvue integrates **AG Grid Community v36** as its unified primary grid across the dashboard (`Overview` active processing queue, resolved history, and the full `Cases` management tab at `/#cases`):
- **Quartz Graphite theme**: Custom-tokenized dark palette (`#19191b` background, `#141415` headers, `#ededed` text) matching Renvue's visual language with hairline borders and zero browser-native select popups.
- **Multi-dimensional semantic filtering**:
  - *Categorical*: Failure type (Failed payments, Halted subscriptions, Overdue invoices, Abandoned checkouts) and Outreach channel (Email link, WhatsApp, Payday retry, Method update, Invoice reminder).
  - *Numerical*: Tiered monetary ranges (Micro `< $100`, Mid `$100 - $1,000`, High `$1,000 - $5,000`, Enterprise `> $5,000`).
  - *Ordinal*: Touch progression (1st touch, 2nd touch, 3rd touch with visual progress pips `●○○`, `●●○`, `●●●`).
- **Clean header sorting**: In-grid column menus suppressed (`suppressHeaderMenuButton: true`) to ensure column headers purely and cleanly sort with one click.
- **Enterprise-grade features**: Virtualized DOM rendering, one-click CSV export (`gridApi.exportDataAsCsv()`), live search across name/email/case ID, dynamic status tabs, and side-drawer case inspection.
- **Code-split bundle**: Dynamic import via `React.lazy` and `Suspense` keeps the core landing dashboard bundle lean (440 kB) while streaming AG Grid asynchronously.

## Deployment on Render (`render.yaml`)

Renvue includes an Infrastructure-as-Code Blueprint (`render.yaml`) configuring an isolated microservice architecture:

| Service | Type | Plan / Tier | Purpose |
| --- | --- | --- | --- |
| `renvue-db` | PostgreSQL | Basic ($7/mo) | Persistent ACID database; never sleeps, does not expire after 30 days |
| `renvue-redis` | Key-Value (Valkey) | Free ($0/mo) | In-memory Taskiq message broker and SSE live broadcast channel |
| `renvue-api` | Web Service | Starter ($7/mo) | FastAPI backend; 512 MB isolated RAM, auto-seeds 34 diverse cases on start |
| `renvue-worker` | Background Worker | Starter ($7/mo) | Taskiq worker & scheduler; 512 MB isolated RAM, runs scheduled recovery plays |
| `renvue-web` | Static Site | Free ($0/mo) | Vite React SPA deployed to global CDN with automatic SPA client routing |

**Process isolation**:
Running the FastAPI API and Taskiq worker in separate 512 MB containers guarantees that heavy background batch operations or retries never starve the API of CPU or memory, ensuring judges and users experience snappy 50ms dashboard interactions without HTTP 502 gateway timeouts.

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
