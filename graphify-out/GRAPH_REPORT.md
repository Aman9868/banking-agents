# Codebase Knowledge Graph Report (Graphify)

*Generated for AI Coding Agents (Cursor, Claude Code, Antigravity, Copilot, Codex, Windsurf, Aider)*

---

## 1. Executive Architecture Summary
The **AI Banking Agent** platform is a multi-agent hierarchical state machine built on **LangGraph**. 
- **Total Mapped Files**: 82
- **Total Dependency Relationships**: 174
- **Root Orchestrator**: `agents/supervisor/graph.py`

---

## 2. Identified "God Nodes" (Core Architectural Hubs)
> **WARNING FOR AI AGENTS**: Modifying any of these core nodes carries a high blast radius. Always check dependent modules before refactoring!

- **`database/repositories/banking_repo.py`** (Degree: 23 | In: 22, Out: 1)
  - *Role*: Repository for secure, parameterized data access on Customers, Accounts, and Transactions.
  - *Key Symbols*: BankingRepository, __init__, get_customer_by_external_id, get_accounts_by_customer_id, get_account_by_number, get_beneficiaries
- **`gateway/tool_gateway/gateway.py`** (Degree: 21 | In: 7, Out: 14)
  - *Role*: Central Tool Gateway enforcing RBAC, Idempotency, and Audit logging across all banking capabilities.
  - *Key Symbols*: ToolGateway, execute_tool
- **`agents/supervisor/graph.py`** (Degree: 19 | In: 5, Out: 14)
  - *Role*: Master Banking Supervisor StateGraph with 6-Agent Orchestration & Context Switching.
  - *Key Symbols*: supervisor_router_node, supervisor_dispatch
- **`database/connection.py`** (Degree: 17 | In: 16, Out: 1)
  - *Role*: Database connection engine and session management using SQLAlchemy Asyncio.
  - *Key Symbols*: get_db_session
- **`apps/api/main.py`** (Degree: 14 | In: 6, Out: 8)
  - *Role*: Main FastAPI Application for Enterprise AI Banking Agent.
  - *Key Symbols*: lifespan, global_exception_handler, serve_chat_ui
- **`security/pii.py`** (Degree: 12 | In: 12, Out: 0)
  - *Role*: PII (Personally Identifiable Information) masking and sanitization module.
  - *Key Symbols*: mask_card_number, mask_account_number, mask_email, mask_phone, sanitize_pii
- **`database/init_db.py`** (Degree: 12 | In: 10, Out: 2)
  - *Role*: Database initialization and mock seed data script.
  - *Key Symbols*: init_database, seed_mock_data, main
- **`tools/base.py`** (Degree: 10 | In: 10, Out: 0)
  - *Role*: Base classes and schemas for banking tools.
  - *Key Symbols*: ToolResult

---

## 3. Subgraph Communities & Responsibilities

### Community: `agents` (15 files)
- **`agents/supervisor/graph.py`**: Master Banking Supervisor StateGraph with 6-Agent Orchestration & Context Switching. *(Symbols: 2)*
- **`agents/transfer/graph.py`**: Controlled Money Transfer Subgraph with Policy Engine, Fraud Scoring, and HITL Checkpoints. *(Symbols: 9)*
- **`agents/state.py`**: Global LangGraph State definitions for Multi-Agent Enterprise Banking (Phases 1-7). *(Symbols: 8)*
- **`agents/card/graph.py`**: Card Operations and Security Subgraph. *(Symbols: 1)*
- **`agents/insights/graph.py`**: Personal Financial Management (PFM) and Insights Subgraph. *(Symbols: 1)*

### Community: `apps` (10 files)
- **`apps/api/main.py`**: Main FastAPI Application for Enterprise AI Banking Agent. *(Symbols: 3)*
- **`apps/api/routes/chat.py`**: Chat conversation and ChatGPT-style session history API endpoints. *(Symbols: 8)*
- **`apps/api/config.py`**: Application configuration using Pydantic Settings. *(Symbols: 1)*
- **`apps/api/routes/admin.py`**: Admin & Bank Officer HITL (Human-in-the-Loop) Review API. *(Symbols: 2)*
- **`apps/api/routes/health.py`**: Health and readiness check endpoints. *(Symbols: 2)*

### Community: `database` (7 files)
- **`database/repositories/banking_repo.py`**: Repository for secure, parameterized data access on Customers, Accounts, and Transactions. *(Symbols: 33)*
- **`database/connection.py`**: Database connection engine and session management using SQLAlchemy Asyncio. *(Symbols: 1)*
- **`database/init_db.py`**: Database initialization and mock seed data script. *(Symbols: 3)*
- **`database/models/banking.py`**: Enterprise Banking Domain Models. *(Symbols: 15)*
- **`database/__init__.py`**: Module database/__init__.py *(Symbols: 0)*

### Community: `gateway` (9 files)
- **`gateway/tool_gateway/gateway.py`**: Central Tool Gateway enforcing RBAC, Idempotency, and Audit logging across all banking capabilities. *(Symbols: 2)*
- **`gateway/tool_gateway/permissions.py`**: Agent Identity and Tool Permission Engine (RBAC). *(Symbols: 3)*
- **`gateway/rate_limit/limiter.py`**: Production-grade Redis sliding-window rate limiter middleware. *(Symbols: 7)*
- **`gateway/tool_gateway/idempotency.py`**: Distributed idempotency manager for financial operations using Redis. *(Symbols: 8)*
- **`gateway/llm/router.py`**: Production-grade Intent Classification, Sub-Intent Resolution, and Entity Extraction Engine. *(Symbols: 9)*

### Community: `policies` (2 files)
- **`policies/transfer.py`**: Deterministic Transfer Policy Engine. *(Symbols: 4)*
- **`policies/__init__.py`**: Module policies/__init__.py *(Symbols: 0)*

### Community: `security` (6 files)
- **`security/pii.py`**: PII (Personally Identifiable Information) masking and sanitization module. *(Symbols: 5)*
- **`security/guardrails_engine.py`**: Enterprise Guardrails AI Engine for Input & Output Validation. *(Symbols: 10)*
- **`security/tracing.py`**: End-to-end request correlation and distributed tracing middleware. *(Symbols: 2)*
- **`security/headers.py`**: HTTP Security Headers Middleware for Enterprise Banking API. *(Symbols: 2)*
- **`security/__init__.py`**: Module security/__init__.py *(Symbols: 0)*

### Community: `services` (6 files)
- **`services/cache/cache_engine.py`**: Redis-backed multi-tier semantic and query caching engine with transactional invalidation. *(Symbols: 10)*
- **`services/fraud/engine.py`**: Deterministic Fraud Detection & Risk Scoring Engine. *(Symbols: 3)*
- **`services/resilience/circuit_breaker.py`**: Circuit Breaker pattern for external banking integrations and LLM resilience. *(Symbols: 7)*
- **`services/__init__.py`**: Module services/__init__.py *(Symbols: 0)*
- **`services/core_banking/__init__.py`**: Module services/core_banking/__init__.py *(Symbols: 0)*

### Community: `tests` (16 files)
- **`tests/unit/test_phase567_tools.py`**: Unit tests for Cards, Loans, Bill Payments, and Knowledge RAG tools. *(Symbols: 7)*
- **`tests/unit/test_insights_and_genui.py`**: Test suite for Next-Gen Capabilities: PFM Insights, Generative UI Widgets, and Guardian. *(Symbols: 7)*
- **`tests/unit/test_cache_and_memory.py`**: Test suite for Redis Query Cache, Entity Memory, Rate Limiting, and Resilience. *(Symbols: 6)*
- **`tests/unit/test_new_user_onboarding.py`**: Tests for New User Onboarding & Persona Switching. *(Symbols: 3)*
- **`tests/unit/test_production_intent_router.py`**: Tests for Production-Grade Intent Classification, Sub-Intents, Negation, Typo Resilience, and Semantic Cache. *(Symbols: 7)*

### Community: `tools` (11 files)
- **`tools/base.py`**: Base classes and schemas for banking tools. *(Symbols: 1)*
- **`tools/payments.py`**: Bill Payments and UPI banking tools. *(Symbols: 4)*
- **`tools/transfers.py`**: Transfer execution banking tools. *(Symbols: 1)*
- **`tools/cards.py`**: Card operations banking tools. *(Symbols: 5)*
- **`tools/loans.py`**: Loan calculation, eligibility, and application banking tools. *(Symbols: 5)*


---

## 4. Multi-Agent Dispatch Topology
The system dispatches through `agents/supervisor/graph.py`:
1. **`account_subgraph`** (`agents/account/graph.py`): KYC slot collection, age validation (18+), AML screening, HITL approval.
2. **`transfer_subgraph`** (`agents/transfer/graph.py`): Entity resolution, parallel fraud + AML + ledger check, 2-phase confirmation.
3. **`card_subgraph`** (`agents/card/graph.py`): Instant card freeze/unfreeze, limit adjustments, stolen replacement.
4. **`loan_subgraph`** (`agents/loan/graph.py`): Mathematical EMI calculation, DTI threshold verification, loan application.
5. **`payment_subgraph`** (`agents/payment/graph.py`): Biller directory, bill fetching, UPI VPA verification, settlement.
6. **`support_subgraph`** (`agents/support/graph.py`): Decline reason investigation, policy RAG, ticket generation.
7. **`insights_subgraph`** (`agents/insights/graph.py`): Spending analytics, categorization, trend alerts.

---

## 5. Blast Radius & Change Guidance for AI Agents
- **Changing Session State**: Modify `agents/state.py` carefully. All 7 subgraphs share `BankingSessionState`.
- **Modifying Intent Routing**: Test against `tests/unit/test_production_intent_router.py`.
- **Database Schema Changes**: Ensure both `database/models/banking.py` and `database/repositories/banking_repo.py` are kept in lockstep.
- **Executing Transfers or Payments**: Always enforce two-phase confirmation and pass through `gateway/tool_gateway/gateway.py` for idempotency and audit logs.
