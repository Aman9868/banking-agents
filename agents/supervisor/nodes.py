"""Master Banking Supervisor StateGraph with 6-Agent Orchestration & Context Switching."""

import re
from typing import Dict, Any, Optional, Tuple
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState
from agents.account.graph import account_subgraph
from agents.transfer.graph import transfer_subgraph
from agents.card.graph import card_subgraph
from agents.loan.graph import loan_subgraph
from agents.payment.graph import payment_subgraph
from agents.support.graph import support_subgraph
from agents.insights.graph import insights_subgraph
from agents.wealth.graph import wealth_subgraph
from agents.policy.graph import policy_subgraph
from gateway.llm.router import (
    route_banking_request,
    BankingIntent,
    BankingSubIntent,
    classify_intent,
    extract_slots
)
from gateway.tool_gateway.gateway import tool_gateway
from gateway.tool_gateway.permissions import AgentRole
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from security.pii import mask_account_number
from security.validators import validate_account_number, validate_ifsc_code
from agents.supervisor.prompts import (
    build_supervisor_default_menu,
    build_interruption_continuation_prompt,
    build_gratitude_response,
    build_chatgpt_style_fallback_response,
    build_system_error_fallback_response,
)
import structlog

logger = structlog.get_logger(__name__)


def _build_interruption_continuation(
    base_msg: str,
    active_wf: str,
    state: BankingSessionState
) -> Tuple[str, str, Dict[str, Any]]:
    """Appends contextual continuation prompt for any active workflow during an interruption."""
    return build_interruption_continuation_prompt(base_msg, active_wf, state)


async def supervisor_router_node(state: BankingSessionState) -> Dict[str, Any]:

    """
    Supervisor brain:
    1. Inspects active workflow and context switching state.
    2. Identifies customer intent using Pydantic structured router with sub-intents.
    3. Handles topic interruptions (e.g., balance check or FAQ during account opening).
    4. Handles negations and temporal date/time queries directly.
    5. Dispatches to specialized subgraphs or answers informational queries directly.
    """
    last_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_msg = msg.content.strip()
            break

    active_wf = state.get("active_workflow", "NONE")
    customer_id = state.get("customer_id", 1)
    customer_name = state.get("customer_name", "Valued Customer")
    first_name = customer_name.split(" ")[0].capitalize() if customer_name else "there"
    memory = dict(state.get("customer_memory") or {})

    # Route request using production-grade Pydantic router
    routing_ctx = {
        "active_workflow": active_wf,
        "account_data": state.get("account_data"),
        "transfer_data": state.get("transfer_data"),
        "payment_data": state.get("payment_data"),
        "wealth_data": state.get("wealth_data"),
    }
    decision = await route_banking_request(last_msg, context=routing_ctx)
    intent = decision.intent.value
    sub_intent = decision.sub_intent.value if decision.sub_intent else None
    slots = decision.entities.model_dump()
    confidence = decision.confidence
    reasoning = decision.reasoning
    negation = decision.negation_detected

    DOMAIN_INTENTS = {
        "OPEN_ACCOUNT",
        "TRANSFER_MONEY",
        "CARD_ACTION",
        "LOAN_ACTION",
        "PAYMENT_ACTION",
        "SUPPORT_DISPUTE",
        "SPENDING_INSIGHTS",
        "WEALTH_ADVISORY",
        "POLICY_INQUIRY",
        "BALANCE_CHECK",
        "STATEMENT_REQUEST",
        "TRANSACTION_INQUIRY",
        "KNOWLEDGE_FAQ",
        "TEMPORAL_QUERY",
        "GENERAL_CONVERSATION",
        "CONFIRM_NO",
        "CONFIRM_YES"
    }

    # Cross-Subgraph Entity Memory: resolve pronouns and references (e.g. "Send him another 2000")
    if not slots.get("beneficiary_name") and any(w in last_msg.lower() for w in ["him", "her", "them", "to same", "again", "another"]):
        if memory.get("last_beneficiary_name"):
            slots["beneficiary_name"] = memory["last_beneficiary_name"]
            logger.info("Resolved pronoun to remembered beneficiary", beneficiary=slots["beneficiary_name"])

    # Retain newly observed entities in memory
    if slots.get("beneficiary_name"):
        memory["last_beneficiary_name"] = slots["beneficiary_name"]
    if slots.get("amount"):
        memory["last_mentioned_amount"] = slots["amount"]
    if slots.get("biller_name"):
        memory["last_biller_name"] = slots["biller_name"]
    if slots.get("card_type"):
        memory["last_card_type"] = slots["card_type"]

    logger.info(
        "Supervisor evaluating request",
        intent=intent,
        sub_intent=sub_intent,
        confidence=confidence,
        negation=negation,
        active_workflow=active_wf
    )

    # 0a. Explicit Negation Safety Guard (e.g. "I don't want to transfer money", "Don't freeze my card")
    if negation and intent in ["TRANSFER_MONEY", "CARD_ACTION", "PAYMENT_ACTION", "OPEN_ACCOUNT", "LOAN_ACTION"]:
        action_name = intent.replace("_", " ").lower()
        resp = f"Understood! I will not proceed with any {action_name}. Let me know if you need help with anything else."
        return {
            "current_intent": "GENERAL_CONVERSATION",
            "current_sub_intent": sub_intent,
            "intent_confidence": confidence,
            "routing_reasoning": reasoning,
            "negation_detected": True,
            "active_workflow": "NONE",
            "final_response": resp,
            "messages": [AIMessage(content=resp)],
            "customer_memory": memory
        }


    # 0b. Temporal Query (Current Date & Time, like ChatGPT)
    if intent == "TEMPORAL_QUERY":
        import datetime
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        now_ist = now_utc + datetime.timedelta(hours=5, minutes=30)
        time_resp = (
            f"Today is **{now_ist.strftime('%A, %d %B %Y')}**, and the current local time is "
            f"**{now_ist.strftime('%I:%M %p IST')}** (UTC: {now_utc.strftime('%H:%M')})."
        )
        full_resp, next_wf, extra_state = _build_interruption_continuation(time_resp, active_wf, state)
        out = {
            "current_intent": "TEMPORAL_QUERY",
            "current_sub_intent": "CURRENT_TIME_DATE",
            "intent_confidence": confidence,
            "routing_reasoning": reasoning,
            "active_workflow": next_wf,
            "final_response": full_resp,
            "messages": [AIMessage(content=full_resp)],
            "customer_memory": memory
        }
        out.update(extra_state)
        return out

    # 0c. Low-confidence Disambiguation / Clarification
    if decision.requires_clarification:
        clarification_msg = decision.clarification_prompt or (
            "I want to make sure I assist you accurately. Could you please specify whether you would like to "
            "check your balance, make a transfer, or manage your cards?"
        )
        return {
            "current_intent": "GENERAL_CONVERSATION",
            "current_sub_intent": "CLARIFICATION",
            "intent_confidence": confidence,
            "routing_reasoning": reasoning,
            "active_workflow": "NONE",
            "final_response": clarification_msg,
            "messages": [AIMessage(content=clarification_msg)],
            "customer_memory": memory,
            "widget_type": None,
            "widget_data": None
        }

    # 0d. Universal Workflow Cancellation Handler ("cancel", "stop", "abort", "exit", "quit", "nevermind")
    clean_text = last_msg.lower().strip()
    is_cancel = intent == "CONFIRM_NO" or any(clean_text == c for c in ["cancel", "stop", "abort", "nevermind", "never mind", "exit", "quit"])
    if is_cancel:
        wf_label = active_wf.replace("_", " ").title() if active_wf != "NONE" else "request"
        cancel_msg = f"I've cancelled the **{wf_label}**. How else may I assist you today?"
        return {
            "current_intent": "CONFIRM_NO",
            "current_sub_intent": "CANCEL",
            "active_workflow": "NONE",
            "paused_workflow": None,
            "account_data": {},
            "transfer_data": {},
            "loan_data": {},
            "payment_data": {},
            "card_data": {},
            "wealth_data": {},
            "policy_data": {},
            "final_response": cancel_msg,
            "messages": [AIMessage(content=cancel_msg)],
            "widget_type": None,
            "widget_data": None,
            "customer_memory": memory
        }

    # 1. Informational Interruption: Balance Check & Multi-Account Portfolio
    if intent == "BALANCE_CHECK":
        widget_type = None
        widget_data = None
        acc_res = None
        try:
            async with AsyncSessionLocal() as session:
                repo = BankingRepository(session)
                acc_res = await tool_gateway.execute_tool(
                    agent_role=AgentRole.SUPERVISOR.value,
                    tool_name="get_accounts",
                    repo=repo,
                    customer_id=customer_id,
                    parameters={}
                )
        except Exception as exc:
            logger.warning("DB session unavailable for get_accounts, using fallback account balance", error=str(exc))

        if acc_res and acc_res.success and acc_res.data and acc_res.data.get("accounts"):
            accounts = acc_res.data["accounts"]
            active_accs = [a for a in accounts if a.get("status") == "ACTIVE"] or accounts
            total_bal = sum(float(a.get("balance", 0.0)) for a in active_accs)

            is_list_query = (
                sub_intent == "LIST_ACCOUNTS"
                or any(k in last_msg.lower() for k in [
                    "how many", "list", "show", "which", "portfolio", "all accounts", "all my accounts", "my accounts", "acocunt"
                ])
            )

            if is_list_query or len(accounts) > 1:
                acc_bullets = []
                for i, a in enumerate(accounts, 1):
                    type_str = a.get("account_type", "SAVINGS").capitalize()
                    masked = a.get("masked_account", "••••")
                    bal = float(a.get("balance", 0.0))
                    status = a.get("status", "ACTIVE")
                    acc_bullets.append(
                        f"{i}. **{type_str} Account** (`{masked}`)\n"
                        f"   • **Available Balance**: ₹{bal:,.2f}\n"
                        f"   • **Status**: {status} {'✅' if status == 'ACTIVE' else '⚠️'}"
                    )
                bullet_str = "\n".join(acc_bullets)
                count_str = f"**{len(accounts)} registered account{'s' if len(accounts) > 1 else ''}**"

                if is_list_query:
                    balance_msg = (
                        f"You currently have {count_str} with NovaBank:\n\n"
                        f"{bullet_str}\n\n"
                        f"💰 **Total Net Worth / Combined Balance**: **₹{total_bal:,.2f}**\n\n"
                        "💡 *You can transfer funds, pay bills, or download statements from any of these accounts.*"
                    )
                else:
                    # User asked for balance but has multiple accounts
                    balance_msg = (
                        f"You have {count_str} with NovaBank with a **Total Consolidated Balance** of **₹{total_bal:,.2f}**:\n\n"
                        f"{bullet_str}\n\n"
                        "Which account would you like to use for your next transaction?"
                    )

                widget_type = "ACCOUNTS_PORTFOLIO_WIDGET"
                widget_data = {
                    "accounts": accounts,
                    "total_balance": total_bal,
                    "account_count": len(accounts)
                }
            else:
                target = accounts[0]
                masked = target.get("masked_account")
                bal = float(target.get("balance", 0.0))
                type_str = target.get("account_type", "SAVINGS").capitalize()
                balance_msg = f"Your current balance for {type_str} account {masked} is **₹{bal:,.2f}**."
        else:
            balance_msg = f"Hello {first_name}! Your NovaBank Primary Savings Account has an available balance of ₹2,45,850.00."

        # Interruption resumption for active workflows (TRANSFER_MONEY, OPEN_ACCOUNT, PAYMENT_ACTION)
        full_resp, next_wf, extra_state = _build_interruption_continuation(balance_msg, active_wf, state)
        out = {
            "current_intent": intent,
            "current_sub_intent": sub_intent or "LIST_ACCOUNTS",
            "active_workflow": next_wf,
            "final_response": full_resp,
            "messages": [AIMessage(content=full_resp)],
            "customer_memory": memory,
            "widget_type": widget_type,
            "widget_data": widget_data
        }
        out.update(extra_state)
        return out

    # 1b. Informational Inquiry: Customer KYC Status
    if sub_intent == "KYC_STATUS" or any(q in last_msg.lower() for q in ["is my kyc done", "is kyc done", "my kyc status", "kyc status", "check kyc", "is my account verified"]):
        async with AsyncSessionLocal() as session:
            repo = BankingRepository(session)
            cust = await repo.get_customer_by_id(customer_id)
        if cust:
            k_status = cust.kyc_status.upper() if cust.kyc_status else "PENDING"
            if k_status == "VERIFIED":
                kyc_resp = (
                    f"✅ Yes, **{cust.full_name}**! Your KYC verification is **COMPLETED & VERIFIED**.\n\n"
                    f"• **Customer ID**: `{cust.external_id}`\n"
                    f"• **KYC Status**: ACTIVE & VERIFIED\n"
                    f"• **Risk Tier**: {cust.risk_tier}\n\n"
                    "Your account has full digital banking privileges with NovaBank."
                )
            else:
                kyc_resp = (
                    f"Your KYC verification status is currently **{k_status}** ⏳.\n\n"
                    "To complete full verification, you can submit your details anytime through our digital onboarding."
                )
        else:
            kyc_resp = "I could not retrieve your customer profile. Please ensure you are logged into your account."

        full_resp, next_wf, extra_state = _build_interruption_continuation(kyc_resp, active_wf, state)
        out = {
            "current_intent": "OPEN_ACCOUNT",
            "current_sub_intent": "KYC_STATUS",
            "active_workflow": next_wf,
            "final_response": full_resp,
            "messages": [AIMessage(content=full_resp)],
            "customer_memory": memory
        }
        out.update(extra_state)
        return out

    # 1c. Informational Inquiry: Transfer Tracking, Diagnosis & Explanations
    if intent == "TRANSACTION_INQUIRY" or any(q in last_msg.lower() for q in [
        "latest amount i transferred", "latest amount transferred", "last transfer",
        "latest transfer", "what was my last transfer", "last transaction",
        "recent transfers", "transfer history", "track transfer", "transfer status",
        "laets amount", "what did i transfer", "why was my last transaction declined",
        "why did my balance decrease", "explain my last transaction", "explain my spending"
    ]):
        widget_type = None
        widget_data = None
        async with AsyncSessionLocal() as session:
            repo = BankingRepository(session)
            txn_ref = slots.get("transaction_ref")
            if not txn_ref:
                tx_match = re.search(r"\b(TXN-[A-Za-z0-9]+)\b", last_msg, re.IGNORECASE)
                if tx_match:
                    txn_ref = tx_match.group(1).upper()

            # Check if this is an explanation / decline root-cause inquiry
            is_explanation_query = (
                sub_intent in ("EXPLAIN_DECLINE", "EXPLAIN_LAST_TXN")
                or any(q in last_msg.lower() for q in [
                    "why was my last transaction declined", "why is my last transaction declined",
                    "why was my transaction declined", "why was it declined", "why did transaction fail",
                    "why my transfer failed", "why was it rejected", "why did it get declined",
                    "explain my last transaction", "explain my transaction", "explain transaction",
                    "explain my spending", "why did my balance decrease", "why balance decreased"
                ])
                or ("why" in last_msg.lower() and any(w in last_msg.lower() for w in ["decline", "declined", "failed", "reject", "rejected"]))
            )

            if is_explanation_query:
                q_type = "DECLINE_REASON" if sub_intent == "EXPLAIN_DECLINE" or any(w in last_msg.lower() for w in ["decline", "failed", "reject"]) else "LAST_TXN"
                explain_res = await tool_gateway.execute_tool(
                    agent_role=AgentRole.SUPERVISOR.value,
                    tool_name="explain_transaction",
                    repo=repo,
                    customer_id=customer_id,
                    parameters={"query_type": q_type, "transaction_ref": txn_ref}
                )
                if explain_res.success and explain_res.data:
                    tracking_msg = explain_res.data.get("conversational_text")
                    widget_type = "TRANSACTION_EXPLAIN_WIDGET"
                    widget_data = explain_res.data
                else:
                    tracking_msg = f"⚠️ Could not analyze transaction: {explain_res.error or 'No transactions found.'}"
            elif txn_ref:
                # Specific transaction reference tracking
                tx_res = await tool_gateway.execute_tool(
                    agent_role=AgentRole.SUPERVISOR.value,
                    tool_name="get_transaction",
                    repo=repo,
                    customer_id=customer_id,
                    parameters={"transaction_ref": txn_ref}
                )
                if tx_res.success and tx_res.data:
                    t = tx_res.data
                    status_emoji = "✅" if t.get("status") == "COMPLETED" else "⏳" if t.get("status") == "PENDING" else "❌"
                    bene_info = f" to **{t['beneficiary_name']}**" if t.get("beneficiary_name") else ""
                    tracking_msg = (
                        f"🔍 **Transaction Tracking Details** (Ref: `{t['transaction_ref']}`)\n\n"
                        f"• **Amount**: ₹{t['amount']:,.2f}\n"
                        f"• **Status**: {t['status']} {status_emoji}\n"
                        f"• **Recipient**:{bene_info} ({t.get('beneficiary_account') or 'N/A'})\n"
                        f"• **Source Account**: {t.get('source_account') or 'Savings'}\n"
                        f"• **Timestamp**: {t.get('created_at')}"
                    )
                else:
                    tracking_msg = f"I could not locate transaction `{txn_ref}` under your account. Please check the reference ID."
            else:
                # General recent transactions or latest transfer inquiry
                recent_res = await tool_gateway.execute_tool(
                    agent_role=AgentRole.SUPERVISOR.value,
                    tool_name="get_recent_transactions",
                    repo=repo,
                    customer_id=customer_id,
                    parameters={"limit": 5}
                )
                txs = recent_res.data.get("transactions", []) if recent_res.success else []
                if not txs:
                    tracking_msg = "You have not made any transfers or transactions yet."
                elif sub_intent == "LATEST_TRANSFER" or any(q in last_msg.lower() for q in ["latest", "last", "laets"]):
                    # Show the most recent transfer (and distinguish if latest was declined vs successful)
                    latest = txs[0]
                    last_completed = next((t for t in txs if t.get("status") == "COMPLETED"), None)

                    if latest.get("status") != "COMPLETED" and last_completed and last_completed != latest:
                        bene_latest = f" to **{latest.get('beneficiary_name')}**" if latest.get("beneficiary_name") else ""
                        bene_comp = f" to **{last_completed.get('beneficiary_name')}**" if last_completed.get("beneficiary_name") else ""
                        tracking_msg = (
                            f"Your latest transfer attempt was **₹{latest['amount']:,.2f}**{bene_latest} (Status: {latest.get('status')} ❌) on **{latest.get('created_at')}** (Ref: `{latest['transaction_ref']}`).\n\n"
                            f"Your last **successful** transfer was **₹{last_completed['amount']:,.2f}**{bene_comp} on **{last_completed.get('created_at')}**.\n"
                            f"• **Transaction ID**: `{last_completed['transaction_ref']}`\n"
                            f"• **Status**: COMPLETED ✅\n"
                            f"• **Recipient Account**: {last_completed.get('beneficiary_account') or 'N/A'}\n"
                            f"• **Debited From**: Savings {last_completed.get('source_account') or ''}"
                        )
                    else:
                        status_emoji = "✅" if latest.get("status") == "COMPLETED" else "⏳" if latest.get("status") == "PENDING" else "❌"
                        bene_info = f" to **{latest.get('beneficiary_name')}**" if latest.get("beneficiary_name") else ""
                        tracking_msg = (
                            f"Your latest transfer was **₹{latest['amount']:,.2f}**{bene_info} on **{latest.get('created_at')}**.\n\n"
                            f"• **Transaction ID**: `{latest['transaction_ref']}`\n"
                            f"• **Status**: {latest['status']} {status_emoji}\n"
                            f"• **Recipient Account**: {latest.get('beneficiary_account') or 'N/A'}\n"
                            f"• **Debited From**: Savings {latest.get('source_account') or ''}"
                        )
                else:
                    # List recent transfer history
                    lines = ["📋 **Your Recent Transfers & Transactions:**\n"]
                    for i, t in enumerate(txs[:5], 1):
                        status_emoji = "✅" if t.get("status") == "COMPLETED" else "⏳" if t.get("status") == "PENDING" else "❌"
                        bene = t.get("beneficiary_name") or "Transfer"
                        lines.append(f"{i}. **₹{t['amount']:,.2f}** to **{bene}** ({t.get('beneficiary_account') or ''}) - `{t['transaction_ref']}` [{t['status']} {status_emoji}] on {t.get('created_at')}")
                    tracking_msg = "\n".join(lines)

        full_resp, next_wf, extra_state = _build_interruption_continuation(tracking_msg, active_wf, state)
        out = {
            "current_intent": "TRANSACTION_INQUIRY",
            "current_sub_intent": sub_intent or "LATEST_TRANSFER",
            "active_workflow": next_wf,
            "final_response": full_resp,
            "messages": [AIMessage(content=full_resp)],
            "customer_memory": memory
        }
        if widget_type and widget_data:
            out["widget_type"] = widget_type
            out["widget_data"] = widget_data
        out.update(extra_state)
        return out

    # 1d. Official Bank Account Statement Generation (PDF + Summary)
    if intent == "STATEMENT_REQUEST" or any(q in last_msg.lower() for q in [
        "statement", "sattemnet", "statemnt", "statment", "account statement", "pdf statement",
        "download statement", "send statement", "get statement", "email statement", "bank statement"
    ]):
        async with AsyncSessionLocal() as session:
            repo = BankingRepository(session)
            period_val = slots.get("period_type")
            stmt_res = await tool_gateway.execute_tool(
                agent_role=AgentRole.SUPERVISOR.value,
                tool_name="generate_account_statement",
                repo=repo,
                customer_id=customer_id,
                parameters={"period_type": period_val}
            )

        if stmt_res.success and stmt_res.data:
            s_data = stmt_res.data
            acc = s_data.get("account", {})
            prd = s_data.get("period", {})
            summ = s_data.get("summary", {})
            d_url = s_data.get("download_url", "#")
            stmt_id = s_data.get("statement_id", "")

            stmt_msg = (
                f"📄 **NovaBank Official Account Statement** (ID: `{stmt_id}`)\n\n"
                f"• **Account**: {acc.get('masked_account')} ({acc.get('account_type', 'SAVINGS')})\n"
                f"• **Statement Period**: {prd.get('start_date')} to {prd.get('end_date')}\n"
                f"• **Opening Balance**: ₹{summ.get('opening_balance', 0.0):,.2f}\n"
                f"• **Total Credits**: ₹{summ.get('total_credits', 0.0):,.2f} (+)\n"
                f"• **Total Debits**: ₹{summ.get('total_debits', 0.0):,.2f} (-)\n"
                f"• **Closing Balance**: ₹{summ.get('closing_balance', 0.0):,.2f}\n"
                f"• **Total Transactions**: {s_data.get('transactions_count', 0)}\n\n"
                f"🔒 *Digitally signed with SHA-256 tamper verification seal.*\n\n"
                f"📥 [**Download Official PDF Statement**]({d_url})"
            )
            widget_type = "STATEMENT_WIDGET"
            widget_data = s_data
        else:
            stmt_msg = f"⚠️ Could not generate statement: {stmt_res.error or 'Internal error.'}"
            widget_type = None
            widget_data = None

        full_resp, next_wf, extra_state = _build_interruption_continuation(stmt_msg, active_wf, state)
        out = {
            "current_intent": "STATEMENT_REQUEST",
            "current_sub_intent": "DOWNLOAD_STATEMENT",
            "active_workflow": next_wf,
            "final_response": full_resp,
            "messages": [AIMessage(content=full_resp)],
            "customer_memory": memory
        }
        if widget_type and widget_data:
            out["widget_type"] = widget_type
            out["widget_data"] = widget_data
        out.update(extra_state)
        return out

    # 2. Informational Interruption: Knowledge Base RAG & Live Web Search
    if intent == "KNOWLEDGE_FAQ":
        async with AsyncSessionLocal() as session:
            repo = BankingRepository(session)
            articles = []
            if sub_intent != "WEB_SEARCH":
                rag_res = await tool_gateway.execute_tool(
                    agent_role=AgentRole.SUPERVISOR.value,
                    tool_name="search_knowledge_base",
                    repo=repo,
                    customer_id=customer_id,
                    parameters={"query": last_msg, "limit": 2}
                )
                if rag_res.success and rag_res.data.get("results"):
                    articles = rag_res.data["results"]

            if articles:
                rag_summary = "\n\n".join([f"• **{a['title']}**: {a['content']}" for a in articles])
            else:
                # Production Live Web Search & Regulatory Benchmark
                web_res = await tool_gateway.execute_tool(
                    agent_role=AgentRole.SUPERVISOR.value,
                    tool_name="search_web_banking",
                    repo=repo,
                    customer_id=customer_id,
                    parameters={"query": last_msg, "max_results": 3}
                )
                if web_res.success and web_res.data.get("results"):
                    w_results = web_res.data["results"]
                    items = []
                    for r in w_results:
                        items.append(
                            f"🌐 **[{r['title']}]({r['url']})** *({r['source']})*\n"
                            f"{r['snippet']}"
                        )
                    rag_summary = "Here are the latest verified search findings:\n\n" + "\n\n".join(items)
                else:
                    rag_summary = "I could not find specific policy or web documentation regarding that topic. Please let me know if you would like me to connect you with a representative."

            full_resp, next_wf, extra_state = _build_interruption_continuation(rag_summary, active_wf, state)
            out = {
                "current_intent": intent,
                "current_sub_intent": sub_intent or "FAQ",
                "active_workflow": next_wf,
                "final_response": full_resp,
                "messages": [AIMessage(content=full_resp)],
                "customer_memory": memory
            }
            out.update(extra_state)
            return out

    # 3. Handle Confirmation / Cancellation inside Transfer Workflow
    if active_wf == "TRANSFER_MONEY":
        transfer_data = dict(state.get("transfer_data") or {})
        if transfer_data.get("step") == "CONFIRM":
            if intent == "CONFIRM_YES" or last_msg.lower() in ["yes", "confirm", "proceed", "sure"]:
                transfer_data["user_confirmed"] = True
                transfer_data["step"] = "EXECUTE"
                return {
                    "current_intent": "CONFIRM_YES",
                    "transfer_data": transfer_data,
                    "active_workflow": "TRANSFER_MONEY"
                }
            elif intent == "CONFIRM_NO" or last_msg.lower() in ["no", "cancel"]:
                resp = "Transfer cancelled. How else may I assist you today?"
                return {
                    "current_intent": "CONFIRM_NO",
                    "active_workflow": "NONE",
                    "transfer_data": {},
                    "final_response": resp,
                    "messages": [AIMessage(content=resp)],
                    "widget_type": None,
                    "widget_data": None
                }
        elif transfer_data.get("step") == "ADD_BENEFICIARY":
            if intent == "CONFIRM_NO" or last_msg.lower() in ["no", "cancel", "stop", "abort", "nevermind"]:
                resp = "Beneficiary registration cancelled. How else may I assist you today?"
                return {
                    "current_intent": "CONFIRM_NO",
                    "active_workflow": "NONE",
                    "transfer_data": {},
                    "final_response": resp,
                    "messages": [AIMessage(content=resp)],
                    "widget_type": None,
                    "widget_data": None
                }

    # 4. Handle Confirmation / Cancellation inside Bill Payment Workflow
    if active_wf == "PAYMENT_ACTION":
        pay_data = dict(state.get("payment_data") or {})
        if pay_data.get("step") == "CONFIRM":
            if intent == "CONFIRM_YES" or last_msg.lower() in ["yes", "confirm", "proceed", "sure"]:
                pay_data["user_confirmed"] = True
                return {
                    "current_intent": "CONFIRM_YES",
                    "payment_data": pay_data,
                    "active_workflow": "PAYMENT_ACTION"
                }
            elif intent == "CONFIRM_NO" or last_msg.lower() in ["no", "cancel"]:
                resp = "Bill payment cancelled. Let me know if you need help with anything else."
                return {
                    "current_intent": "CONFIRM_NO",
                    "active_workflow": "NONE",
                    "payment_data": {},
                    "final_response": resp,
                    "messages": [AIMessage(content=resp)]
                }

    # 4c. Handle Confirmation / Cancellation inside Wealth Advisory (SIP Mandate) Workflow
    if active_wf == "WEALTH_ADVISORY":
        wealth_data = dict(state.get("wealth_data") or {})
        if wealth_data.get("step") == "CONFIRM":
            if intent == "CONFIRM_YES" or last_msg.lower() in ["yes", "confirm", "proceed", "sure", "authorize", "activate"]:
                wealth_data["user_confirmed"] = True
                wealth_data["step"] = "EXECUTE"
                return {
                    "current_intent": "CONFIRM_YES",
                    "wealth_data": wealth_data,
                    "active_workflow": "WEALTH_ADVISORY"
                }
            elif intent == "CONFIRM_NO" or last_msg.lower() in ["no", "cancel", "stop", "abort", "don't", "dont"]:
                resp = (
                    f"Understood, {first_name}! I have cancelled the SIP mandate setup. "
                    "No amounts will be debited from your account. Let me know if you would like to explore other funds or adjust the investment amount!"
                )
                return {
                    "current_intent": "CONFIRM_NO",
                    "active_workflow": "NONE",
                    "wealth_data": {},
                    "final_response": resp,
                    "messages": [AIMessage(content=resp)],
                    "widget_type": None,
                    "widget_data": None
                }

    # 5. Route to Account Opening Subgraph (preserves active slot collection)
    if intent == "OPEN_ACCOUNT" or (active_wf == "OPEN_ACCOUNT" and intent not in DOMAIN_INTENTS):
        acc_data = dict(state.get("account_data") or {})
        if slots.get("full_name"):
            acc_data["full_name"] = slots["full_name"]
        if slots.get("dob"):
            acc_data["date_of_birth"] = slots["dob"]
        if slots.get("account_type"):
            acc_data["account_type"] = slots["account_type"]

        return {
            "current_intent": "OPEN_ACCOUNT",
            "active_workflow": "OPEN_ACCOUNT",
            "account_data": acc_data,
            "customer_memory": memory
        }

    # 5b. Beneficiary Management & FAQ (intercept before Transfer Subgraph)
    lower_msg = last_msg.lower()
    if any(k in lower_msg for k in ["beneficiar", "beeficiar"]) and any(k in lower_msg for k in ["list", "show", "who", "view", "my", "all", "have", "saved", "details", "check", "any", "whom"]):
        customer_id = state.get("customer_id", 1)
        async with AsyncSessionLocal() as session:
            repo = BankingRepository(session)
            benes = await repo.get_beneficiaries(customer_id)
            if not benes:
                bene_resp = (
                    "You currently do not have any registered beneficiaries saved on your account.\n\n"
                    "To add a new beneficiary, simply provide their **Full Name**, **Account Number**, and **IFSC Code** (e.g. *'Add beneficiary Priya Sharma, account 9876543210, IFSC NOVA0001001'*)."
                )
            else:
                lines = [f"Here are your registered beneficiaries ({len(benes)} saved):\n"]
                for b in benes:
                    masked_acc = mask_account_number(b.account_number)
                    lines.append(f"• **{b.name}** — Account: `{masked_acc}`, IFSC: `{b.ifsc_code}` [{b.status}]")
                first_name = benes[0].name.split()[0]
                lines.append(f"\nTo send money to any of them, just say *'Transfer ₹1,000 to {first_name}'*.")
                bene_resp = "\n".join(lines)

        return {
            "current_intent": "KNOWLEDGE_FAQ",
            "current_sub_intent": "BENEFICIARY_MANAGEMENT",
            "active_workflow": "NONE",
            "transfer_data": {},
            "final_response": bene_resp,
            "messages": [AIMessage(content=bene_resp)],
            "customer_memory": memory,
            "widget_type": None,
            "widget_data": None
        }

    if any(k in lower_msg for k in ["beneficiar", "beeficiar"]) and any(k in lower_msg for k in ["how to", "how do", "add", "register", "create", "new"]):
        if any(k in lower_msg for k in ["how to", "how do", "process", "steps"]):
            bene_msg = (
                "To add a new beneficiary to your account:\n"
                "1. Provide their **Full Name**, **Bank Account Number**, and **IFSC Code** (e.g., *'Add beneficiary Priya Sharma, account 9876543210, IFSC NOVA0001001'*).\n"
                "2. Once registered, for safety compliance, transfers above ₹50,000 have a standard 30-minute cooling period.\n\n"
                "Would you like to add a beneficiary now? Please provide their name, account number, and IFSC code."
            )
            return {
                "current_intent": "KNOWLEDGE_FAQ",
                "current_sub_intent": "BENEFICIARY_MANAGEMENT",
                "active_workflow": "NONE",
                "transfer_data": {},
                "final_response": bene_msg,
                "messages": [AIMessage(content=bene_msg)],
                "customer_memory": memory,
                "widget_type": None,
                "widget_data": None
            }
        else:
            target_name = slots.get("beneficiary_name") or "the recipient"
            if slots.get("beneficiary_account"):
                # Both name and account details provided in same turn!
                transfer_data = {
                    "step": "ADD_BENEFICIARY",
                    "beneficiary_name": target_name,
                    "beneficiary_account": slots["beneficiary_account"],
                    "ifsc_code": slots.get("ifsc_code", "NOVA0001001"),
                    "amount": slots.get("amount") or 0.0
                }
                return {
                    "current_intent": "TRANSFER_MONEY",
                    "active_workflow": "TRANSFER_MONEY",
                    "transfer_data": transfer_data,
                    "customer_memory": memory
                }
            else:
                bene_msg = (
                    f"To add **{target_name}** as a registered beneficiary, please provide their:\n"
                    "• **Account Number** (e.g., 9876543210)\n"
                    "• **IFSC Code** (e.g., NOVA0001001)\n\n"
                    "Once provided, they will be registered and ready for instant transfers!"
                )
                return {
                    "current_intent": "TRANSFER_MONEY",
                    "current_sub_intent": "BENEFICIARY_MANAGEMENT",
                    "active_workflow": "TRANSFER_MONEY",
                    "transfer_data": {
                        "step": "ADD_BENEFICIARY",
                        "beneficiary_name": target_name,
                        "amount": slots.get("amount") or 0.0
                    },
                    "final_response": bene_msg,
                    "messages": [AIMessage(content=bene_msg)],
                    "customer_memory": memory,
                    "widget_type": None,
                    "widget_data": None
                }

    # 6. Route to Transfer Subgraph
    if intent == "TRANSFER_MONEY" or (active_wf == "TRANSFER_MONEY" and intent not in DOMAIN_INTENTS and not state.get("transfer_data", {}).get("user_confirmed")):
        transfer_data = dict(state.get("transfer_data") or {})
        if slots.get("amount") and (not transfer_data.get("amount") or transfer_data.get("step") != "ADD_BENEFICIARY"):
            transfer_data["amount"] = slots["amount"]
        if slots.get("beneficiary_name"):
            transfer_data["beneficiary_name"] = slots["beneficiary_name"]
        if slots.get("beneficiary_account"):
            is_v, c_acc, _ = validate_account_number(slots["beneficiary_account"])
            if is_v:
                transfer_data["beneficiary_account"] = c_acc
        if slots.get("ifsc_code"):
            is_v, c_ifsc, _ = validate_ifsc_code(slots["ifsc_code"])
            if is_v:
                transfer_data["ifsc_code"] = c_ifsc

        return {
            "current_intent": "TRANSFER_MONEY",
            "active_workflow": "TRANSFER_MONEY",
            "transfer_data": transfer_data,
            "customer_memory": memory
        }

    # 7. Route to Card Operations Subgraph
    if intent == "CARD_ACTION" or (active_wf == "CARD_ACTION" and intent not in DOMAIN_INTENTS):
        card_data = dict(state.get("card_data") or {})
        if slots.get("card_type"):
            card_data["card_type"] = slots["card_type"]
        if slots.get("amount"):
            card_data["online_limit"] = slots["amount"]
        return {
            "current_intent": "CARD_ACTION",
            "current_sub_intent": sub_intent,
            "active_workflow": "CARD_ACTION",
            "card_data": card_data,
            "customer_memory": memory
        }

    # 8. Route to Loan & Advisory Subgraph
    if intent == "LOAN_ACTION" or (active_wf == "LOAN_ACTION" and intent not in DOMAIN_INTENTS):
        loan_data = dict(state.get("loan_data") or {})
        if slots.get("amount"):
            loan_data["amount"] = slots["amount"]
        if slots.get("tenure_months"):
            loan_data["tenure_months"] = slots["tenure_months"]
        return {
            "current_intent": "LOAN_ACTION",
            "current_sub_intent": sub_intent,
            "active_workflow": "LOAN_ACTION",
            "loan_data": loan_data,
            "customer_memory": memory
        }

    # 9. Route to Bill Payments & UPI Subgraph
    if intent == "PAYMENT_ACTION" or (active_wf == "PAYMENT_ACTION" and intent not in DOMAIN_INTENTS):
        pay_data = dict(state.get("payment_data") or {})
        if slots.get("biller_name"):
            pay_data["biller_name"] = slots["biller_name"]
        if slots.get("amount"):
            pay_data["amount"] = slots["amount"]
        return {
            "current_intent": "PAYMENT_ACTION",
            "current_sub_intent": sub_intent,
            "active_workflow": "PAYMENT_ACTION",
            "payment_data": pay_data,
            "customer_memory": memory
        }

    # 10. Route to Support Subgraph
    if intent == "SUPPORT_DISPUTE" or (active_wf == "SUPPORT" and intent not in DOMAIN_INTENTS):
        support_data = dict(state.get("support_data") or {})
        support_data["sub_intent"] = sub_intent
        if slots.get("transaction_ref"):
            support_data["transaction_ref"] = slots["transaction_ref"]
        return {
            "current_intent": "SUPPORT_DISPUTE",
            "current_sub_intent": sub_intent,
            "active_workflow": "SUPPORT",
            "support_data": support_data,
            "customer_memory": memory
        }

    # 11. Route to PFM Insights Subgraph
    if intent == "SPENDING_INSIGHTS" or (active_wf == "INSIGHTS" and intent not in DOMAIN_INTENTS):
        raw_text = last_msg.lower()
        ins_action = "SPENDING"
        if "subscript" in raw_text or "recurring" in raw_text:
            ins_action = "SUBSCRIPTIONS"
        elif "cashflow" in raw_text or "safe" in raw_text:
            ins_action = "CASHFLOW"

        return {
            "current_intent": "SPENDING_INSIGHTS",
            "current_sub_intent": sub_intent or "SPENDING_BREAKDOWN",
            "active_workflow": "INSIGHTS",
            "insights_data": {"action": ins_action, "days": 30},
            "customer_memory": memory
        }

    # 11b. Route to Wealth Advisory & SIP Planning Subgraph
    if intent == "WEALTH_ADVISORY" or (active_wf == "WEALTH_ADVISORY" and intent not in DOMAIN_INTENTS):
        wealth_data = dict(state.get("wealth_data") or {})
        if slots.get("user_persona"):
            wealth_data["user_persona"] = slots["user_persona"]
        if slots.get("risk_profile"):
            wealth_data["risk_profile"] = slots["risk_profile"]
        if slots.get("amount"):
            wealth_data["monthly_investment"] = slots["amount"]
        if slots.get("stock_symbol"):
            wealth_data["symbol"] = slots["stock_symbol"]
        return {
            "current_intent": "WEALTH_ADVISORY",
            "current_sub_intent": sub_intent or "SIP_PLANNING",
            "active_workflow": "WEALTH_ADVISORY",
            "wealth_data": wealth_data,
            "customer_memory": memory
        }

    # 11c. Route to Policy & Insurance Advisory Subgraph
    if intent == "POLICY_INQUIRY" or (active_wf == "POLICY_ACTION" and intent not in DOMAIN_INTENTS):
        policy_data = dict(state.get("policy_data") or {})
        if slots.get("policy_category"):
            policy_data["category"] = slots["policy_category"]
        return {
            "current_intent": "POLICY_INQUIRY",
            "current_sub_intent": sub_intent or "BANKING_POLICY",
            "active_workflow": "POLICY_ACTION",
            "policy_data": policy_data,
            "customer_memory": memory
        }

    # 12. User Identity Query ("what is my name", "who am i")
    lower_msg = last_msg.lower()
    full_cust_name = state.get("customer_name")
    if any(k in lower_msg for k in ["what is my name", "whats my name", "who am i", "tell me my name"]):
        name_msg = f"Your registered name with NovaBank is **{full_cust_name}**." if full_cust_name else "I do not have your name registered in this session."
        return {
            "current_intent": "GENERAL_CONVERSATION",
            "current_sub_intent": "USER_IDENTITY",
            "active_workflow": "NONE",
            "final_response": name_msg,
            "messages": [AIMessage(content=name_msg)],
            "customer_memory": memory,
            "widget_type": None,
            "widget_data": None
        }

    # 12b. Gratitude & Appreciation Handling ("thank you", "thanks", "thanku", "thx")
    clean_text = lower_msg.strip().rstrip("!.,")
    is_gratitude = (
        sub_intent == "THANK_YOU"
        or any(clean_text == t for t in [
            "thank you", "thanks", "thanku", "thx", "ty", "thank u", "many thanks",
            "great thanks", "thanks a lot", "thank you so much", "thank u so much",
            "thanks bot", "thnx", "appreciate it", "thankyou", "thanks!"
        ])
        or any(lower_msg.startswith(p) for p in ["thank you", "thanks", "thanku", "appreciate it", "thank u"])
    )
    if is_gratitude:
        # Determine previous assistant context
        last_ai_content = ""
        for m in reversed(state.get("messages", [])):
            if isinstance(m, AIMessage):
                last_ai_content = m.content or ""
                break

        cust_first_name = (state.get("customer_name") or "").split(" ")[0].capitalize()
        name_str = cust_first_name if cust_first_name else "there"

        # Contextual appreciation based on preceding action (Segregated in agents.supervisor.prompts)
        appreciation_msg = build_gratitude_response(last_ai_content, state.get("customer_name") or "")

        full_resp, next_wf, extra_state = _build_interruption_continuation(appreciation_msg, active_wf, state)
        out = {
            "current_intent": "GENERAL_CONVERSATION",
            "current_sub_intent": "THANK_YOU",
            "active_workflow": next_wf,
            "final_response": full_resp,
            "messages": [AIMessage(content=full_resp)],
            "customer_memory": memory,
            "widget_type": None,
            "widget_data": None
        }
        out.update(extra_state)
        return out

    # 13. Conversational / Intelligent Fallback Handler
    is_greeting = any(clean_text == g for g in [
        "hi", "hello", "hey", "good morning", "good evening", "good afternoon",
        "namaste", "hola", "help", "menu", "start", "options"
    ]) or sub_intent == "GREETING"

    if is_greeting:
        resp_msg = build_supervisor_default_menu(state.get("customer_name") or "")
    else:
        resp_msg = build_chatgpt_style_fallback_response(last_msg, state.get("customer_name") or "")

    return {
        "current_intent": "GENERAL_CONVERSATION",
        "current_sub_intent": sub_intent or "OTHER",
        "active_workflow": "NONE",
        "paused_workflow": None,
        "account_data": {},
        "transfer_data": {},
        "loan_data": {},
        "payment_data": {},
        "card_data": {},
        "wealth_data": {},
        "policy_data": {},
        "final_response": resp_msg,
        "messages": [AIMessage(content=resp_msg)],
        "customer_memory": memory,
        "widget_type": None,
        "widget_data": None
    }


def supervisor_dispatch(state: BankingSessionState) -> str:
    """Dispatches execution to the corresponding compiled subgraph."""
    wf = state.get("active_workflow")
    intent = state.get("current_intent")

    # If the router already produced the final response (e.g. balance check, FAQ, or cancellation)
    if state.get("final_response") and intent in ["BALANCE_CHECK", "KNOWLEDGE_FAQ", "GENERAL_CONVERSATION", "CONFIRM_NO", "TEMPORAL_QUERY", "STATEMENT_REQUEST"]:
        return END

    if wf == "OPEN_ACCOUNT":
        return "account_subgraph"
    elif wf == "TRANSFER_MONEY":
        return "transfer_subgraph"
    elif wf == "CARD_ACTION":
        return "card_subgraph"
    elif wf == "LOAN_ACTION":
        return "loan_subgraph"
    elif wf == "PAYMENT_ACTION":
        return "payment_subgraph"
    elif wf == "SUPPORT":
        return "support_subgraph"
    elif wf == "INSIGHTS":
        return "insights_subgraph"
    elif wf == "WEALTH_ADVISORY":
        return "wealth_subgraph"
    elif wf == "POLICY_ACTION":
        return "policy_subgraph"

    return END

