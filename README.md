# AI Banking Agent — Enterprise LangGraph Operating Layer

An enterprise-grade, conversational banking platform built with **LangGraph**, **FastAPI**, **PostgreSQL**, **Redis**, and **ChatGroq**.

> **Guiding Principle**: *"Let the customer do banking through conversation, while deterministic banking systems remain the absolute source of truth."*

---

## 🖥️ NovaBank Interactive AI Chatbot UI

| NovaBank Conversational Portal | Customer Persona & Guest Onboarding Switcher |
| :---: | :---: |
| ![NovaBank AI Interface](docs/screenshots/ui_chat_interface.png) | ![Customer Persona Switcher](docs/screenshots/persona_switcher.png) |

The enterprise banking portal features:
- **Interactive Generative UI (GenUI)**: Real-time dynamic widgets (Account Cards, EMI Sliders, Transaction Receipts, Spending Breakdowns).
- **Multi-Agent Conversational Routing**: Seamless context switching between account opening, transfers, cards, loans, payments, and support.
- **Role-Based & Guest Access**: One-click instant onboarding for new guest prospects alongside authenticated customer sessions.

---

## 💬 Live Chat Samples & Multi-Agent Interactions

### 1. Conversational KYC & Instant Savings Account Opening
```markdown
👤 User: I want to open a new savings account with NovaBank
🤖 Assistant: Absolutely! I can help you open a new bank account. May I have your full name?
👤 User: rajuu
🤖 Assistant: Thanks, Raju. What is your date of birth?
👤 User: 07-10-1997
🤖 Assistant: What email address would you like to use for your account?
👤 User: raju@example.com
🤖 Assistant: Congratulations Raju! Your KYC is complete. Your SAVINGS account SB64237377 has been successfully opened.

┌─────────────────────────────────────────────────────────────┐
│  NovaBank Digital Account Passbook                          │
│  ACTIVE & KYC VERIFIED                                      │
│  Account Number: SB64237377        Account Holder: Raju     │
│  Customer ID:    CUST-8536         Account Type:   SAVINGS  │
│  IFSC Code:      NOVA0001001       Branch: Digital Branch   │
│  Balance:        ₹0.00                                      │
└─────────────────────────────────────────────────────────────┘
```

### 2. Controlled Money Transfer with Parallel Fraud Scoring & Two-Phase Confirmation
```markdown
👤 User: Transfer ₹5,000 to Rahul
🤖 Assistant: Transfer ₹5,000.00 to Rahul Sharma (Account: ****3456).
   Fraud Score: 0.05 (LOW RISK).
   Daily Transfer Limit Available: ₹95,000.00.
   Please reply 'Yes' to confirm the transfer, or 'No' to cancel.

👤 User: Yes
🤖 Assistant: Transfer initiated! ₹5,000.00 sent successfully to Rahul Sharma.
   Transaction Reference: TXN-94821032
   New Available Balance: ₹95,000.00.
```

### 3. Mid-Flow Interruption & Context Switching
```markdown
👤 User: I want to open a savings account
🤖 Assistant: Absolutely! What is your full legal name?
👤 User: Amanpreet Singh
🤖 Assistant: Thanks Amanpreet! What is your date of birth?
👤 User: Before that, what's my current balance?
🤖 Assistant: Your current balance for Savings account ****1234 is ₹100,000.00.

   Now, continuing with your account application: What is your date of birth?
```

### 4. Card Security & Instant Lock Safeguard
```markdown
👤 User: I lost my debit card, please freeze it right now!
🤖 Assistant: Your NovaBank Platinum Debit Card ending in ****7821 has been INSTANTLY FROZEN.
   All online, POS, and ATM transactions are temporarily blocked.
   Would you like me to order a replacement card to your registered address?
```

### 5. Loan Advisory & Mathematical EMI Calculation
```markdown
👤 User: What is the EMI for a 5 lakh loan for 3 years?
🤖 Assistant: For a Personal Loan of ₹5,00,000 over 36 months at 10.50% annual interest:
   • Monthly EMI: ₹16,254.67
   • Total Interest: ₹85,168.00
   • Total Payable: ₹5,85,168.00
   Would you like to check your eligibility or proceed with an application?
```

---

## 🗺️ Master Multi-Agent Architecture (LangGraph)

Below is the complete multi-agent execution graph across all 7 autonomous subgraphs:

![LangGraph Master Multi-Agent Architecture](docs/graphs/banking_graph_full.png)

> **For AI Coding Assistants**: See [`AGENTS.md`](AGENTS.md) and [`graphify-out/GRAPH_REPORT.md`](graphify-out/GRAPH_REPORT.md) for the codebase AST knowledge graph and blast-radius rules.

---

## Architecture Overview

```
                         CUSTOMER
                            │
                            ▼
                    ┌─────────────────┐
                    │ Web / Mobile UI │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   API Gateway   │
                    │ Security / WAF  │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Banking Chat API│
                    │  FastAPI (8000) │
                    └────────┬────────┘
                             │
                             ▼
              ┌───────────────────────────┐
              │     LLM GATEWAY           │
              │ Routing / Groq / Fallback │
              └────────────┬──────────────┘
                             │
                             ▼
              ┌───────────────────────────┐
              │     LANGGRAPH             │
              │    Banking Supervisor     │
              └────────────┬──────────────┘
                           │
       ┌──────────┬────────┼─────────┬──────────┬─────────┐
       ▼          ▼        ▼         ▼          ▼         ▼
    Account    Transfer  Cards     Loans     Payments  Support
    Subgraph   Subgraph  Subgraph  Subgraph  Subgraph  Subgraph
       │          │        │         │          │         │
       ▼          ▼        ▼         ▼          ▼         ▼
     KYC/AML    Fraud    Security   EMI/DTI    Billers   RAG FAQ
       │          │        │         │          │         │
       ▼          ▼        │         │          ▼         ▼
      HITL       HITL      │         │       Confirm   Tickets
  (interrupt) (interrupt)  │         │          │         │
       │          │        │         │          │         │
       └──────────┴────────┴────┬────┴──────────┴─────────┘
                                ▼
                          TOOL GATEWAY
                 (RBAC + Idempotency + Audit)
                                │
          ┌─────────────┬───────┼───────┬─────────────┐
          ▼             ▼       ▼       ▼             ▼
       Accounts     Transfers Cards   Loans       Payments
          │             │       │       │             │
          └─────────────┴───────┼───────┴─────────────┘
                                ▼
                     PostgreSQL Database
                                │
               ┌────────────────┼────────────────┐
               ▼                ▼                ▼
          Business DB         Redis      AsyncPostgresSaver
          (pgdb:5432)        (Cache)        (Checkpointer)
```

---

## 6 Autonomous Subgraphs Implemented

1. **Account Opening Subgraph** ([`agents/account/graph.py`](agents/account/graph.py)):
   - Multi-turn conversational slot filling (`name` ➔ `dob` ➔ `email` ➔ `account_type`).
   - KYC validation and AML watchlist screening with compliance officer `interrupt()` pause.
2. **Controlled Money Transfer Subgraph** ([`agents/transfer/graph.py`](agents/transfer/graph.py)):
   - Resolves source accounts and registered beneficiaries.
   - Computes deterministic Fraud Score (velocity, cooling-off periods).
   - Enforces Transfer Policy rules (daily limits, step-up auth, HITL escalation).
   - Mandatory explicit two-phase confirmation (`Yes`/`No`) before execution with idempotency key.
3. **Cards Operations & Security Subgraph** ([`agents/card/graph.py`](agents/card/graph.py)):
   - Emergency freeze (`"Freeze my debit card"`, `"My card was stolen"`).
   - Unfreeze card (`"Unfreeze my card"`).
   - Configure online/ATM daily spending limits.
   - Replace lost/stolen card with instant blocking and new card dispatch.
4. **Loans & Advisory Subgraph** ([`agents/loan/graph.py`](agents/loan/graph.py)):
   - Deterministic mathematical EMI calculation ($E = P \cdot r \cdot \frac{(1+r)^n}{(1+r)^n - 1}$).
   - Debt-to-Income (DTI) ratio eligibility check against 50% income threshold.
   - Multi-step loan application submission to Core Banking.
5. **Bill Payments & UPI Subgraph** ([`agents/payment/graph.py`](agents/payment/graph.py)):
   - Utility bill fetching (Tata Power, Airtel Broadband) and credit card bills.
   - UPI handle format validation and VPA resolution (`rahul@okaxis`).
   - Explicit two-phase payment confirmation and ledger settlement with idempotency.
6. **Support & Grounded RAG Subgraph** ([`agents/support/graph.py`](agents/support/graph.py)):
   - Transaction decline reason investigation (`TXN-10091` ➔ customer-friendly translation).
   - Grounded RAG search over official bank policies, interest rates, and fees.
   - Formal customer support ticket escalation.

---

## Quickstart

### 1. Prerequisites
- Python 3.12+
- Docker (PostgreSQL & Redis)

### 2. Environment Setup
```bash
cd /home/itsam/Projects/banking-agent
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt langgraph-checkpoint-postgres
```

### 3. Initialize Database & Seed
```bash
python -m database.init_db
```

### 4. Run Automated Test Suite
```bash
pytest -v tests/
```
All **31 automated tests** pass out-of-the-box in under 6 seconds!

### 5. Run FastAPI Application
```bash
uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
```
Interactive API documentation: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).
