"""Conversational Account Opening Subgraph and State Machine."""

import uuid
from typing import Dict, Any
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from agents.state import BankingSessionState, AccountWorkflowData
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from database.models.banking import Customer, Account
from sqlalchemy import select
import structlog

logger = structlog.get_logger(__name__)


async def collect_profile_node(state: BankingSessionState) -> Dict[str, Any]:
    """Inspects missing slots in account application and prompts customer or advances state."""
    data: AccountWorkflowData = dict(state.get("account_data") or {})

    # Extract info from last message if applicable
    last_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_msg = msg.content.strip()
            break

    # If currently expecting a specific slot
    current_step = data.get("step")
    is_opening_trigger = any(k in last_msg.lower() for k in ["open", "account", "savings", "current", "apply", "register", "novabank"])

    if current_step == "NAME" and not data.get("full_name") and last_msg and not is_opening_trigger:
        data["full_name"] = last_msg
        data["step"] = "DOB"
    elif current_step == "DOB" and not data.get("date_of_birth") and last_msg:
        data["date_of_birth"] = last_msg
        data["step"] = "EMAIL"
    elif current_step == "EMAIL" and not data.get("email") and last_msg:
        data["email"] = last_msg
        data["step"] = "TYPE"
    elif current_step == "TYPE" and not data.get("account_type") and last_msg:
        data["account_type"] = "CURRENT" if "current" in last_msg.lower() else "SAVINGS"
        data["step"] = "KYC"

    # Determine what is missing next
    if not data.get("full_name"):
        data["step"] = "NAME"
        data["account_type"] = data.get("account_type", "SAVINGS")
        resp = "Absolutely! I can help you open a new bank account. May I have your full name?"
        return {
            "account_data": data,
            "final_response": resp,
            "messages": [AIMessage(content=resp)]
        }

    if not data.get("date_of_birth"):
        data["step"] = "DOB"
        resp = f"Thanks, {data['full_name']}. What is your date of birth?"
        return {
            "account_data": data,
            "final_response": resp,
            "messages": [AIMessage(content=resp)]
        }

    if not data.get("email"):
        data["step"] = "EMAIL"
        resp = "What email address would you like to use for your account?"
        return {
            "account_data": data,
            "final_response": resp,
            "messages": [AIMessage(content=resp)]
        }

    # All slots collected! Ready for KYC/AML
    data["step"] = "KYC"
    return {"account_data": data}


async def kyc_aml_node(state: BankingSessionState) -> Dict[str, Any]:
    """Runs deterministic KYC verification and AML watchlist screening."""
    data: AccountWorkflowData = dict(state.get("account_data") or {})

    # Simulate deterministic KYC check (Passes for valid profile)
    data["kyc_status"] = "VERIFIED"

    # Deterministic AML check
    # If customer name contains "PEP" or "Sanction", flag for HITL
    name = data.get("full_name", "")
    if "sanction" in name.lower() or "pep" in name.lower():
        data["aml_status"] = "FLAGGED"
        data["risk_level"] = "HIGH"
    else:
        data["aml_status"] = "CLEAR"
        data["risk_level"] = "LOW"

    return {"account_data": data}


async def aml_hitl_node(state: BankingSessionState) -> Dict[str, Any]:
    """Pauses graph execution via LangGraph interrupt() when high-risk AML is detected."""
    data: AccountWorkflowData = dict(state.get("account_data") or {})
    task_id = f"HITL-KYC-{uuid.uuid4().hex[:8].upper()}"

    # Record review task in database
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        await repo.create_review_task(
            task_ref=task_id,
            thread_id=state.get("customer_external_id", "THREAD-DEFAULT"),
            customer_id=state.get("customer_id", 1),
            workflow_type="ACCOUNT_KYC",
            risk_score=0.92,
            reason="AML screening flagged potential PEP/Watchlist match.",
            payload=data
        )

    # LangGraph human-in-the-loop checkpoint pause
    review_decision = interrupt({
        "task_id": task_id,
        "type": "AML_COMPLIANCE_REVIEW",
        "applicant": data.get("full_name"),
        "reason": "AML screening flagged potential PEP/Watchlist match."
    })

    if review_decision.get("approved"):
        data["aml_status"] = "CLEAR"
        data["risk_level"] = "LOW"
    else:
        data["aml_status"] = "REJECTED"

    return {"account_data": data}


async def create_account_node(state: BankingSessionState) -> Dict[str, Any]:
    """Provisions the account in Core Banking database upon successful checks."""
    data: AccountWorkflowData = dict(state.get("account_data") or {})

    if data.get("aml_status") == "REJECTED":
        resp = "We regret to inform you that your account application could not be approved following compliance review."
        data["step"] = "COMPLETED"
        return {
            "account_data": data,
            "active_workflow": "NONE",
            "final_response": resp,
            "messages": [AIMessage(content=resp)]
        }

    # Provision account
    new_acc_num = f"SB{uuid.uuid4().int % 100000000:08d}"
    data["account_number"] = new_acc_num
    data["step"] = "COMPLETED"

    assigned_cust_ext_id = state.get("customer_external_id", "CUST-1001")

    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        cust_id = state.get("customer_id", 1)
        cust = await session.get(Customer, cust_id)
        if cust:
            if data.get("full_name"):
                cust.full_name = data.get("full_name")
            if data.get("email"):
                existing_res = await session.execute(
                    select(Customer).where(Customer.email == data.get("email"), Customer.id != cust_id)
                )
                if not existing_res.scalar_one_or_none():
                    cust.email = data.get("email")
            if data.get("date_of_birth"):
                cust.date_of_birth = data.get("date_of_birth")
            cust.kyc_status = "VERIFIED"
            if cust.external_id.startswith("GUEST") or cust.external_id.startswith("PROSPECT") or cust.external_id.startswith("NEW"):
                cust.external_id = f"CUST-{uuid.uuid4().int % 9000 + 1000}"
            assigned_cust_ext_id = cust.external_id

        # Create account record for customer
        account = Account(
            customer_id=cust_id,
            account_number=new_acc_num,
            account_type=data.get("account_type", "SAVINGS"),
            balance=0.0,
            currency="INR",
            status="ACTIVE"
        )
        session.add(account)
        await repo.log_audit(
            event_type="ACCOUNT_CREATED",
            agent_id="account_agent",
            customer_id=cust_id,
            thread_id=None,
            payload={"account_number": new_acc_num, "type": data.get("account_type"), "customer_external_id": assigned_cust_ext_id}
        )
        await session.commit()

    resp = (
        f"Congratulations {data.get('full_name')}! Your KYC is complete. "
        f"Your {data.get('account_type', 'SAVINGS')} account {new_acc_num} has been successfully opened."
    )
    return {
        "account_data": data,
        "active_workflow": "NONE",
        "final_response": resp,
        "messages": [AIMessage(content=resp)],
        "widget_type": "ACCOUNT_CARD",
        "widget_data": {
            "account_number": new_acc_num,
            "account_type": data.get("account_type", "SAVINGS"),
            "full_name": data.get("full_name", "Valued Customer"),
            "customer_external_id": assigned_cust_ext_id,
            "ifsc_code": "NOVA0001001",
            "branch": "NovaBank Digital Branch",
            "status": "ACTIVE & KYC VERIFIED",
            "balance": 0.0
        }
    }


def route_after_profile(state: BankingSessionState) -> str:
    data = state.get("account_data") or {}
    if data.get("step") == "KYC":
        return "kyc_aml"
    return END


def route_after_aml(state: BankingSessionState) -> str:
    data = state.get("account_data") or {}
    if data.get("aml_status") == "FLAGGED":
        return "aml_hitl"
    return "create_account"


# Build Account Subgraph
account_subgraph_builder = StateGraph(BankingSessionState)
account_subgraph_builder.add_node("collect_profile", collect_profile_node)
account_subgraph_builder.add_node("kyc_aml", kyc_aml_node)
account_subgraph_builder.add_node("aml_hitl", aml_hitl_node)
account_subgraph_builder.add_node("create_account", create_account_node)

account_subgraph_builder.add_edge(START, "collect_profile")
account_subgraph_builder.add_conditional_edges("collect_profile", route_after_profile, ["kyc_aml", END])
account_subgraph_builder.add_conditional_edges("kyc_aml", route_after_aml, ["aml_hitl", "create_account"])
account_subgraph_builder.add_edge("aml_hitl", "create_account")
account_subgraph_builder.add_edge("create_account", END)

account_subgraph = account_subgraph_builder.compile()

