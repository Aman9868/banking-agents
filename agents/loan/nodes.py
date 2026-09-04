"""Loan Advisory, EMI Calculation, and Application Subgraph."""

import re
from typing import Dict, Any
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState, LoanWorkflowData
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from gateway.tool_gateway.gateway import tool_gateway
from gateway.tool_gateway.permissions import AgentRole
import structlog

logger = structlog.get_logger(__name__)


async def loan_orchestrator_node(state: BankingSessionState) -> Dict[str, Any]:
    """Handles EMI calculations, eligibility evaluations, and loan applications."""
    customer_id = state.get("customer_id", 1)
    loan_data = dict(state.get("loan_data") or {})

    last_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_msg = msg.content.strip()
            break

    text_lower = last_msg.lower()

    # Extract slots from message
    amount = loan_data.get("amount")
    if not amount:
        # Check for numeric or Indian lakh/crore notation
        lakh_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|lac)s?", text_lower)
        if lakh_match:
            amount = float(lakh_match.group(1)) * 100000.0
        else:
            std_num = re.search(r"(?:₹|rs\.?)?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]{4,})", text_lower)
            if std_num:
                amount = float(std_num.group(1).replace(",", ""))

    tenure_months = loan_data.get("tenure_months")
    if not tenure_months:
        yr_match = re.search(r"(\d+)\s*(?:years?|yrs?)", text_lower)
        if yr_match:
            tenure_months = int(yr_match.group(1)) * 12
        else:
            mo_match = re.search(r"(\d+)\s*(?:months?|mths?)", text_lower)
            if mo_match:
                tenure_months = int(mo_match.group(1))

    loan_type = "PERSONAL"
    if "home" in text_lower:
        loan_type = "HOME"
    elif "car" in text_lower or "auto" in text_lower:
        loan_type = "AUTO"

    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)

        # Case 1: Loan Application Submission
        if any(k in text_lower for k in ["apply", "submit application", "proceed with loan"]):
            req_amount = amount or 300000.0
            req_tenure = tenure_months or 36
            res = await tool_gateway.execute_tool(
                agent_role=AgentRole.LOAN_AGENT.value,
                tool_name="apply_loan",
                repo=repo,
                customer_id=customer_id,
                parameters={
                    "loan_type": loan_type,
                    "amount": req_amount,
                    "tenure_months": req_tenure,
                    "annual_income": 900000.0,
                    "annual_rate_pct": 8.75 if loan_type == "HOME" else 10.5
                }
            )
            resp = res.data.get("message", "Loan application submitted.")
            return {
                "active_workflow": "NONE",
                "loan_data": {},
                "final_response": resp,
                "messages": [AIMessage(content=resp)]
            }

        # Case 2: Loan Eligibility Evaluation
        if any(k in text_lower for k in ["eligible", "eligibility"]):
            req_amount = amount or 500000.0
            req_tenure = tenure_months or 36
            res = await tool_gateway.execute_tool(
                agent_role=AgentRole.LOAN_AGENT.value,
                tool_name="check_loan_eligibility",
                repo=repo,
                customer_id=customer_id,
                parameters={
                    "monthly_income": 75000.0,
                    "existing_emi": 5000.0,
                    "requested_amount": req_amount,
                    "tenure_months": req_tenure,
                    "annual_rate_pct": 10.5
                }
            )
            resp = res.data.get("message")
            return {
                "active_workflow": "NONE",
                "loan_data": {},
                "final_response": resp,
                "messages": [AIMessage(content=resp)]
            }

        # Case 3: EMI Calculation & General Inquiry
        calc_principal = amount or 500000.0
        calc_tenure = tenure_months or 36
        interest_rate = 8.75 if loan_type == "HOME" else 10.50

        res = await tool_gateway.execute_tool(
            agent_role=AgentRole.LOAN_AGENT.value,
            tool_name="calculate_emi",
            repo=repo,
            customer_id=customer_id,
            parameters={
                "principal": calc_principal,
                "tenure_months": calc_tenure,
                "annual_rate_pct": interest_rate
            }
        )

        emi_data = res.data
        resp = (
            f"Here is your {loan_type.capitalize()} Loan estimate:\n\n"
            f"• Loan Amount: ₹{calc_principal:,.2f}\n"
            f"• Interest Rate: {interest_rate:.2f}% p.a.\n"
            f"• Tenure: {calc_tenure} months ({calc_tenure // 12} years)\n"
            f"• Estimated Monthly EMI: ₹{emi_data['monthly_emi']:,.2f}\n"
            f"• Total Interest: ₹{emi_data['total_interest']:,.2f}\n"
            f"• Total Payable: ₹{emi_data['total_payable']:,.2f}\n\n"
            f"Would you like to check your eligibility or submit an application today?"
        )

    return {
        "active_workflow": "NONE",
        "loan_data": {
            "amount": calc_principal,
            "tenure_months": calc_tenure,
            "monthly_emi": emi_data["monthly_emi"]
        },
        "final_response": resp,
        "messages": [AIMessage(content=resp)],
        "widget_type": "EMI_SLIDER",
        "widget_data": {
            "amount": calc_principal,
            "tenure_months": calc_tenure,
            "interest_rate": interest_rate,
            "monthly_emi": emi_data["monthly_emi"]
        }
    }

