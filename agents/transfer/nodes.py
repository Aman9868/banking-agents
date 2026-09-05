"""Controlled Money Transfer Subgraph with Policy Engine, Fraud Scoring, and HITL Checkpoints."""

import uuid
import re
import json
from typing import Dict, Any, Optional
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from agents.state import BankingSessionState, TransferWorkflowData
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from gateway.tool_gateway.gateway import tool_gateway
from gateway.tool_gateway.permissions import AgentRole
from gateway.llm.client import llm_gateway
from services.fraud.engine import fraud_engine, FraudAssessment
from policies.transfer import transfer_policy_engine, PolicyDecision
from security.pii import mask_account_number
from security.validators import validate_account_number, validate_ifsc_code
from agents.transfer.prompts import build_transfer_entity_extraction_prompt
import structlog

logger = structlog.get_logger(__name__)


async def extract_transfer_entities_llm(
    last_msg: str,
    current_data: Dict[str, Any],
    previous_question: str = ""
) -> Dict[str, Any]:
    """Uses LLM routing tier for conversational entity extraction across multi-turn transfer flow."""
    if not last_msg or len(last_msg.strip()) < 2:
        return {}

    prompt = build_transfer_entity_extraction_prompt(current_data, previous_question, last_msg)

    try:
        res = await llm_gateway.invoke_chat([
            SystemMessage(content=prompt),
            HumanMessage(content=last_msg)
        ], model_tier="routing")

        content = res.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        parsed = json.loads(content)
        return {k: v for k, v in parsed.items() if v is not None}
    except Exception as exc:
        logger.warning("LLM transfer entity extraction fallback", error=str(exc))
        return {}


async def resolve_transfer_entities_node(state: BankingSessionState) -> Dict[str, Any]:
    """Resolves source account, beneficiary, and transfer amount from repository."""
    data: TransferWorkflowData = dict(state.get("transfer_data") or {})
    customer_id = state.get("customer_id", 1)

    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        last_msg = ""
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, HumanMessage) or getattr(msg, "type", None) == "human":
                last_msg = msg.content.strip()
                break

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

        # 0. Conversational Context & LLM Structured Entity Extraction
        prev_ai_q = ""
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, AIMessage) or getattr(msg, "type", None) == "ai":
                prev_ai_q = msg.content
                break

        llm_slots = await extract_transfer_entities_llm(last_msg, data, prev_ai_q)
        if llm_slots.get("beneficiary_name") and not data.get("beneficiary_name"):
            data["beneficiary_name"] = llm_slots["beneficiary_name"]
        if llm_slots.get("amount") and not data.get("amount"):
            try:
                data["amount"] = float(llm_slots["amount"])
            except (ValueError, TypeError):
                pass

        # 1. Extract candidate beneficiary account details and IFSC from message
        cand_acc = str(llm_slots["account_number"]) if llm_slots.get("account_number") else None
        if not cand_acc:
            acc_m = re.search(r"(?:acc(?:ount)?\s*(?:no|num|number)?\s*[-:=]?\s*)([A-Za-z0-9]+)\b", last_msg, re.IGNORECASE)
            if acc_m:
                cand_acc = acc_m.group(1).strip()
            elif not data.get("beneficiary_account"):
                raw_d = re.findall(r"\b(\d{3,24})\b", last_msg)
                for d in raw_d:
                    if data.get("amount") and float(d) == data.get("amount"):
                        continue
                    cand_acc = d
                    break

        cand_ifsc = str(llm_slots["ifsc_code"]).upper() if llm_slots.get("ifsc_code") else None
        if not cand_ifsc:
            ifsc_m = re.search(r"(?:ifsc(?:\s*code)?\s*[-:=]?\s*)([A-Za-z0-9]+)\b", last_msg, re.IGNORECASE)
            if ifsc_m:
                cand_ifsc = ifsc_m.group(1).upper().strip()
            elif not data.get("ifsc_code"):
                raw_tokens = re.findall(r"\b([A-Za-z0-9]{8,14})\b", last_msg)
                for tok in raw_tokens:
                    u = tok.upper()
                    if re.match(r"^[A-Z]{4}", u) and any(c.isdigit() for c in u) and u not in ["TRANSFER", "TXN", "CUST", "GUEST", "SAVINGS", "CURRENT"]:
                        if cand_acc and cand_acc.upper() == u:
                            continue
                        cand_ifsc = u
                        break



        # Validate extracted candidates
        acc_error = None
        if cand_acc:
            is_valid, cleaned_acc, acc_err = validate_account_number(cand_acc)
            if is_valid:
                data["beneficiary_account"] = cleaned_acc
            else:
                acc_error = acc_err
                data["beneficiary_account"] = None

        ifsc_error = None
        if cand_ifsc:
            is_valid, cleaned_ifsc, ifsc_err = validate_ifsc_code(cand_ifsc)
            if is_valid:
                data["ifsc_code"] = cleaned_ifsc
            else:
                ifsc_error = ifsc_err
                data["ifsc_code"] = None

        # Resolve beneficiary name
        bene_name = data.get("beneficiary_name")
        if not bene_name:
            name_m = re.search(r"\b(?:add|for|to|pay|send)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)", last_msg, re.IGNORECASE)
            if name_m:
                bene_name = name_m.group(1).strip()
                data["beneficiary_name"] = bene_name
            elif state.get("customer_memory", {}).get("last_beneficiary_name"):
                bene_name = state["customer_memory"]["last_beneficiary_name"]
                data["beneficiary_name"] = bene_name
            elif data.get("step") == "RESOLVE":
                # User replied directly to "Who would you like to transfer funds to?"
                cleaned = re.sub(r"[^A-Za-z\s]", "", last_msg).strip()
                words = cleaned.split()
                if words and len(words) <= 3 and not any(w.lower() in ["hi", "hello", "hey", "yes", "no", "cancel", "stop", "transfer", "money", "upi", "pay"] for w in words):
                    bene_name = " ".join(w.capitalize() for w in words)
                    data["beneficiary_name"] = bene_name

        # Check if user mentioned a saved beneficiary's first or full name
        if not bene_name:
            saved_benes = await repo.get_beneficiaries(customer_id)
            for sb in saved_benes:
                first_name = sb.name.split()[0].lower()
                if first_name in last_msg.lower() or sb.name.lower() in last_msg.lower():
                    bene_name = sb.name
                    data["beneficiary_name"] = bene_name
                    data["beneficiary_id"] = sb.id
                    data["beneficiary_account"] = sb.account_number
                    data["ifsc_code"] = sb.ifsc_code
                    break

        # Cross-reference saved beneficiaries if beneficiary_id is not yet set
        if bene_name and not data.get("beneficiary_id"):
            matched_bene = await repo.find_beneficiary_by_name(customer_id, bene_name)
            if matched_bene:
                data["beneficiary_id"] = matched_bene.id
                data["beneficiary_name"] = matched_bene.name
                data["beneficiary_account"] = matched_bene.account_number
                data["ifsc_code"] = matched_bene.ifsc_code

        if not bene_name:
            resp = "Who would you like to transfer funds to? Please provide the beneficiary name."
            data["step"] = "RESOLVE"
            return {
                "active_workflow": "TRANSFER_MONEY",
                "transfer_data": data,
                "final_response": resp,
                "messages": [AIMessage(content=resp)]
            }

        # 3. Handle validation errors with user-friendly corrective guidance
        if acc_error or ifsc_error:
            data["step"] = "ADD_BENEFICIARY"
            if acc_error and ifsc_error:
                err_resp = (
                    f"⚠️ **Invalid details provided for {bene_name}:**\n"
                    f"• {acc_error}\n"
                    f"• {ifsc_error}\n\n"
                    "Please provide a valid Account Number (9–18 digits) and an 11-character IFSC Code (e.g. SBIN0001234 or NOVA0001001)."
                )
            elif acc_error:
                if data.get("ifsc_code"):
                    err_resp = (
                        f"Recorded IFSC Code **{data['ifsc_code']}** for **{bene_name}**.\n\n"
                        f"⚠️ {acc_error}\n\n"
                        f"Please provide a valid Account Number (9–18 digits) for {bene_name}."
                    )
                else:
                    err_resp = (
                        f"⚠️ {acc_error}\n\n"
                        f"Please provide a valid Account Number (9–18 digits) for {bene_name}."
                    )
            else:
                if data.get("beneficiary_account"):
                    err_resp = (
                        f"Recorded Account Number **{data['beneficiary_account']}** for **{bene_name}**.\n\n"
                        f"⚠️ {ifsc_error}\n\n"
                        "Please provide a valid 11-character IFSC Code (e.g. SBIN0001234 or NOVA0001001)."
                    )
                else:
                    err_resp = (
                        f"⚠️ {ifsc_error}\n\n"
                        "Please provide a valid 11-character IFSC Code (e.g. SBIN0001234 or NOVA0001001)."
                    )

            return {
                "active_workflow": "TRANSFER_MONEY",
                "transfer_data": data,
                "final_response": err_resp,
                "messages": [AIMessage(content=err_resp)],
                "widget_type": None,
                "widget_data": None
            }

        # 4. Multi-Turn Slot Filling: Check if one required piece is still missing
        has_acc = bool(data.get("beneficiary_account"))
        has_ifsc = bool(data.get("ifsc_code"))

        # Case A: User provided Account Number, but no IFSC Code yet
        if has_acc and not has_ifsc:
            data["step"] = "ADD_BENEFICIARY"
            resp = (
                f"I have recorded account number **{data['beneficiary_account']}** for **{bene_name}**. "
                "Please provide their **11-character IFSC Code** (e.g. SBIN0001234 or NOVA0001001) to complete adding them as a beneficiary."
            )
            return {
                "active_workflow": "TRANSFER_MONEY",
                "transfer_data": data,
                "final_response": resp,
                "messages": [AIMessage(content=resp)],
                "widget_type": None,
                "widget_data": None
            }

        # Case B: User provided IFSC Code, but no Account Number yet
        if has_ifsc and not has_acc:
            data["step"] = "ADD_BENEFICIARY"
            resp = (
                f"I have recorded IFSC code **{data['ifsc_code']}** for **{bene_name}**. "
                "Please provide their **Account Number** (9 to 18 digits) to complete adding them as a beneficiary."
            )
            return {
                "active_workflow": "TRANSFER_MONEY",
                "transfer_data": data,
                "final_response": resp,
                "messages": [AIMessage(content=resp)],
                "widget_type": None,
                "widget_data": None
            }

        # 5. Both Account Number & IFSC are present and valid -> Register in repository
        if has_acc and has_ifsc and not data.get("beneficiary_id"):
            add_res = await tool_gateway.execute_tool(
                agent_role=AgentRole.TRANSFER_AGENT.value,
                tool_name="add_beneficiary",
                repo=repo,
                customer_id=customer_id,
                parameters={
                    "name": bene_name,
                    "account_number": data["beneficiary_account"],
                    "ifsc_code": data["ifsc_code"]
                }
            )
            if add_res.success:
                data["beneficiary_id"] = add_res.data["beneficiary_id"]
                data["beneficiary_name"] = add_res.data["name"]
                data["beneficiary_account"] = add_res.data["account_number"]
                data["ifsc_code"] = add_res.data["ifsc_code"]
                data["just_added"] = True
                await session.commit()

        # 6. If beneficiary is not yet registered, check if already in repository
        if not data.get("beneficiary_id"):
            bene_result = await tool_gateway.execute_tool(
                agent_role=AgentRole.TRANSFER_AGENT.value,
                tool_name="get_beneficiary",
                repo=repo,
                customer_id=customer_id,
                parameters={"name": bene_name}
            )

            if not bene_result.success:
                data["step"] = "ADD_BENEFICIARY"
                data["beneficiary_name"] = bene_name
                resp = (
                    f"I could not find '{bene_name}' in your saved beneficiaries list. "
                    f"To add {bene_name} as a new beneficiary and proceed with this transfer, "
                    "please provide their **Account Number** and **IFSC Code** (e.g. 'Acc No-201010101010 IFSC Code-SBIN0001234')."
                )
                return {
                    "active_workflow": "TRANSFER_MONEY",
                    "transfer_data": data,
                    "final_response": resp,
                    "messages": [AIMessage(content=resp)],
                    "widget_type": None,
                    "widget_data": None
                }

            data["beneficiary_id"] = bene_result.data["beneficiary_id"]
            data["beneficiary_name"] = bene_result.data["name"]
            data["beneficiary_account"] = bene_result.data["account_number"]
            data["ifsc_code"] = bene_result.data.get("ifsc_code", "NOVA0001001")


        # 5. Check transfer amount
        amount = data.get("amount")
        if not amount or amount <= 0:
            # Try to extract amount from current message if user just replied with a number or amount
            amt_m = re.search(r"(?:rs\.?|inr|₹|\bamount\b\s*[:=]?)\s*([\d,]+(?:\.\d+)?)\b", last_msg, re.IGNORECASE)
            if amt_m:
                try:
                    amount = float(amt_m.group(1).replace(",", ""))
                    data["amount"] = amount
                except ValueError:
                    pass
            elif data.get("step") == "RESOLVE" and data.get("beneficiary_name"):
                num_m = re.search(r"\b(\d+(?:,\d+)*(?:\.\d+)?)\s*(k|lakh|lac|cr)?\b", last_msg, re.IGNORECASE)
                if num_m:
                    val = float(num_m.group(1).replace(",", ""))
                    mult = num_m.group(2)
                    if mult:
                        m_lower = mult.lower()
                        if m_lower == "k": val *= 1000
                        elif m_lower in ["lakh", "lac"]: val *= 100000
                        elif m_lower == "cr": val *= 10000000
                    amount = val
                    data["amount"] = amount

        if not amount or amount <= 0:
            if data.get("just_added"):
                masked_acc = mask_account_number(data["beneficiary_account"])
                resp = (
                    f"Beneficiary **{data['beneficiary_name']}** (Account: {masked_acc}, IFSC: {data.get('ifsc_code', 'NOVA0001001')}) "
                    "has been successfully registered! You can now send funds to them at any time."
                )
                return {
                    "active_workflow": "NONE",
                    "transfer_data": {},
                    "final_response": resp,
                    "messages": [AIMessage(content=resp)],
                    "widget_type": None,
                    "widget_data": None
                }
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
        bene_name = data['beneficiary_name']
        prefix = f"Beneficiary **{bene_name}** has been registered successfully.\n\n" if data.get("just_added") else f"I found {bene_name} as your beneficiary.\n\n"
        resp = (
            f"{prefix}"
            f"Transfer ₹{amount:,.2f} from Savings {src_masked} to {bene_name} ({dest_masked})?\n\n"
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

