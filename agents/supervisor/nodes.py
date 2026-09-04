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
import structlog

logger = structlog.get_logger(__name__)


def _build_interruption_continuation(
    base_msg: str,
    active_wf: str,
    state: BankingSessionState
) -> Tuple[str, str, Dict[str, Any]]:
    """Appends contextual continuation prompt for any active workflow during an interruption."""
    if active_wf == "TRANSFER_MONEY":
        t_data = dict(state.get("transfer_data") or {})
        t_step = t_data.get("step")
        bene = t_data.get("beneficiary_name", "the beneficiary")
        acc = t_data.get("beneficiary_account")
        ifsc = t_data.get("ifsc_code")
        amt = t_data.get("amount")

        if t_step == "ADD_BENEFICIARY":
            if acc and not ifsc:
                prompt = (
                    f"\n\nNow, continuing with adding **{bene}** as a beneficiary: "
                    "Please provide their **11-character IFSC Code** (e.g. SBIN0001234 or NOVA0001001) to proceed with the transfer."
                )
            elif ifsc and not acc:
                prompt = (
                    f"\n\nNow, continuing with adding **{bene}** as a beneficiary: "
                    "Please provide their **Account Number** (9 to 18 digits) to proceed with the transfer."
                )
            else:
                prompt = (
                    f"\n\nNow, continuing with your transfer to **{bene}**: "
                    "Please provide their **Account Number** and **IFSC Code** to add them as a beneficiary."
                )
        elif t_step == "CONFIRM":
            amt_str = f"₹{amt:,.2f}" if amt else "the funds"
            prompt = (
                f"\n\nNow, continuing with your transfer: Would you like to proceed with transferring "
                f"**{amt_str}** to **{bene}**? (Please reply 'Yes' to confirm or 'No' to cancel)."
            )
        elif t_step == "RESOLVE":
            if not amt:
                prompt = f"\n\nNow, continuing with your transfer to **{bene}**: How much would you like to transfer?"
            else:
                prompt = f"\n\nNow, continuing with your transfer: Who would you like to transfer funds to?"
        else:
            prompt = f"\n\nWould you like to continue with your transfer to **{bene}**?"

        return base_msg + prompt, "TRANSFER_MONEY", {"transfer_data": t_data}

    elif active_wf == "OPEN_ACCOUNT":
        acc_data = dict(state.get("account_data") or {})
        step = acc_data.get("step", "NAME")
        if step == "DOB":
            prompt = "\n\nNow, continuing with your account application: What is your date of birth?"
        elif step == "EMAIL":
            prompt = "\n\nNow, continuing with your account application: What is your email address?"
        else:
            prompt = "\n\nNow, continuing with your account application: What is your full name?"
        return base_msg + prompt, "OPEN_ACCOUNT", {"account_data": acc_data}

    elif active_wf == "PAYMENT_ACTION":
        bill_data = dict(state.get("bill_data") or {})
        biller = bill_data.get("biller_name", "your bill")
        prompt = f"\n\nNow, continuing with your bill payment for **{biller}**: Please provide the consumer number or confirm payment."
        return base_msg + prompt, "PAYMENT_ACTION", {"bill_data": bill_data}

    elif active_wf == "WEALTH_ADVISORY":
        w_data = dict(state.get("wealth_data") or {})
        amt = w_data.get("monthly_investment", 1000.0)
        prompt = f"\n\nNow, continuing with your SIP investment planning of ₹{amt:,.2f}/month: Would you like to view our recommended funds or adjust the tenure?"
        return base_msg + prompt, "WEALTH_ADVISORY", {"wealth_data": w_data}

    elif active_wf == "POLICY_ACTION":
        p_data = dict(state.get("policy_data") or {})
        cat = p_data.get("category", "insurance")
        prompt = f"\n\nNow, continuing with your {cat} policy exploration: Would you like more details or a comparison between specific plans?"
        return base_msg + prompt, "POLICY_ACTION", {"policy_data": p_data}

    return base_msg, "NONE", {}


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
    memory = dict(state.get("customer_memory") or {})

    # Route request using production-grade Pydantic router
    routing_ctx = {
        "active_workflow": active_wf,
        "account_data": state.get("account_data"),
        "transfer_data": state.get("transfer_data"),
        "payment_data": state.get("payment_data"),
    }
    decision = await route_banking_request(last_msg, context=routing_ctx)
    intent = decision.intent.value
    sub_intent = decision.sub_intent.value if decision.sub_intent else None
    slots = decision.entities.model_dump()
    confidence = decision.confidence
    reasoning = decision.reasoning
    negation = decision.negation_detected

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
            "customer_memory": memory
        }

    # 1. Informational Interruption: Balance Check
    if intent == "BALANCE_CHECK":
        async with AsyncSessionLocal() as session:
            repo = BankingRepository(session)
            bal_res = await tool_gateway.execute_tool(
                agent_role=AgentRole.SUPERVISOR.value,
                tool_name="get_balance",
                repo=repo,
                customer_id=customer_id,
                parameters={}
            )

        if bal_res.success:
            masked = bal_res.data["masked_account"]
            bal = bal_res.data["balance"]
            balance_msg = f"Your current balance for {bal_res.data['account_type'].capitalize()} account {masked} is ₹{bal:,.2f}."
        else:
            balance_msg = "You currently do not have an active account with a balance."

        # Interruption resumption for active workflows (TRANSFER_MONEY, OPEN_ACCOUNT, PAYMENT_ACTION)
        full_resp, next_wf, extra_state = _build_interruption_continuation(balance_msg, active_wf, state)
        out = {
            "current_intent": intent,
            "active_workflow": next_wf,
            "final_response": full_resp,
            "messages": [AIMessage(content=full_resp)],
            "customer_memory": memory,
            "widget_type": None,
            "widget_data": None
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

    # 2. Informational Interruption: Knowledge Base RAG

    if intent == "KNOWLEDGE_FAQ":
        async with AsyncSessionLocal() as session:
            repo = BankingRepository(session)
            rag_res = await tool_gateway.execute_tool(
                agent_role=AgentRole.SUPERVISOR.value,
                tool_name="search_knowledge_base",
                repo=repo,
                customer_id=customer_id,
                parameters={"query": last_msg, "limit": 2}
            )
        if rag_res.success and rag_res.data.get("results"):
            articles = rag_res.data["results"]
            rag_summary = "\n\n".join([f"• **{a['title']}**: {a['content']}" for a in articles])
            full_resp, next_wf, extra_state = _build_interruption_continuation(rag_summary, active_wf, state)
            out = {
                "current_intent": intent,
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

    # 5. Route to Account Opening Subgraph (preserves active slot collection)
    if active_wf == "OPEN_ACCOUNT" or intent == "OPEN_ACCOUNT":
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
    if intent == "TRANSFER_MONEY" or (active_wf == "TRANSFER_MONEY" and not state.get("transfer_data", {}).get("user_confirmed")):
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
    if intent == "CARD_ACTION" or active_wf == "CARD_ACTION":
        card_data = dict(state.get("card_data") or {})
        if slots.get("card_type"):
            card_data["card_type"] = slots["card_type"]
        return {
            "current_intent": "CARD_ACTION",
            "active_workflow": "CARD_ACTION",
            "card_data": card_data,
            "customer_memory": memory
        }

    # 8. Route to Loan & Advisory Subgraph
    if intent == "LOAN_ACTION" or active_wf == "LOAN_ACTION":
        loan_data = dict(state.get("loan_data") or {})
        if slots.get("amount"):
            loan_data["amount"] = slots["amount"]
        if slots.get("tenure_months"):
            loan_data["tenure_months"] = slots["tenure_months"]
        return {
            "current_intent": "LOAN_ACTION",
            "active_workflow": "LOAN_ACTION",
            "loan_data": loan_data,
            "customer_memory": memory
        }

    # 9. Route to Bill Payments & UPI Subgraph
    if intent == "PAYMENT_ACTION" or active_wf == "PAYMENT_ACTION":
        pay_data = dict(state.get("payment_data") or {})
        if slots.get("biller_name"):
            pay_data["biller_name"] = slots["biller_name"]
        return {
            "current_intent": "PAYMENT_ACTION",
            "active_workflow": "PAYMENT_ACTION",
            "payment_data": pay_data,
            "customer_memory": memory
        }

    # 10. Route to Support Subgraph
    if intent == "SUPPORT_DISPUTE":
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
    if intent == "SPENDING_INSIGHTS" or active_wf == "INSIGHTS":
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
    if intent == "WEALTH_ADVISORY" or active_wf == "WEALTH_ADVISORY":
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
    if intent == "POLICY_INQUIRY" or active_wf == "POLICY_ACTION":
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

        # Contextual appreciation based on preceding action
        if any(k in last_ai_content for k in ["Transaction ID", "TXN-", "latest transfer was", "latest transfer attempt", "Recent Transfers", "Debited From"]):
            bene_mention = " to Rahul" if "Rahul" in last_ai_content else ""
            appreciation_msg = f"You're very welcome, {name_str}! 😊 Glad I could help you check your transfer details{bene_mention}. Let me know if you need an official PDF statement, a balance check, or anything else!"
        elif any(k in last_ai_content for k in ["Official Account Statement", "NovaBank Official Account Statement", "Download Official PDF Statement"]) or state.get("widget_type") == "STATEMENT_WIDGET":
            appreciation_msg = f"You're very welcome, {name_str}! 📄 I hope the statement details and PDF are helpful. Feel free to ask if you need statements for other date ranges or any spending insights!"
        elif any(k in last_ai_content for k in ["Transaction Diagnosis", "Root Cause:", "Beneficiary Cool-Off", "Recommended Next Step"]):
            appreciation_msg = f"You're very welcome, {name_str}! I'm always here to help clarify transaction policies and safeguard your accounts. Let me know if you'd like help with anything else!"
        elif any(k in last_ai_content for k in ["Transfer initiated!", "sent successfully", "Official Transaction Receipt"]) or (state.get("transfer_data") or {}).get("step") == "COMPLETED":
            appreciation_msg = f"You're most welcome, {name_str}! 🎉 Glad that transfer went through smoothly. Feel free to ask if you need a receipt, statement, or anything else. Have a wonderful day! 😊"
        elif any(k in last_ai_content for k in ["current balance for", "available balance", "is ₹"]):
            appreciation_msg = f"You're very welcome, {name_str}! Always happy to help keep track of your account balance. Let me know if you need to make a transfer, pay a bill, or check statements!"
        elif any(k in last_ai_content for k in ["account SB", "account CA", "KYC is complete", "Passbook", "successfully opened"]):
            appreciation_msg = f"It was my absolute pleasure, {name_str}! 🌟 Congratulations once again on opening your NovaBank account. Let me know whenever you'd like to explore features, make a deposit, or add beneficiaries!"
        elif any(k in last_ai_content for k in ["INSTANTLY FROZEN", "Card Security", "unfrozen", "card limits"]):
            appreciation_msg = f"You're very welcome, {name_str}! Your card and account security is always our top priority. We're here 24/7 whenever you need us!"
        elif any(k in last_ai_content for k in ["Monthly EMI", "EMI Simulator", "Personal Loan"]):
            appreciation_msg = f"Happy to help with your loan calculations, {name_str}! Feel free to reach out when you're ready to proceed with an application or explore other options. 😊"
        elif any(k in last_ai_content for k in ["Paid to", "bill payment", "Electricity Bill"]):
            appreciation_msg = f"You're very welcome, {name_str}! Glad that payment is all sorted. Let me know if you have other bills or transfers to take care of."
        elif any(k in last_ai_content for k in ["SIP", "Compounding", "Student Starter", "Nifty 50", "Asset Allocation"]):
            appreciation_msg = f"You're very welcome, {name_str}! Starting your investment journey early is the best decision you can make. Let me know whenever you'd like to adjust your SIP or explore other funds! 🚀"
        elif any(k in last_ai_content for k in ["Health Shield", "PMJJBY", "Insurance", "Policy Catalog", "Health & Medical"]):
            appreciation_msg = f"Always glad to help secure your financial future, {name_str}! Reach out anytime you have questions about policies or coverage benefits. 🌟"
        elif any(k in last_ai_content for k in ["Live Market Quote", "Financial & Stock Market"]):
            appreciation_msg = f"You're very welcome, {name_str}! Happy to provide real-time market data. Let me know if you need quotes or insights on any other stocks!"
        else:
            appreciation_msg = f"You're very welcome, {name_str}! 😊 It's always my pleasure to assist you. Just let me know whenever you need anything else with NovaBank!"

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

    # 13. Default Banking Assistant Menu
    cust_display_name = state.get("customer_name", "").split(" ")[0] if state.get("customer_name") else "there"
    default_msg = (
        f"Hello {cust_display_name}! I am your AI Banking Assistant. I can assist you with:\n"
        "• Transfers & Beneficiaries: Send money, UPI payments, balance checks\n"
        "• Wealth & Investments: Student SIP planner, compounding calculators, live stock market search\n"
        "• Insurance & Policies: Student health shield, pure term life, PMJJBY, PMSBY, PPF & NPS\n"
        "• Statements & Ledgers: Official PDF statements with running balances & decline diagnosis\n"
        "• Cards Management: Instant freeze/unfreeze, report lost card, set limits\n"
        "• Loans & Advisory: EMI calculators, loan eligibility, application submission\n"
        "• Bill Payments: Pay electricity, broadband, mobile, and credit card bills\n"
        "• Account Opening: Conversational savings and current account opening with video KYC\n"
        "• Support & FAQs: Dispute investigation, interest rates, and customer support escalation"
    )
    return {
        "current_intent": "GENERAL_CONVERSATION",
        "current_sub_intent": sub_intent,
        "active_workflow": "NONE",
        "final_response": default_msg,
        "messages": [AIMessage(content=default_msg)],
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

