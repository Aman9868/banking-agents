"""Master Banking Supervisor StateGraph with 6-Agent Orchestration & Context Switching."""

from typing import Dict, Any, Optional
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
import structlog

logger = structlog.get_logger(__name__)


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
        return {
            "current_intent": "TEMPORAL_QUERY",
            "current_sub_intent": "CURRENT_TIME_DATE",
            "intent_confidence": confidence,
            "routing_reasoning": reasoning,
            "active_workflow": "NONE",
            "final_response": time_resp,
            "messages": [AIMessage(content=time_resp)],
            "customer_memory": memory
        }

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

        # If interrupted an ongoing workflow, resume it!
        if active_wf == "OPEN_ACCOUNT":
            acc_data = state.get("account_data") or {}
            step = acc_data.get("step", "NAME")
            if step == "DOB":
                resume_prompt = "\n\nNow, continuing with your account application: What is your date of birth?"
            elif step == "EMAIL":
                resume_prompt = "\n\nNow, continuing with your account application: What is your email address?"
            else:
                resume_prompt = "\n\nNow, continuing with your account application: What is your full name?"
            full_resp = balance_msg + resume_prompt
            return {
                "current_intent": intent,
                "final_response": full_resp,
                "messages": [AIMessage(content=full_resp)]
            }

        return {
            "current_intent": intent,
            "active_workflow": "NONE",
            "final_response": balance_msg,
            "messages": [AIMessage(content=balance_msg)]
        }

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
            return {
                "current_intent": intent,
                "active_workflow": "NONE",
                "final_response": rag_summary,
                "messages": [AIMessage(content=rag_summary)]
            }

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
                    "messages": [AIMessage(content=resp)]
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

    # 6. Route to Transfer Subgraph
    if intent == "TRANSFER_MONEY" or (active_wf == "TRANSFER_MONEY" and not state.get("transfer_data", {}).get("user_confirmed")):
        transfer_data = dict(state.get("transfer_data") or {})
        if slots.get("amount"):
            transfer_data["amount"] = slots["amount"]
        if slots.get("beneficiary_name"):
            transfer_data["beneficiary_name"] = slots["beneficiary_name"]

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

    # 12. Default Banking Assistant Menu
    default_msg = (
        "Hello Amanpreet! I am your AI Banking Assistant. I can assist you with:\n"
        "• Transfers & Beneficiaries: Send money, UPI payments, balance checks\n"
        "• Cards Management: Instant freeze/unfreeze, report lost card, set limits\n"
        "• Loans & Advisory: EMI calculators, loan eligibility, application submission\n"
        "• Bill Payments: Pay electricity, broadband, mobile, and credit card bills\n"
        "• Account Opening: Seamless conversational savings and current accounts\n"
        "• Support & FAQs: Transaction dispute investigation, interest rates, and fees"
    )
    return {
        "current_intent": "GENERAL_CONVERSATION",
        "current_sub_intent": sub_intent,
        "active_workflow": "NONE",
        "final_response": default_msg,
        "messages": [AIMessage(content=default_msg)],
        "customer_memory": memory
    }


def supervisor_dispatch(state: BankingSessionState) -> str:
    """Dispatches execution to the corresponding compiled subgraph."""
    wf = state.get("active_workflow")
    intent = state.get("current_intent")

    # If the router already produced the final response (e.g. balance check, FAQ, or cancellation)
    if state.get("final_response") and intent in ["BALANCE_CHECK", "KNOWLEDGE_FAQ", "GENERAL_CONVERSATION", "CONFIRM_NO", "TEMPORAL_QUERY"]:
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

    return END


# Assemble Master Banking Supervisor Graph with all 7 Subgraphs
supervisor_graph_builder = StateGraph(BankingSessionState)
supervisor_graph_builder.add_node("router", supervisor_router_node)
supervisor_graph_builder.add_node("account_subgraph", account_subgraph)
supervisor_graph_builder.add_node("transfer_subgraph", transfer_subgraph)
supervisor_graph_builder.add_node("card_subgraph", card_subgraph)
supervisor_graph_builder.add_node("loan_subgraph", loan_subgraph)
supervisor_graph_builder.add_node("payment_subgraph", payment_subgraph)
supervisor_graph_builder.add_node("support_subgraph", support_subgraph)
supervisor_graph_builder.add_node("insights_subgraph", insights_subgraph)

supervisor_graph_builder.add_edge(START, "router")
supervisor_graph_builder.add_conditional_edges(
    "router",
    supervisor_dispatch,
    ["account_subgraph", "transfer_subgraph", "card_subgraph", "loan_subgraph", "payment_subgraph", "support_subgraph", "insights_subgraph", END]
)
supervisor_graph_builder.add_edge("account_subgraph", END)
supervisor_graph_builder.add_edge("transfer_subgraph", END)
supervisor_graph_builder.add_edge("card_subgraph", END)
supervisor_graph_builder.add_edge("loan_subgraph", END)
supervisor_graph_builder.add_edge("payment_subgraph", END)
supervisor_graph_builder.add_edge("support_subgraph", END)
supervisor_graph_builder.add_edge("insights_subgraph", END)
