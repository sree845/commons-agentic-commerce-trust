# Commons — Trust Infrastructure for Agentic Commerce

**A PayPal-integrated, explainable trust and recovery layer for AI-agent transactions.**

> **Verify authority. Evaluate risk. Learn collaboratively. Enable recourse.**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-18-61DAFB)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688)](https://fastapi.tiangolo.com/)
[![PayPal](https://img.shields.io/badge/Payments-PayPal%20Sandbox-003087)](https://developer.paypal.com/)
[![License](https://img.shields.io/badge/License-Add%20before%20publishing-lightgrey)](#license)

## Overview

Artificial intelligence is changing online commerce. AI agents can increasingly discover products, make purchasing decisions, and initiate transactions on behalf of people. However, existing fraud detection approaches were largely designed around human purchasing behaviour.

This creates a new trust problem.

How can a merchant determine whether an AI agent is genuinely authorized to make a purchase? How can suspicious behaviour be identified without requiring merchants to exchange sensitive customer and transaction records? And when a legitimate transaction is incorrectly restricted, how can the decision be challenged?

**Commons addresses these challenges through an integrated agentic commerce trust and recovery architecture.**

Commons combines cryptographic agent authorization, explainable risk assessment, collaborative fraud intelligence, governed model adaptation, PayPal Sandbox payment integration, and evidence-backed recourse.

Rather than treating fraud detection as a single prediction, Commons treats trust as a process involving authority verification, behavioural assessment, controlled payment decisions, and accountability.

## The problem

Agentic commerce introduces several challenges:

- **Unclear agent authority:** A transaction may be initiated by an AI agent without sufficient proof of what it is permitted to purchase or spend.
- **Changing attack behaviour:** Traditional fraud indicators may not adequately represent autonomous purchasing patterns, repeated agent activity, or misuse of delegated authority.
- **Fragmented merchant intelligence:** Individual merchants may encounter similar attacks but cannot freely exchange raw customer and transaction information.
- **Unaccountable automated decisions:** A transaction restriction needs an understandable explanation and a mechanism for review.
- **Unsafe model adaptation:** Fraud models must adapt to emerging attacks without silently replacing an approved model with an unvalidated candidate.

Commons explores how these challenges can be addressed within one demonstrable system.

## The solution

Commons uses a layered trust workflow:

1. **Establish authority:** Verify a digitally signed agent mandate and its permitted transaction conditions.
2. **Assess behavioural risk:** Extract trusted transaction features and generate an explainable risk assessment.
3. **Collaborate across merchants:** Demonstrate federated model learning using model updates rather than raw order records.
4. **Govern adaptation:** Evaluate emerging attack candidates and require explicit approval before model promotion.
5. **Control payment execution:** Integrate with PayPal Sandbox for checkout, buyer authorization, risk evaluation, and authenticated payment execution.
6. **Provide recourse:** Preserve evidence, accept appeals, and maintain tamper-evident audit records.

A valid mandate establishes permission; it does not automatically establish that a transaction is safe.

## System architecture

```text
                  AI AGENT
                     |
                     v
          Signed Agent Mandate
                     |
                     v
          Cryptographic Verification
          - Ed25519 signature
          - Expiry validation
          - Spending constraints
          - Allowed categories
          - Nonce and replay protection
          - Agent revocation
                     |
                     v
             ORDER TRUST LAYER
                     |
          +----------+----------+
          |                     |
          v                     v
   Trusted Features       PayPal Sandbox
          |                Checkout Workflow
          v                     |
   Explainable Risk             |
       Engine                   |
          |                     |
          +----------+----------+
                     |
                     v
             PAYMENT DECISION
             CAPTURE / HOLD / VOID
                     |
                     v
           Authenticated Operator
               Execution
                     |
          +----------+----------+
          |                     |
          v                     v
   Recovery and Recourse    Audit Services
   - Evidence receipts      - Event records
   - Appeals                - Hash-chain integrity
   - Review workflow        - Verification
          
                     |
                     v
          FEDERATED TRUST LEARNING
          - Merchant-local training
          - Signed model updates
          - Sample-weighted FedAvg
          - Explicit model promotion
          - Governed immune learning
```

## Core capabilities

### 1. Cryptographic Agent Mandates

Commons implements digitally signed agent mandates using **Ed25519 public-key cryptography**.

A mandate defines the authority delegated to an AI agent, including:

- Agent identity.
- Maximum transaction amount.
- Maximum cumulative spending.
- Transaction-count restrictions.
- Permitted product categories.
- Validity period and expiry.
- Unique nonce for replay protection.
- Revocation status.

The verification workflow checks the signature and mandate conditions before a live order proceeds.

This separates **proof of authority** from **behavioural risk assessment**.

### 2. Explainable AI Risk Engine

Commons uses a machine-learning risk engine to assess agent-initiated transactions using trusted features.

The feature pipeline considers signals such as:

- Transaction amount relative to the mandate limit.
- Whether the requested category is permitted.
- Mandate age.
- Transaction frequency.
- Address changes.
- Payment retries.
- Amount relative to merchant norms.
- Shared-agent activity indicators.

The engine produces a risk probability and a decision that can be interpreted alongside the supporting evidence.

The payment policy distinguishes between:

- **CAPTURE:** Eligible for payment capture under the configured policy.
- **HOLD:** Requires further review; does not itself capture or void the payment.
- **VOID:** A payment authorization may be voided through the separately controlled execution workflow.

Risk evaluation and payment execution are deliberately separate operations.

### 3. Federated Merchant Learning

Commons explores collaborative fraud intelligence through federated learning.

The repository includes two complementary implementations:

**Demonstration federation**

The dashboard illustrates three participating merchants, their local activity, and collaborative model learning through Federated Averaging (FedAvg).

**Networked federation protocol**

The `src/federation_network/` module implements:

- A separately runnable coordinator API.
- Merchant-local training clients.
- Signed model-update submissions using HMAC-SHA256.
- Merchant identity and participant validation.
- Feature-schema and base-model-version checks.
- Timestamp validation.
- Unique nonce and duplicate-update rejection.
- Sample-weighted FedAvg aggregation.
- Candidate model artifact generation after all expected participants submit.
- Explicit model promotion rather than automatic activation.

The coordinator receives model parameters and sample counts rather than raw order rows.

**Privacy and deployment boundary:** HMAC authenticates updates but does not provide secure aggregation or differential privacy. The coordinator can inspect individual model updates. The dashboard's three-merchant illustration and in-process protocol tests do not establish that three independent merchant organizations have deployed and exchanged updates over separate networks.

### 4. Governed Immune Learning

Fraud patterns evolve, so a trust system needs a controlled adaptation mechanism.

Commons includes an immune-learning workflow that generates and evaluates candidate model updates against emerging synthetic attack families.

The governance layer supports:

- Candidate model evaluation.
- Safety-gate results.
- Explicit human approval.
- SHA-256 artifact integrity records.
- Version tracking.
- Explicit rollback to a previously approved model.
- Append-only governance event history.

Candidate evaluation does not silently replace the active model. Model promotion and rollback require an explicit approval action.

The current emerging-attack workflow uses synthetic attack data; it is not a connection to a live external fraud-intelligence feed.

### 5. PayPal Sandbox Integration

Commons integrates with the PayPal Sandbox API to demonstrate a controlled payment workflow.

The live order workflow includes:

1. Signed mandate submission.
2. Mandate verification and nonce/spending reservation.
3. PayPal Sandbox checkout-order creation.
4. Buyer approval.
5. PayPal authorization.
6. Trusted-feature extraction and live risk inference.
7. Persisted payment decision.
8. Authenticated operator-controlled execution.
9. Payment reconciliation and webhook verification.

The backend exposes distinct operations for creating, authorizing, evaluating, executing, and retrieving live orders.

Payment execution requires an operator credential. Reviewer actions require a separate reviewer credential.

A browser redirect alone is not treated as proof of payment. PayPal responses and verified webhook/reconciliation information are used as the authoritative payment evidence.

**Environment:** This project is configured for PayPal Sandbox. It is not intended to process real-money payments.

### 6. Recovery, Appeals and Auditability

Commons treats recourse as part of the trust architecture rather than an afterthought.

The recovery services support:

- Decision evidence receipts.
- Canonical evidence snapshots.
- SHA-256 evidence digests.
- Recourse records.
- Appeal submission.
- Authenticated reviewer decisions.
- Audit-event recording.
- Hash-chain integrity verification.

The evidence digest helps detect changes to a stored evidence payload. The hash chain makes modifications to the recorded event sequence detectable.

These mechanisms provide application-level integrity checks; they are not equivalent to an externally anchored immutable ledger or independent trusted timestamping service.

## Dashboard

The React dashboard presents the main Commons workflows through five sections.

| Dashboard section | Purpose |
|---|---|
| Overview | Transaction decision distribution and merchant activity |
| Order Intelligence | Order-level risk information, explanations, and agent trust context |
| Federation Network | Merchant participation and collaborative learning illustration |
| Attack Replay Lab | Synthetic attack scenarios and the live PayPal Sandbox order workflow |
| Recovery & Audit | Evidence receipts, appeals, recovery information, and audit integrity |

The dashboard clearly distinguishes synthetic demonstration scenarios from the live PayPal Sandbox workflow.

## Technology stack

| Layer | Technologies |
|---|---|
| Frontend | React 18, Vite, JavaScript, CSS |
| Backend | Python, FastAPI, Pydantic |
| Machine learning | scikit-learn, NumPy, Pandas |
| Model persistence | Joblib |
| Cryptography | Ed25519, HMAC-SHA256, SHA-256 |
| Payment integration | PayPal REST API, Sandbox |
| Local persistence | SQLite |
| Testing | Pytest |
| Federated learning | Merchant-local training, signed updates, FedAvg |

## Repository structure

```text
Commons/
│
├── config/
│   └── trusted_agents.json
│
├── data/
│   └── .gitkeep
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── LiveOrderPanel.jsx
│   │   ├── OrderGrid.jsx
│   │   ├── main.jsx
│   │   └── style.css
│   ├── index.html
│   └── package.json
│
├── models/
│   ├── federated_risk_model.joblib
│   ├── risk_model.joblib
│   ├── immune_candidate_model.joblib
│   ├── immune_model_versions.json
│   └── ...
│
├── src/
│   ├── api.py
│   ├── risk_engine.py
│   ├── mandate_issuer.py
│   ├── mandate_verification.py
│   ├── mandate_store.py
│   ├── trusted_agent_registry.py
│   ├── paypal_integration.py
│   ├── paypal_webhook_api.py
│   ├── payment_decision_service.py
│   ├── payment_reconciliation_service.py
│   ├── recovery_service.py
│   ├── appeal_service.py
│   ├── audit_service.py
│   ├── federated_train.py
│   ├── federation_network/
│   ├── immune_learning.py
│   ├── immune_evaluate.py
│   └── immune_governance.py
│
├── tests/
│   ├── test_commons_completion.py
│   ├── test_commons_services.py
│   ├── test_federation_network.py
│   ├── test_immune_governance.py
│   ├── test_mandate_service.py
│   ├── test_payment_decision_service.py
│   ├── test_paypal_webhook_service.py
│   └── ...
│
├── requirements.txt
├── pytest.ini
├── Build-Models.ps1
├── FEDERATION_AND_IMMUNE_DEPLOYMENT.md
├── FINAL_SUBMISSION_STATUS.md
└── README.md
```

The model artifacts required by the current application are included in the repository. Local runtime databases, credentials, and generated transaction records should not be committed.

## Getting started

### Prerequisites

Install the following:

- Python 3.10 or later.
- Node.js and npm.
- Git.
- A PayPal Developer account for optional Sandbox payment testing.

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/commons-agentic-commerce-trust.git
cd commons-agentic-commerce-trust
```

Replace `YOUR_USERNAME` with the GitHub account that owns the repository.

### 2. Set up the Python backend

Create and activate a virtual environment.

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Start the FastAPI application:

```powershell
uvicorn src.api:app --host 127.0.0.1 --port 8000 --reload
```

The API is available at:

```text
http://127.0.0.1:8000
```

Interactive API documentation:

```text
http://127.0.0.1:8000/docs
```

Health check:

```text
http://127.0.0.1:8000/health
```

### 3. Set up the React frontend

Open a second terminal from the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Open the local dashboard:

```text
http://127.0.0.1:5173
```

The frontend defaults to the local FastAPI address `http://127.0.0.1:8000`. For a different backend address, configure the Vite environment variable `VITE_API_URL` before building or starting the frontend.

### 4. Configure PayPal Sandbox (optional)

Create a project-root `.env` file. Never commit it.

```env
PAYPAL_CLIENT_ID=your_sandbox_client_id
PAYPAL_CLIENT_SECRET=your_sandbox_client_secret
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_WEBHOOK_ID=your_sandbox_webhook_id

COMMONS_AGENT_PRIVATE_KEY_B64=your_base64_encoded_ed25519_private_key

COMMONS_OPERATOR_TOKEN=your_long_random_operator_secret
COMMONS_REVIEWER_TOKEN=your_long_random_reviewer_secret
```

The PayPal webhook ID is required for webhook signature verification when using that workflow. Configure the webhook in your PayPal Sandbox application.

Generate separate, strong random operator and reviewer tokens. Keep all credentials on the backend.

The trusted-agent registry in `config/trusted_agents.json` contains the public key used for mandate verification. The corresponding private key must remain secret.

The live workflow requires a correctly configured trusted agent, a valid signed mandate, PayPal Sandbox credentials, and buyer approval.

The default PayPal return and cancel URLs are local development URLs. Change them to the appropriate HTTPS frontend URLs before using the workflow from another host.

### 5. Verify the installation

Run Python compilation checks:

```powershell
python -m compileall -q src tests
```

Run the automated tests:

```powershell
python -m pytest -q
```

Build the frontend:

```powershell
cd frontend
npm run build
```

The frontend build output is generated in `frontend/dist/`.

## API overview

The main FastAPI application exposes the following routes.

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Backend health check |
| GET | `/api/runtime` | Runtime and integration readiness information |
| GET | `/api/overview` | Dashboard overview |
| GET | `/api/orders` | Synthetic order catalogue |
| GET | `/api/orders/{scenario_id}` | Retrieve a demonstration scenario |
| GET | `/api/federation` | Merchant federation demonstration data |
| GET | `/api/replay/scenarios` | Available replay scenarios |
| POST | `/api/replay/{scenario_id}` | Replay a synthetic scenario |
| GET | `/api/recovery/analytics` | Recovery and appeal statistics |
| POST | `/api/recovery/recourse` | Create a recourse record |
| POST | `/api/recovery/evidence` | Create an evidence receipt |
| GET | `/api/recovery/evidence/{receipt_id}` | Retrieve an evidence receipt |
| POST | `/api/appeals` | Submit an appeal |
| GET | `/api/appeals/{appeal_id}` | Retrieve an appeal |
| POST | `/api/appeals/{appeal_id}/review` | Authenticated reviewer action |
| GET | `/api/audit/verify` | Verify audit-chain integrity |
| GET | `/api/audit/events` | Retrieve audit events |
| POST | `/api/live/orders` | Create a PayPal Sandbox checkout order |
| POST | `/api/live/orders/{transaction_id}/authorize` | Authorize a buyer-approved order |
| POST | `/api/live/orders/{transaction_id}/evaluate` | Evaluate a live transaction |
| POST | `/api/live/orders/{transaction_id}/execute` | Execute the persisted decision with operator authorization |
| GET | `/api/live/orders/{transaction_id}` | Retrieve live transaction state |

The networked federation coordinator is a separate FastAPI application, documented in `FEDERATION_AND_IMMUNE_DEPLOYMENT.md`.

## Testing and engineering verification

The project package includes automated tests for core services and security-sensitive workflows, including:

- Agent mandate verification and spending constraints.
- Nonce reservation and replay protection.
- Risk-engine and payment-decision behaviour.
- Payment reconciliation.
- PayPal webhook verification and handling.
- Recovery and appeal services.
- Audit integrity.
- Signed federated update validation and aggregation.
- Immune-learning approval and rollback controls.

**Recorded verification for the supplied project package:**

- Python compilation: passed.
- Automated test suite: 123 passed, with 4 subtests passed.
- Federation and immune-governance tests: 3 passed.

These are recorded results from the supplied engineering update. Re-run the commands above against the exact checkout you submit to reproduce the results.

## Important implementation boundaries

Commons is a hackathon research prototype. Its capabilities should be interpreted within the following boundaries:

1. The dashboard overview, merchant activity, and attack replay catalogue use synthetic demonstration data.
2. The three-merchant dashboard is illustrative. The networked federation protocol is implemented and tested, but independent merchant deployments and real cross-organization training rounds have not been demonstrated.
3. The coordinator receives individual HMAC-authenticated model updates. Secure aggregation and differential privacy are not implemented.
4. Immune learning uses synthetic emerging attack families. It is not connected to a live external fraud feed.
5. PayPal operations use Sandbox credentials. A created checkout order is not the same as an authorized or captured payment.
6. A HOLD decision does not itself capture or void funds. Payment execution is a separate authenticated operation.
7. Operator and reviewer bearer tokens are prototype controls, not a complete production identity and access-management system.
8. Local SQLite storage is intended for the demonstration environment and requires appropriate persistent storage and operational hardening for deployment.
9. Hash-based evidence and audit mechanisms provide application-level integrity verification, not an externally anchored immutable ledger.

Commons is not presented as a production-ready payment security service. Production use would require independent security assessment, hardened identity and access management, secure deployment, persistent infrastructure, monitoring, privacy analysis, and external validation.

## Future work

Potential next steps include:

- Deploying independently administered merchant nodes.
- Evaluating secure aggregation and differential privacy.
- Connecting real, consented merchant incident data.
- Strengthening identity, access control, and credential lifecycle management.
- Introducing external audit anchoring.
- Conducting independent adversarial and privacy evaluations.
- Expanding the appeal and dispute-resolution experience.
- Evaluating the system against larger and previously unseen agentic-commerce attack datasets.

## Why Commons?

Agentic commerce needs more than a fraud score.

It needs a way to verify what an agent is allowed to do, evaluate whether its behaviour is trustworthy, learn from emerging threats, control payment execution, and provide a meaningful path to challenge decisions.

Commons brings these capabilities together in one integrated prototype.

**Commons — Building trust in the age of agentic commerce.**

## License

No open-source license has been selected for this submission yet. Unless a license is added, the repository remains subject to the default copyright rules. Add a suitable license before inviting reuse or redistribution.