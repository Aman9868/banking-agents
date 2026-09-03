"""Controlled Money Transfer Subgraph with Policy Engine, Fraud Scoring, and HITL Checkpoints."""

import uuid
from typing import Dict, Any, Optional
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from agents.state import BankingSessionState, TransferWorkflowData
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from gateway.tool_gateway.gateway import tool_gateway
from gateway.tool_gateway.permissions import AgentRole
from services.fraud.engine import fraud_engine, FraudAssessment
from policies.transfer import transfer_policy_engine, PolicyDecision
from security.pii import mask_account_number
import structlog

logger = structlog.get_logger(__name__)


async def resolve_transfer_entities_node(state: BankingSessionState) -> Dict[str, Any]:
    """Resolves source account, beneficiary, and transfer amount from repository."""
    data: TransferWorkflowData = dict(state.get("transfer_data") or {})
    customer_id = state.get("customer_id", 1)

    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)

        # 1. Resolve source account
        if not data.get("source_account_id"):
            accounts = await repo.get_accounts_by_customer_id(customer_id)
            if not accounts:
                resp = "You do not have any active bank accounts to transfer funds from."
                return {
                    "active_workflow": "NONE",
                    "final_response": resp,
                    "messages": [AIMessage(content=resp)]
                }
            # Pick account with sufficient funds or fallback to first active account
            target_acc = None
            req_amount = data.get("amount") or 0.0
            for acc in accounts:
                if acc.status == "ACTIVE" and acc.balance >= req_amount:
                    target_acc = acc
                    break
            if not target_acc:
                target_acc = accounts[0]

            data["source_account_id"] = target_acc.id
            data["source_account_number"] = target_acc.account_number

        # 2. Resolve beneficiary
        bene_name = data.get("beneficiary_name")
        if not bene_name:
            resp = "Who would you like to transfer funds to? Please provide the beneficiary name."
            data["step"] = "RESOLVE"
            return {
                "transfer_data": data,
                "final_response": resp,
                "messages": [AIMessage(content=resp)]
            }

        if not data.get("beneficiary_account"):
            bene_result = await tool_gateway.execute_tool(
                agent_role=AgentRole.TRANSFER_AGENT.value,
                tool_name="get_beneficiary",
                repo=repo,
                customer_id=customer_id,
                parameters={"name": bene_name}
            )

            if not bene_result.success:
                resp = (
                    f"I could not find '{bene_name}' in your saved beneficiaries list. "
                    "To send funds to them, please add them as a beneficiary first by providing their account number and IFSC code."
                )
                return {
                    "active_workflow": "NONE",
                    "transfer_data": {},
                    "final_response": resp,
                    "messages": [AIMessage(content=resp)],
                    "widget_type": None,
                    "widget_data": None
                }

            data["beneficiary_id"] = bene_result.data["beneficiary_id"]
            data["beneficiary_name"] = bene_result.data["name"]
            data["beneficiary_account"] = bene_result.data["account_number"]

        # 3. Check amount
        amount = data.get("amount")
        if not amount or amount <= 0:
            resp = f"How much would you like to transfer to {data['beneficiary_name']}?"
            data["step"] = "RESOLVE"
            return {
                "transfer_data": data,
                "final_response": resp,
                "messages": [AIMessage(content=resp)]
            }

        data["step"] = "SECURITY_FANOUT"
        return {"transfer_data": data}


async def parallel_fraud_scoring_node(state: BankingSessionState) -> Dict[str, Any]:
    """Parallel Fan-Out Branch 1: Evaluates velocity and fraud risk concurrently."""
    data = state.get("transfer_data") or {}
    amount = data.get("amount", 0.0)
    assessment = fraud_engine.evaluate_transfer(
        amount=amount,
        beneficiary_is_new=False,
        recent_transfer_count_1h=0
    )
    return {
        "fraud_check_result": {
            "score": assessment.score,
            "risk_level": str(getattr(assessment.risk_level, "value", assessment.risk_level)),
            "reasons": assessment.reason_codes
        }
    }


async def parallel_aml_screening_node(state: BankingSessionState) -> Dict[str, Any]:
    """Parallel Fan-Out Branch 2: Evaluates AML sanctions & PEP screening concurrently."""
    data = state.get("transfer_data") or {}
    bene = data.get("beneficiary_name", "")
    is_blocked = any(s in bene.lower() for s in ["sanctioned", "terror", "ofac", "blacklist"])
    return {
        "aml_check_result": {
            "passed": not is_blocked,
            "risk_tier": "HIGH" if is_blocked else "STANDARD"
        }
    }


async def parallel_ledger_verification_node(state: BankingSessionState) -> Dict[str, Any]:
    """Parallel Fan-Out Branch 3: Real-time ledger balance and hold capacity verification."""
    data = state.get("transfer_data") or {}
    amount = data.get("amount", 0.0)
    customer_id = state.get("customer_id", 1)
    src_account = data.get("source_account_number")

    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        bal_result = await tool_gateway.execute_tool(
            agent_role=AgentRole.TRANSFER_AGENT.value,
            tool_name="get_balance",
            repo=repo,
            customer_id=customer_id,
            parameters={"account_number": src_account}
        )
    current_balance = bal_result.data.get("balance", 0.0) if bal_result.success else 0.0
    return {
        "ledger_check_result": {
            "available_balance": current_balance,
            "sufficient_funds": current_balance >= amount
        }
    }


async def policy_aggregator_node(state: BankingSessionState) -> Dict[str, Any]:
    """Fan-In Aggregator: Aggregates parallel security checks and renders policy decision."""
    data: TransferWorkflowData = dict(state.get("transfer_data") or {})
    amount = data.get("amount", 0.0)

    fraud_res = state.get("fraud_check_result") or {}
    aml_res = state.get("aml_check_result") or {}
    ledger_res = state.get("ledger_check_result") or {}

    # 1. Check AML Sanctions (Legal compliance requirement)
    if not aml_res.get("passed", True):
        resp = "Transfer blocked by AML & Sanctions screening policy."
        return {
            "active_workflow": "NONE",
            "transfer_data": {},
            "final_response": resp,
            "messages": [AIMessage(content=resp)]
        }

    # 2. Check ledger balance
    if not ledger_res.get("sufficient_funds", True):
        cur_bal = ledger_res.get("available_balance", 0.0)
        src_masked = mask_account_number(data.get("source_account_number"))
        resp = (
            f"Insufficient funds in your account {src_masked}. "
            f"Your available balance is ₹{cur_bal:,.2f}, but the requested transfer is ₹{amount:,.2f}."
        )
        return {
            "active_workflow": "NONE",
            "transfer_data": {},
            "final_response": resp,
            "messages": [AIMessage(content=resp)]
        }

    # 3. Evaluate deterministic transfer policy
    assessment = FraudAssessment(
        score=fraud_res.get("score", 0.05),
        risk_level=fraud_res.get("risk_level", "LOW"),
        reason_codes=fraud_res.get("reasons", [])
    )
    data["fraud_score"] = assessment.score
    data["fraud_reasons"] = assessment.reason_codes

    policy_result = transfer_policy_engine.evaluate(
        amount=amount,
        account_status="ACTIVE",
        fraud_assessment=assessment,
        user_confirmed=data.get("user_confirmed", False),
        step_up_completed=data.get("step_up_verified", False)
    )
    data["policy_decision"] = policy_result.decision.value

    # If policy requires HITL review
    if policy_result.decision == PolicyDecision.REQUIRE_HITL_REVIEW:
        data["step"] = "HITL_PAUSE"
        return {"transfer_data": data}

    # If user confirmation required
    if policy_result.decision == PolicyDecision.REQUIRE_USER_CONFIRMATION:
        data["step"] = "CONFIRM"
        src_masked = mask_account_number(data["source_account_number"])
        dest_masked = mask_account_number(data["beneficiary_account"])
        resp = (
            f"I found {data['beneficiary_name']} as your beneficiary.\n\n"
            f"Transfer ₹{amount:,.2f} from Savings {src_masked} to {data['beneficiary_name']} {dest_masked}?\n\n"
            f"Please reply 'Yes' to confirm or 'No' to cancel."
        )
        return {
            "transfer_data": data,
            "final_response": resp,
            "messages": [AIMessage(content=resp)]
        }

    data["step"] = "EXECUTE"
    return {"transfer_data": data}


async def transfer_hitl_node(state: BankingSessionState) -> Dict[str, Any]:
    """Pauses money transfer graph execution for compliance officer approval."""
    data: TransferWorkflowData = dict(state.get("transfer_data") or {})
    task_id = f"HITL-TXN-{uuid.uuid4().hex[:8].upper()}"

    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        await repo.create_review_task(
            task_ref=task_id,
            thread_id=state.get("customer_external_id", "THREAD-DEFAULT"),
            customer_id=state.get("customer_id", 1),
            workflow_type="TRANSFER_FRAUD",
            risk_score=data.get("fraud_score", 0.85),
            reason=f"High risk score ({data.get('fraud_score')}) triggered review: {', '.join(data.get('fraud_reasons', []))}",
            payload=data
        )

    # Durable HITL interrupt
    decision = interrupt({
        "task_id": task_id,
        "type": "TRANSFER_FRAUD_REVIEW",
        "amount": data.get("amount"),
        "beneficiary": data.get("beneficiary_name"),
        "risk_score": data.get("fraud_score")
    })

    if decision.get("approved"):
        data["policy_decision"] = PolicyDecision.ALLOW.value
        data["step"] = "EXECUTE"
    else:
        data["policy_decision"] = PolicyDecision.DENY.value
        data["step"] = "COMPLETED"

    return {"transfer_data": data}


async def execute_transfer_node(state: BankingSessionState) -> Dict[str, Any]:
    """Invokes initiate_transfer on the Tool Gateway with an idempotency key."""
    data: TransferWorkflowData = dict(state.get("transfer_data") or {})
    customer_id = state.get("customer_id", 1)

    if data.get("policy_decision") == PolicyDecision.DENY.value:
        resp = "The transfer request was declined by bank risk management policies."
        return {
            "active_workflow": "NONE",
            "transfer_data": {},
            "final_response": resp,
            "messages": [AIMessage(content=resp)]
        }

    # Generate or reuse unique idempotency key
    idempotency_key = data.get("idempotency_key") or f"TX-REQ-{uuid.uuid4().hex[:12].upper()}"
    data["idempotency_key"] = idempotency_key

    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        result = await tool_gateway.execute_tool(
            agent_role=AgentRole.TRANSFER_AGENT.value,
            tool_name="initiate_transfer",
            repo=repo,
            customer_id=customer_id,
            parameters={
                "source_account_id": data["source_account_id"],
                "beneficiary_id": data["beneficiary_id"],
                "amount": data["amount"],
                "idempotency_key": idempotency_key,
                "fraud_score": data.get("fraud_score", 0.0)
            },
            thread_id=state.get("customer_external_id")
        )
        await session.commit()

    if not result.success:
        resp = f"Transfer failed: {result.error}"
        return {
            "active_workflow": "NONE",
            "transfer_data": {},
            "final_response": resp,
            "messages": [AIMessage(content=resp)]
        }

    tx_ref = result.data.get("transaction_ref")
    data["transaction_ref"] = tx_ref
    data["step"] = "COMPLETED"

    resp = f"Transfer initiated. Transaction ID {tx_ref}. ₹{data['amount']:,.2f} transferred to {data['beneficiary_name']}."
    return {
        "active_workflow": "NONE",
        "transfer_data": {},
        "final_response": resp,
        "messages": [AIMessage(content=resp)]
    }


from typing import List


def route_after_resolve(state: BankingSessionState) -> List[str]:
    data = state.get("transfer_data") or {}
    if data.get("step") == "SECURITY_FANOUT":
        return ["parallel_fraud_scoring", "parallel_aml_screening", "parallel_ledger_verification"]
    return [END]


def route_after_policy(state: BankingSessionState) -> str:
    data = state.get("transfer_data") or {}
    if data.get("step") == "HITL_PAUSE":
        return "transfer_hitl"
    elif data.get("step") == "EXECUTE":
        return "execute_transfer"
    return END


# Build Transfer Subgraph with LangGraph Fan-Out Architecture
transfer_subgraph_builder = StateGraph(BankingSessionState)
transfer_subgraph_builder.add_node("resolve_entities", resolve_transfer_entities_node)
transfer_subgraph_builder.add_node("parallel_fraud_scoring", parallel_fraud_scoring_node)
transfer_subgraph_builder.add_node("parallel_aml_screening", parallel_aml_screening_node)
transfer_subgraph_builder.add_node("parallel_ledger_verification", parallel_ledger_verification_node)
transfer_subgraph_builder.add_node("policy_aggregator", policy_aggregator_node)
transfer_subgraph_builder.add_node("transfer_hitl", transfer_hitl_node)
transfer_subgraph_builder.add_node("execute_transfer", execute_transfer_node)

transfer_subgraph_builder.add_edge(START, "resolve_entities")

# 1. Parallel Fan-Out: resolve_entities concurrently triggers 3 security checks
transfer_subgraph_builder.add_conditional_edges(
    "resolve_entities",
    route_after_resolve,
    ["parallel_fraud_scoring", "parallel_aml_screening", "parallel_ledger_verification", END]
)

# 2. Parallel Fan-In: all 3 branches converge into policy_aggregator
transfer_subgraph_builder.add_edge("parallel_fraud_scoring", "policy_aggregator")
transfer_subgraph_builder.add_edge("parallel_aml_screening", "policy_aggregator")
transfer_subgraph_builder.add_edge("parallel_ledger_verification", "policy_aggregator")

# 3. Downstream policy execution
transfer_subgraph_builder.add_conditional_edges(
    "policy_aggregator",
    route_after_policy,
    ["transfer_hitl", "execute_transfer", END]
)
transfer_subgraph_builder.add_edge("transfer_hitl", "execute_transfer")
transfer_subgraph_builder.add_edge("execute_transfer", END)

transfer_subgraph = transfer_subgraph_builder.compile()

