"""Customer Support Subgraph with Transaction Dispute Analysis, Grounded RAG, and Human Escalation."""

import re
from typing import Dict, Any
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from gateway.tool_gateway.gateway import tool_gateway
from gateway.tool_gateway.permissions import AgentRole
from security.pii import mask_account_number
from agents.support.prompts import (
    REASON_TRANSLATIONS,
    build_fraud_ticket_response,
    build_kb_guidelines_response,
    build_transaction_dispute_response,
)
import structlog

logger = structlog.get_logger(__name__)


async def support_orchestrator_node(state: BankingSessionState) -> Dict[str, Any]:
    """
    Unified Support Agent:
    1. Transaction dispute investigation & translation
    2. Grounded RAG knowledge search (policy, fees, rates)
    3. Escalation & support ticket creation
    """
    customer_id = state.get("customer_id", 1)
    raw_sub = state.get("current_sub_intent") or state.get("support_data", {}).get("sub_intent")
    sub_intent = (raw_sub or "").upper()
    last_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_msg = msg.content.strip()
            break

    text_lower = last_msg.lower()

    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)

        # 0. High-Priority Fraud / Unauthorized Transaction
        if sub_intent == "UNAUTHORIZED_TRANSACTION" or any(k in text_lower for k in ["unauthorized", "fraud", "someone stole", "suspicious charge"]):
            try:
                ticket_res = await tool_gateway.execute_tool(
                    agent_role=AgentRole.SUPPORT_AGENT.value,
                    tool_name="create_support_ticket",
                    repo=repo,
                    customer_id=customer_id,
                    parameters={
                        "subject": "🚨 URGENT: Unauthorized Transaction & Fraud Report",
                        "description": f"Customer reported unauthorized activity: {last_msg}",
                        "priority": "HIGH"
                    }
                )
                if ticket_res.success:
                    await session.commit()
                    ticket_id = ticket_res.data.get("ticket_id", "TKT-SEC-01")
                else:
                    ticket_id = "TKT-SEC-01"
            except Exception:
                ticket_id = "TKT-SEC-01"
            resp = build_fraud_ticket_response(ticket_id)
            return {
                "active_workflow": "NONE",
                "final_response": resp,
                "messages": [AIMessage(content=resp)]
            }

        # 1. Human Escalation / Create Support Ticket
        if sub_intent in ["CREATE_TICKET", "ESCALATE_HUMAN", "FILE_COMPLAINT"] or any(k in text_lower for k in ["human", "agent", "escalate", "file a complaint", "open ticket", "raise ticket"]):
            ticket_res = await tool_gateway.execute_tool(
                agent_role=AgentRole.SUPPORT_AGENT.value,
                tool_name="create_support_ticket",
                repo=repo,
                customer_id=customer_id,
                parameters={
                    "subject": "Customer Service Request",
                    "description": last_msg,
                    "priority": "HIGH" if "urgent" in text_lower else "MEDIUM"
                }
            )
            await session.commit()
            resp = ticket_res.data.get("message")
            return {
                "active_workflow": "NONE",
                "final_response": resp,
                "messages": [AIMessage(content=resp)]
            }

        # 2. General Knowledge / FAQ RAG Search
        if sub_intent in ["FAQ", "INTEREST_RATE", "POLICY"] or any(k in text_lower for k in ["interest rate", "fixed deposit", "fees", "charges", "policy", "what is the limit", "savings rate"]):
            rag_res = await tool_gateway.execute_tool(
                agent_role=AgentRole.SUPPORT_AGENT.value,
                tool_name="search_knowledge_base",
                repo=repo,
                customer_id=customer_id,
                parameters={"query": last_msg, "limit": 2}
            )
            if rag_res.success and rag_res.data.get("results"):
                resp = build_kb_guidelines_response(rag_res.data["results"])
                return {
                    "active_workflow": "NONE",
                    "final_response": resp,
                    "messages": [AIMessage(content=resp)]
                }

        # 3. Transaction Dispute Investigation (CARD_PAYMENT_DECLINED, UPI_PAYMENT_FAILED, TRANSFER_FAILED, ATM_WITHDRAWAL_FAILED, FEE_DISPUTE, etc.)
        tx_match = re.search(r"\b(TXN-[A-Za-z0-9]+)\b", last_msg, re.IGNORECASE)
        target_tx = None

        if tx_match:
            tx_ref = tx_match.group(1).upper()
            result = await tool_gateway.execute_tool(
                agent_role=AgentRole.SUPPORT_AGENT.value,
                tool_name="get_transaction",
                repo=repo,
                customer_id=customer_id,
                parameters={"transaction_ref": tx_ref}
            )
            if result.success:
                target_tx = result.data
        else:
            recent_res = await tool_gateway.execute_tool(
                agent_role=AgentRole.SUPPORT_AGENT.value,
                tool_name="get_recent_transactions",
                repo=repo,
                customer_id=customer_id,
                parameters={"limit": 50}
            )
            if recent_res.success and recent_res.data.get("transactions"):
                for tx in recent_res.data["transactions"]:
                    if tx.get("status") in ["DECLINED", "FAILED"]:
                        target_tx = tx
                        break
                if not target_tx:
                    target_tx = recent_res.data["transactions"][0]

        if not target_tx:
            resp = "I could not locate any recent transactions for your account. Could you please provide the transaction reference ID?"
            return {
                "active_workflow": "NONE",
                "final_response": resp,
                "messages": [AIMessage(content=resp)]
            }

        tx_ref = target_tx.get("transaction_ref")
        status = target_tx.get("status")
        failure_code = target_tx.get("failure_reason") or "SYSTEM_POLICY_DENIAL"
        resp = build_transaction_dispute_response(
            tx_ref=tx_ref,
            status=status,
            failure_code=failure_code,
            amount=target_tx.get("amount", 0.0)
        )

        return {
            "active_workflow": "NONE",
            "final_response": resp,
            "messages": [AIMessage(content=resp)]
        }

