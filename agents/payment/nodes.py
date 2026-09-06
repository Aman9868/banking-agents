"""Bill Payments and UPI Subgraph with Two-Phase Confirmation and Idempotency."""

import uuid
import re
from typing import Dict, Any
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState, PaymentWorkflowData
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from gateway.tool_gateway.gateway import tool_gateway
from gateway.tool_gateway.permissions import AgentRole
from security.pii import mask_account_number
from agents.payment.prompts import (
    build_upi_verified_response,
    build_bill_details_prompt,
)
import structlog

logger = structlog.get_logger(__name__)


async def payment_orchestrator_node(state: BankingSessionState) -> Dict[str, Any]:
    """Manages bill discovery, bill fetching, user confirmation, and payment execution."""
    customer_id = state.get("customer_id", 1)
    data: PaymentWorkflowData = dict(state.get("payment_data") or {})

    last_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_msg = msg.content.strip()
            break

    text_lower = last_msg.lower()
    sub_intent = (state.get("current_sub_intent") or "").upper()

    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)

        # 1. UPI Payment Handler
        if sub_intent == "UPI_PAYMENT" or ("@" in last_msg and any(k in text_lower for k in ["upi", "pay", "send"])):
            upi_match = re.search(r"([\w\.\-]+@[\w\-]+)", last_msg)
            if upi_match:
                upi_id = upi_match.group(1)
                res = await tool_gateway.execute_tool(
                    agent_role=AgentRole.PAYMENTS_AGENT.value,
                    tool_name="verify_upi_id",
                    repo=repo,
                    customer_id=customer_id,
                    parameters={"upi_id": upi_id}
                )
                if res.success:
                    resp = build_upi_verified_response(upi_id, res.data.get("resolved_name", "Registered User"))
                else:
                    resp = res.error
                return {
                    "active_workflow": "NONE",
                    "payment_data": {},
                    "final_response": resp,
                    "messages": [AIMessage(content=resp)]
                }

        # 2. Check if user is confirming an existing pending bill payment
        if data.get("step") == "CONFIRM" and data.get("user_confirmed"):
            idemp_key = f"BIL-REQ-{uuid.uuid4().hex[:12].upper()}"
            res = await tool_gateway.execute_tool(
                agent_role=AgentRole.PAYMENTS_AGENT.value,
                tool_name="pay_bill",
                repo=repo,
                customer_id=customer_id,
                parameters={
                    "biller_name": data["biller_name"],
                    "consumer_number": data["consumer_number"],
                    "amount": data["amount"],
                    "source_account_id": data["source_account_id"],
                    "idempotency_key": idemp_key
                }
            )
            await session.commit()

            if res.success:
                resp = res.data["message"]
            else:
                resp = f"Bill payment failed: {res.error}"

            return {
                "active_workflow": "NONE",
                "payment_data": {},
                "final_response": resp,
                "messages": [AIMessage(content=resp)],
                "widget_type": "TRANSACTION_RECEIPT" if res.success else None,
                "widget_data": {
                    "type": "BILL_PAYMENT",
                    "reference": idemp_key,
                    "amount": data.get("amount", 0.0),
                    "biller": data.get("biller_name", "Biller"),
                    "status": "SUCCESS"
                } if res.success else None
            }

        # 3. New Bill Payment Request - Fetch details
        biller_name = data.get("biller_name")
        if not biller_name:
            if sub_intent == "ELECTRICITY_BILL" or "electric" in text_lower or "power" in text_lower:
                biller_name = "Tata Power"
            elif sub_intent == "BROADBAND_BILL" or "airtel" in text_lower or "broadband" in text_lower:
                biller_name = "Airtel Broadband"
            elif sub_intent == "CREDIT_CARD_BILL" or "credit" in text_lower or "card bill" in text_lower:
                biller_name = "HDFC Credit Card Bill"
            else:
                biller_name = "Tata Power"

        consumer_num = data.get("consumer_number") or "CONS-882910"
        data["biller_name"] = biller_name
        data["consumer_number"] = consumer_num

        # Fetch bill
        bill_res = await tool_gateway.execute_tool(
            agent_role=AgentRole.PAYMENTS_AGENT.value,
            tool_name="fetch_bill",
            repo=repo,
            customer_id=customer_id,
            parameters={"biller_name": biller_name, "consumer_number": consumer_num}
        )

        if not bill_res.success:
            resp = f"Could not fetch bill: {bill_res.error}"
            return {
                "active_workflow": "NONE",
                "payment_data": {},
                "final_response": resp,
                "messages": [AIMessage(content=resp)]
            }

        bill_amount = bill_res.data["amount_due"]
        data["amount"] = bill_amount

        # Resolve primary account
        accounts = await repo.get_accounts_by_customer_id(customer_id)
        if not accounts:
            resp = "No active bank accounts found to pay bills."
            return {
                "active_workflow": "NONE",
                "payment_data": {},
                "final_response": resp,
                "messages": [AIMessage(content=resp)]
            }

        target_acc = None
        for acc in accounts:
            if acc.status == "ACTIVE" and acc.balance >= bill_amount:
                target_acc = acc
                break
        if not target_acc:
            target_acc = accounts[0]

        data["source_account_id"] = target_acc.id
        data["source_account_number"] = target_acc.account_number
        data["step"] = "CONFIRM"

        masked_acc = mask_account_number(target_acc.account_number)
        resp = (
            f"Found bill for {biller_name} (Consumer No: {consumer_num}).\n\n"
            f"• Amount Due: ₹{bill_amount:,.2f}\n"
            f"• Due Date: {bill_res.data.get('due_date', 'Immediate')}\n"
            f"• Pay from: {target_acc.account_type.capitalize()} Account {masked_acc}\n\n"
            f"Do you want to proceed with this bill payment?\n"
            f"Please reply 'Yes' to confirm or 'No' to cancel."
        )

        return {
            "active_workflow": "PAYMENT_ACTION",
            "payment_data": data,
            "final_response": resp,
            "messages": [AIMessage(content=resp)]
        }

