# AGENTS.md — AI Agent Guide & Codebase Architecture

> **Notice for AI Agents** (Cursor, Claude Code, Antigravity, GitHub Copilot, Codex, Windsurf, Aider):
> This repository is a production-grade conversational banking platform built on **LangGraph**, **FastAPI**, **PostgreSQL**, **Redis**, and **ChatGroq**. Read this document to understand the architectural topology, conventions, state structures, and blast radius before modifying any code.
> 
> A queryable structural graph is also available in `graphify-out/graph.json` and `graphify-out/GRAPH_REPORT.md`.

---

## 1. Guiding Core Principles
1. **Deterministic Core Truth**: The LLM is an orchestration & conversational translation layer. Financial state changes (money transfers, card locks, loan approvals) MUST execute through deterministic tools with idempotency and audit logs.
2. **Two-Phase Commit for Actions**: High-risk financial operations (Transfers, Bill Payments, Card Freezes) require explicit user confirmation (`Yes`/`No`) before calling downstream settlement APIs.
3. **Strict Validation**: Account opening, KYC, and entity resolution use strict zero-tolerance validators (no placeholders like "na", adult 18+ enforcement, strict email regex).

---

## 2. High-Connectivity "God Nodes" (High Blast Radius)
Modifying any of these core files impacts multiple modules across the repository:

| File | Role | Blast Radius / Dependent Modules |
| :--- | :--- | :--- |
| [`agents/state.py`](agents/state.py) | Master `BankingSessionState` typed dictionary | **CRITICAL**: Imported by all 7 subgraphs and supervisor. |
| [`agents/supervisor/graph.py`](agents/supervisor/graph.py) | Master StateGraph orchestrator and router node | Dispatches requests to all subgraphs; handles interruptions and context switching. |
| [`gateway/llm/router.py`](gateway/llm/router.py) | Pydantic structured intent & entity router | Classifies customer intent, sub-intent, and extracts entities (amount, beneficiary, biller). |
| [`database/repositories/banking_repo.py`](database/repositories/banking_repo.py) | Async SQLAlchemy banking data access layer | Customer profiles, accounts, ledgers, beneficiaries, cards, loans, bills. |
| [`gateway/tool_gateway/gateway.py`](gateway/tool_gateway/gateway.py) | Tool gateway with RBAC, idempotency & audit logging | All tool invocations must pass through this security perimeter. |
| [`apps/api/routes/chat.py`](apps/api/routes/chat.py) | Primary `/api/v1/chat` FastAPI endpoint | Manages thread persistence, checkpointers, and chat UI responses. |

---

## 3. The 7 Autonomous LangGraph Subgraphs

The supervisor at [`agents/supervisor/graph.py`](agents/supervisor/graph.py) compiles 7 specialized state machines:

```
                  ┌──────────────────────┐
                  │ supervisor_router    │
                  └──────────┬───────────┘
                             │
       ┌──────────┬──────────┼──────────┬──────────┬──────────┬──────────┐
       ▼          ▼          ▼          ▼          ▼          ▼          ▼
    Account    Transfer    Cards      Loans     Payments   Support   Insights
    Subgraph   Subgraph   Subgraph   Subgraph   Subgraph   Subgraph  Subgraph
```

1. **Account Opening Subgraph** ([`agents/account/graph.py`](agents/account/graph.py)):
   - State machine: `collect_profile` ➔ `kyc_aml` ➔ `aml_hitl` (interrupt) ➔ `create_account`
   - Strict validators in [`agents/account/validators.py`](agents/account/validators.py): Name, DOB (18+), Email.
2. **Transfer Subgraph** ([`agents/transfer/graph.py`](agents/transfer/graph.py)):
   - State machine: `resolve_entities` ➔ Fan-out: (`parallel_fraud_scoring`, `parallel_aml_screening`, `parallel_ledger_verification`) ➔ `policy_aggregator` ➔ `transfer_hitl` ➔ `execute_transfer`.
   - Requires explicit confirmation (`Yes`/`No`) before execution.
3. **Card Management Subgraph** ([`agents/card/graph.py`](agents/card/graph.py)):
   - Instant card freeze/unfreeze, limit changes, lost card reissuance.
4. **Loans & Advisory Subgraph** ([`agents/loan/graph.py`](agents/loan/graph.py)):
   - Deterministic EMI calculation ($E = P \cdot r \cdot \frac{(1+r)^n}{(1+r)^n - 1}$) and Debt-to-Income (DTI) eligibility checks.
5. **Bill Payments Subgraph** ([`agents/payment/graph.py`](agents/payment/graph.py)):
   - Utility bill fetching (electricity, broadband), UPI VPA resolution, confirmation, and settlement.
6. **Support & Grounded RAG Subgraph** ([`agents/support/graph.py`](agents/support/graph.py)):
   - Decline code diagnosis (`TXN-10091`), official policy RAG search, ticket escalation.
7. **Insights Subgraph** ([`agents/insights/graph.py`](agents/insights/graph.py)):
   - Spending categorizations, cashflow trends, and budget alerts.

---

## 4. Repository Directory Layout

```
banking-agent/
├── AGENTS.md                  # <-- THIS FILE (Universal AI agent entrypoint)
├── llms.txt                   # LLM discovery index (llmstxt.org)
├── graphify-out/              # Graphify Knowledge Graph artifacts
│   ├── graph.json             # Persistent machine-readable knowledge graph
│   ├── GRAPH_REPORT.md        # God nodes & community report
│   └── graph.html             # Interactive D3 force-directed visualizer
├── docs/graphs/               # LangGraph visual PNG diagrams
│   ├── banking_graph_full.png # Full expanded multi-agent graph (xray=True)
│   ├── supervisor_overview.png# High-level collapsed router view (xray=False)
│   └── *_subgraph.png         # Individual subgraph state machines
├── scripts/
│   ├── build_graphify.py      # Regenerates graphify-out artifacts
│   └── generate_graphs.py     # Regenerates LangGraph mermaid PNGs
├── agents/                    # LangGraph agents & subgraphs
│   ├── supervisor/            # Master router & dispatcher
│   ├── account/               # KYC & account creation state machine
│   ├── transfer/              # Transfer flow with fraud fan-out & HITL
│   ├── card/                  # Card controls & security
│   ├── loan/                  # Loan calculation & applications
│   ├── payment/               # Bill pay & UPI
│   ├── support/               # RAG FAQs & dispute analysis
│   ├── insights/              # Spending intelligence
│   └── state.py               # Shared session state definitions
├── apps/api/                  # FastAPI web server and routes
│   ├── routes/chat.py         # Main chat execution loop
│   └── static/index.html      # GenUI rich chat client
├── database/                  # SQLAlchemy models, SQLite/Postgres connection, seed data
├── gateway/                   # LLM Router & Tool Gateway (RBAC, Idempotency)
├── policies/                  # Banking limits & transfer policy rules
├── security/                  # Guardrails, PII masking, circuit breakers
└── tests/                     # Automated unit and integration test suite
```

---

## 5. Development & Verification Commands

### Run Application Locally
```bash
# Start FastAPI backend
uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
```

### Run Tests
```bash
# Run complete test suite
pytest -v tests/

# Run specific domain test suite
pytest -v tests/unit/test_account_validation.py
pytest -v tests/unit/test_production_intent_router.py
pytest -v tests/graph/test_graphs.py
```

### Regenerate Knowledge Graph & Mermaid Architecture
```bash
# Rebuild Graphify JSON, report, and HTML visualizer:
python scripts/build_graphify.py

# Rebuild all LangGraph PNG diagrams in docs/graphs/:
python scripts/generate_graphs.py
```

---

## 6. Coding Conventions for AI Agents
1. **Never bypass `tool_gateway`**: Direct database mutation for transactions without going through `gateway/tool_gateway/gateway.py` is strictly prohibited.
2. **Preserve PII Masking**: Never return raw bank account numbers or card numbers in LLM responses. Use `security.pii.mask_account_number`.
3. **Session Checkpointing**: LangGraph uses thread-scoped checkpointers (`MemorySaver` or `AsyncPostgresSaver`). Keep message structures serializable.

