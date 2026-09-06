"""Chat conversation and ChatGPT-style session history API endpoints."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from langchain_core.messages import HumanMessage
from apps.api.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatSessionResponse,
    ChatMessageResponse,
    SessionListResponse,
    SessionDetailResponse
)
from agents.supervisor.graph import supervisor_graph_builder
from agents.supervisor.prompts import (
    build_chatgpt_style_fallback_response,
    build_system_error_fallback_response,
)
from checkpoints.checkpointer import get_checkpointer
from security.guardrails_engine import enterprise_guardrails
from services.cache.cache_engine import cache_engine
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from database.models.banking import Customer
from sqlalchemy import select
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])

import asyncio

_compiled_app = None
_compiled_app_loop = None


async def get_banking_app():
    global _compiled_app, _compiled_app_loop
    try:
        curr_loop = asyncio.get_running_loop()
    except RuntimeError:
        curr_loop = None

    if _compiled_app is None or _compiled_app_loop is not curr_loop:
        checkpointer = await get_checkpointer(use_postgres=True)
        _compiled_app = supervisor_graph_builder.compile(checkpointer=checkpointer)
        _compiled_app_loop = curr_loop
    return _compiled_app


@router.post("", response_model=ChatResponse)
async def handle_chat(request: ChatRequest):
    """
    Stateful conversational chat endpoint with automatic ChatGPT-style session persistence.
    """
    try:
        return await _handle_chat_impl(request)
    except HTTPException:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise


async def _handle_chat_impl(request: ChatRequest):
    # 1. Guardrails AI Input Guard (Prompt Injection & Secrets Defense)
    is_safe, violation_reason = enterprise_guardrails.validate_input(request.message)
    if not is_safe:
        logger.warn("Guardrails AI security violation detected in input", reason=violation_reason)
        return ChatResponse(
            response="I cannot process this request due to security and compliance policy restrictions.",
            thread_id=request.thread_id or str(uuid.uuid4()),
            active_workflow="NONE"
        )

    # 2. Session and Customer resolution
    thread_id = request.thread_id or f"TH-{uuid.uuid4().hex[:10]}"
    customer_external_id = request.customer_external_id or "CUST-1001"

    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        customer = await repo.get_customer_by_external_id(customer_external_id)
        if not customer:
            # Fallback: guest external_id may have been converted to CUST-XXXX
            # during account opening. Look up via existing session thread_id.
            from database.models.banking import ChatSession
            existing_session = (await session.execute(
                select(ChatSession).where(ChatSession.thread_id == thread_id)
            )).scalars().first()
            if existing_session:
                customer = await session.get(Customer, existing_session.customer_id)

        if not customer:
            if customer_external_id.startswith("GUEST") or customer_external_id.startswith("PROSPECT") or customer_external_id.startswith("NEW"):
                customer = Customer(
                    external_id=customer_external_id,
                    full_name="Guest Applicant",
                    email=f"{customer_external_id.lower()}@prospect.novabank.com",
                    phone="+910000000000",
                    kyc_status="PENDING",
                    risk_tier="LOW"
                )
                session.add(customer)
                await session.commit()
                await session.refresh(customer)
            else:
                raise HTTPException(status_code=404, detail="Customer not found")
        customer_id = customer.id
        customer_name = customer.full_name

        # Create session and record user message
        clean_title = request.message[:35] + ("..." if len(request.message) > 35 else "")
        await repo.get_or_create_session(thread_id=thread_id, customer_id=customer_id, title=clean_title)
        await repo.save_chat_message(
            thread_id=thread_id,
            customer_id=customer_id,
            role="user",
            content=request.message,
            active_workflow="NONE"
        )
        await session.commit()

        # 3. Check Redis Query Cache for identical/read-only queries (Sub-2ms response)
        cached_result = await cache_engine.get_cached_response(customer_id, request.message)
        if cached_result:
            cached_reply = cached_result["response"]
            cached_wf = cached_result.get("active_workflow", "NONE")
            await repo.save_chat_message(
                thread_id=thread_id,
                customer_id=customer_id,
                role="assistant",
                content=cached_reply,
                active_workflow=cached_wf
            )
            await repo.update_session(thread_id=thread_id, customer_id=customer_id)
            await session.commit()
            return ChatResponse(
                response=cached_reply,
                thread_id=thread_id,
                active_workflow=cached_wf
            )

    app = await get_banking_app()
    config = {"configurable": {"thread_id": thread_id}}

    # 4. Invoke LangGraph
    input_payload = {
        "messages": [HumanMessage(content=request.message)],
        "customer_id": customer_id,
        "customer_external_id": customer_external_id,
        "customer_name": customer_name,
        "widget_type": None,
        "widget_data": None,
        "kyc_payload": request.kyc_payload
    }

    try:
        final_state = await app.ainvoke(input_payload, config=config)
    except Exception as exc:
        logger.error("LangGraph turn execution error", error=str(exc))
        fallback_msg = build_system_error_fallback_response()
        safe_fallback = enterprise_guardrails.sanitize_output(fallback_msg)
        async with AsyncSessionLocal() as session:
            repo = BankingRepository(session)
            await repo.save_chat_message(
                thread_id=thread_id,
                customer_id=customer_id,
                role="assistant",
                content=safe_fallback,
                active_workflow="NONE"
            )
            await repo.update_session(thread_id=thread_id, customer_id=customer_id)
            await session.commit()
        return ChatResponse(
            response=safe_fallback,
            thread_id=thread_id,
            active_workflow="NONE"
        )

    # 4. Check if paused at HITL interrupt or pending confirmation
    snapshot = await app.aget_state(config)
    requires_action = None
    action_payload = None

    if snapshot.tasks and any(t.interrupts for t in snapshot.tasks):
        requires_action = "HITL_PENDING"
        interrupt_val = snapshot.tasks[0].interrupts[0].value
        action_payload = interrupt_val
        bot_reply = (
            "Your transaction requires compliance officer verification due to banking risk policy. "
            "Our security team has been alerted and is reviewing the request."
        )
    else:
        raw_reply = final_state.get("final_response")
        if not raw_reply or not str(raw_reply).strip():
            bot_reply = build_chatgpt_style_fallback_response(request.message, customer_name)
        else:
            bot_reply = raw_reply
        # Transfer confirmation check
        if final_state.get("active_workflow") == "TRANSFER_MONEY" and final_state.get("transfer_data", {}).get("step") == "CONFIRM":
            requires_action = "CONFIRMATION_REQUIRED"
            action_payload = {
                "action": "TRANSFER",
                "amount": final_state.get("transfer_data", {}).get("amount"),
                "beneficiary": final_state.get("transfer_data", {}).get("beneficiary_name")
            }
        # Bill payment confirmation check
        elif final_state.get("active_workflow") == "PAYMENT_ACTION" and final_state.get("payment_data", {}).get("step") == "CONFIRM":
            requires_action = "CONFIRMATION_REQUIRED"
            action_payload = {
                "action": "BILL_PAYMENT",
                "biller": final_state.get("payment_data", {}).get("biller_name"),
                "amount": final_state.get("payment_data", {}).get("amount")
            }
        # SIP mandate confirmation check
        elif final_state.get("active_workflow") == "WEALTH_ADVISORY" and final_state.get("wealth_data", {}).get("step") == "CONFIRM":
            requires_action = "CONFIRMATION_REQUIRED"
            action_payload = {
                "action": "SIP_MANDATE",
                "amount": final_state.get("wealth_data", {}).get("monthly_investment", 5000.0),
                "frequency": "MONTHLY"
            }

    # 5. Extract Generative UI Widgets (GenUI) directly from current turn execution
    widget_type = final_state.get("widget_type")
    widget_data = final_state.get("widget_data")

    # 6. Guardrails AI Output Guard (PII Anonymization & Data Sanitization)
    safe_reply = enterprise_guardrails.sanitize_output(bot_reply)
    active_wf = final_state.get("active_workflow", "NONE")

    # 7. Save assistant message and update session in database
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        await repo.save_chat_message(
            thread_id=thread_id,
            customer_id=customer_id,
            role="assistant",
            content=safe_reply,
            active_workflow=active_wf,
            requires_action=requires_action,
            action_payload=action_payload,
            widget_type=widget_type,
            widget_data=widget_data
        )
        await repo.update_session(thread_id=thread_id, customer_id=customer_id)
        await session.commit()

        # Cache response if eligible (e.g. balance, FAQ, policies) and not requiring confirmation
        if active_wf == "NONE" and not requires_action and not widget_type:
            await cache_engine.set_cached_response(
                customer_id=customer_id,
                query=request.message,
                response_payload={"response": safe_reply, "active_workflow": active_wf}
            )

    return ChatResponse(
        response=safe_reply,
        thread_id=thread_id,
        active_workflow=active_wf,
        requires_action=requires_action,
        action_payload=action_payload,
        widget_type=widget_type,
        widget_data=widget_data
    )


@router.get("/sessions", response_model=SessionListResponse)
async def list_chat_sessions(customer_external_id: str = Query("CUST-1001")):
    """Retrieves all conversation sessions for the customer just like ChatGPT sidebar."""
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        customer = await repo.get_customer_by_external_id(customer_external_id)
        if not customer:
            if customer_external_id.startswith("GUEST") or customer_external_id.startswith("PROSPECT") or customer_external_id.startswith("NEW"):
                return SessionListResponse(sessions=[])
            raise HTTPException(status_code=404, detail="Customer not found")

        sessions = await repo.list_sessions_by_customer(customer.id)
        return SessionListResponse(
            sessions=[
                ChatSessionResponse(
                    thread_id=s.thread_id,
                    title=s.title,
                    created_at=s.created_at.isoformat(),
                    updated_at=s.updated_at.isoformat()
                )
                for s in sessions
            ]
        )


@router.get("/sessions/{thread_id}", response_model=SessionDetailResponse)
async def get_session_history(thread_id: str, customer_external_id: str = Query("CUST-1001")):
    """Loads all messages in a conversation thread to restore ChatGPT conversation view."""
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        customer = await repo.get_customer_by_external_id(customer_external_id)
        if not customer:
            if customer_external_id.startswith("GUEST") or customer_external_id.startswith("PROSPECT") or customer_external_id.startswith("NEW"):
                return SessionDetailResponse(thread_id=thread_id, title="New Conversation", messages=[])
            raise HTTPException(status_code=404, detail="Customer not found")

        session_obj = await repo.get_session(thread_id, customer.id)
        if not session_obj:
            if customer_external_id.startswith("GUEST") or customer_external_id.startswith("PROSPECT") or customer_external_id.startswith("NEW"):
                return SessionDetailResponse(thread_id=thread_id, title="New Conversation", messages=[])
            raise HTTPException(status_code=404, detail="Chat session not found")

        messages = await repo.get_messages_by_thread(thread_id, customer.id)
        return SessionDetailResponse(
            thread_id=session_obj.thread_id,
            title=session_obj.title,
            messages=[
                ChatMessageResponse(
                    id=m.id,
                    role=m.role,
                    content=m.content,
                    active_workflow=m.active_workflow,
                    requires_action=m.requires_action,
                    action_payload=m.action_payload,
                    widget_type=m.widget_type,
                    widget_data=m.widget_data,
                    created_at=m.created_at.isoformat()
                )
                for m in messages
            ]
        )


@router.delete("/sessions/{thread_id}")
async def delete_chat_session(thread_id: str, customer_external_id: str = Query("CUST-1001")):
    """Deletes a chat session and clears its message history."""
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        customer = await repo.get_customer_by_external_id(customer_external_id)
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        deleted = await repo.delete_session(thread_id, customer.id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Session not found")

        await session.commit()
        return {"status": "deleted", "thread_id": thread_id}


@router.get("/guardian")
async def get_financial_guardian_alerts(customer_external_id: str = Query("CUST-1001")):
    """Proactive financial guardian alerts and upcoming due dates for session start."""
    return {
        "alerts": [
            {
                "id": "ALERT-BILL-01",
                "type": "UPCOMING_BILL",
                "title": "Tata Power Bill Due Soon",
                "message": "Your electricity bill of ₹2,450.00 is due in 3 days (10-Sep).",
                "action_prompt": "Pay Tata Power electricity bill"
            },
            {
                "id": "ALERT-PFM-02",
                "type": "SUBSCRIPTION_AUDIT",
                "title": "3 Active Subscriptions",
                "message": "Monthly recurring burn: ₹5,949.00 across Broadband, Power & Gym.",
                "action_prompt": "Show my subscriptions"
            }
        ]
    }


@router.get("/customers")
async def list_available_customers():
    """Returns available existing personas and guest onboarding mode for UI testing."""
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        # Fetch verified and active customer personas, newest first, filtering out transient guest rows
        query = (
            select(Customer)
            .where(~Customer.external_id.startswith("GUEST-PROSPECT-"))
            .order_by(Customer.id.desc())
            .limit(30)
        )
        res = await session.execute(query)
        custs = res.scalars().all()

        # Keep primary demo persona Amanpreet Singh at the top
        amanpreet = await repo.get_customer_by_external_id("CUST-1001")
        ordered_custs = [amanpreet] if amanpreet else []
        seen_ids = {"CUST-1001"}
        for c in custs:
            if c.external_id not in seen_ids and not c.external_id.startswith("GUEST-NAMEFIX"):
                seen_ids.add(c.external_id)
                ordered_custs.append(c)

        results = []
        for c in ordered_custs:
            accs = await repo.get_accounts_by_customer_id(c.id)
            primary_bal = max([a.balance for a in accs], default=0.0) if accs else 0.0
            results.append({
                "external_id": c.external_id,
                "name": c.full_name,
                "email": c.email,
                "kyc_status": c.kyc_status,
                "balance": primary_bal,
                "account_count": len(accs)
            })

        return {
            "customers": results,
            "guest_prospect": {
                "external_id": "GUEST-PROSPECT",
                "name": "Guest / New Applicant",
                "email": "prospect@novabank.com",
                "kyc_status": "UNREGISTERED",
                "balance": 0.0,
                "account_count": 0
            }
        }
