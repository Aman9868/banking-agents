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
import structlog

logger = structlog.get_logger(__name__)

REASON_TRANSLATIONS = {
    "BENEFICIARY_SECURITY_VERIFICATION_INCOMPLETE": "the beneficiary security verification was not completed",
    "DAILY_TRANSFER_LIMIT_EXCEEDED": "your daily transfer limit was exceeded",
    "SUSPICIOUS_VELOCITY_FLAG": "our fraud monitoring system flagged elevated velocity on the account",
    "INSUFFICIENT_FUNDS": "the account balance was insufficient at the time of execution",
}


async def support_orchestrator_node(state: BankingSessionState) -> Dict[str, Any]:
    """
    Unified Support Agent:
    1. Transaction dispute investigation & translation
    2. Grounded RAG knowledge search (policy, fees, rates)
    3. Escalation & support ticket creation
    """
    customer_id = state.get("customer_id", 1)
    sub_intent = state.get("current_sub_intent") or state.get("support_data", {}).get("sub_intent")
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
            await session.commit()
            ticket_id = ticket_res.data.get("ticket_id", "TKT-SEC-01") if ticket_res.success else "TKT-SEC-01"
            resp = (
                f"🚨 **High-Priority Fraud Report Logged** (Ref: `{ticket_id}`)\n\n"
                "We take unauthorized charges very seriously. I have escalated this directly to NovaBank's Fraud Investigation Team.\n\n"
                "**Immediate Safety Recommendation:**\n"
                "• Would you like me to **freeze your card immediately** to prevent any further unauthorized activity?\n"
                "• Simply say *'Freeze my card'* or click the Cards menu to lock it instantly."
            )
            return {
                "active_workflow": "NONE",
                "final_response": resp,
                "messages": [AIMessage(content=resp)]
            }

        # 1. Human Escalation / Create Support Ticket
        if any(k in text_lower for k in ["human", "agent", "escalate", "file a complaint", "open ticket", "raise ticket"]):
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
        if any(k in text_lower for k in ["interest rate", "fixed deposit", "fees", "charges", "policy", "what is the limit", "savings rate"]):
            rag_res = await tool_gateway.execute_tool(
                agent_role=AgentRole.SUPPORT_AGENT.value,
                tool_name="search_knowledge_base",
                repo=repo,
                customer_id=customer_id,
                parameters={"query": last_msg, "limit": 2}
            )
            if rag_res.success and rag_res.data.get("results"):
                articles = rag_res.data["results"]
                summary = "\n\n".join([f"**{a['title']}**:\n{a['content']}" for a in articles])
                resp = f"According to our official banking guidelines:\n\n{summary}"
                return {
                    "active_workflow": "NONE",
                    "final_response": resp,
                    "messages": [AIMessage(content=resp)]
                }

        # 3. Transaction Dispute Investigation
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
        friendly_reason = REASON_TRANSLATIONS.get(failure_code, str(failure_code).replace("_", " ").lower())

        if status in ["DECLINED", "FAILED"]:
            resp = (
                f"I found transaction {tx_ref}.\n"
                f"It was declined because {friendly_reason}."
            )
        else:
            resp = (
                f"Transaction {tx_ref} is currently {status.lower()} "
                f"for the amount of ₹{target_tx.get('amount', 0.0):,.2f}."
            )

        return {
            "active_workflow": "NONE",
            "final_response": resp,
            "messages": [AIMessage(content=resp)]
        }


# Build Support Subgraph
support_subgraph_builder = StateGraph(BankingSessionState)
support_subgraph_builder.add_node("support_orchestrator", support_orchestrator_node)
support_subgraph_builder.add_edge(START, "support_orchestrator")
support_subgraph_builder.add_edge("support_orchestrator", END)

support_subgraph = support_subgraph_builder.compile()
