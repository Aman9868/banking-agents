"""Tests for Production-Grade Intent Classification, Sub-Intents, Negation, Typo Resilience, and Semantic Cache."""

import pytest
from langchain_core.messages import HumanMessage
from gateway.llm.router import (
    route_banking_request,
    BankingIntent,
    BankingSubIntent,
    classify_intent,
    extract_slots
)
from services.cache.cache_engine import cache_engine
from agents.supervisor.graph import supervisor_graph_builder
from checkpoints.checkpointer import get_checkpointer


@pytest.mark.asyncio
async def test_negation_detection_prevents_accidental_action():
    """Verify that sentences with negations do NOT trigger mutating transfers or actions."""
    negation_msg = "I don't want to transfer money right now"
    decision = await route_banking_request(negation_msg)

    assert decision.negation_detected is True
    # The intent should NOT be TRANSFER_MONEY
    assert decision.intent != BankingIntent.TRANSFER_MONEY

    # Verify adapter also reflects this safety guarantee
    legacy_intent = await classify_intent(negation_msg)
    assert legacy_intent != "TRANSFER_MONEY"


@pytest.mark.asyncio
async def test_typo_and_slang_resilience():
    """Verify that typos like 'trnasfer', 'balence', 'freze' are accurately resolved."""
    # Typo in transfer
    res_transfer = await route_banking_request("trnasfer 5000 to Rahul")
    assert res_transfer.intent == BankingIntent.TRANSFER_MONEY
    assert res_transfer.entities.amount == 5000.0
    assert res_transfer.entities.beneficiary_name == "Rahul"

    # Typo in balance check
    res_bal = await route_banking_request("wht is my balence?")
    assert res_bal.intent == BankingIntent.BALANCE_CHECK

    # Typo in card freeze
    res_card = await route_banking_request("plz freze my dbit crd")
    assert res_card.intent == BankingIntent.CARD_ACTION
    assert res_card.sub_intent == BankingSubIntent.FREEZE_CARD


@pytest.mark.asyncio
async def test_granular_dispute_sub_intents():
    """Verify distinct sub-intents for card declines, UPI failures, and unauthorized fraud."""
    # 1. Card Decline
    card_dec = await route_banking_request("Why was my card payment declined at merchant?")
    assert card_dec.intent == BankingIntent.SUPPORT_DISPUTE
    assert card_dec.sub_intent == BankingSubIntent.CARD_PAYMENT_DECLINED

    # 2. UPI Failure
    upi_dec = await route_banking_request("Why did my UPI payment fail to grocery store?")
    assert upi_dec.intent == BankingIntent.SUPPORT_DISPUTE
    assert upi_dec.sub_intent == BankingSubIntent.UPI_PAYMENT_FAILED

    # 3. Unauthorized Transaction / Fraud
    fraud_dec = await route_banking_request("I noticed an unauthorized charge of 10000 on my account!")
    assert fraud_dec.intent == BankingIntent.SUPPORT_DISPUTE
    assert fraud_dec.sub_intent == BankingSubIntent.UNAUTHORIZED_TRANSACTION


@pytest.mark.asyncio
async def test_unauthorized_fraud_support_flow():
    """Verify that unauthorized fraud triggers high-priority ticket and card freeze suggestion."""
    checkpointer = await get_checkpointer(use_postgres=False)
    app = supervisor_graph_builder.compile(checkpointer=checkpointer)

    initial_state = {
        "messages": [HumanMessage(content="There is an unauthorized transaction of 15000 on my card!")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh",
        "active_workflow": "NONE",
        "paused_workflow": None,
        "account_data": {},
        "transfer_data": {},
        "card_data": {},
        "loan_data": {},
        "payment_data": {},
        "support_data": {},
        "insights_data": {},
        "current_intent": None,
        "current_sub_intent": None,
        "intent_confidence": None,
        "routing_reasoning": None,
        "negation_detected": None,
        "hitl_task_id": None,
        "hitl_status": None,
        "final_response": None,
        "customer_memory": {},
        "fraud_check_result": None,
        "aml_check_result": None,
        "ledger_check_result": None,
        "widget_type": None,
        "widget_data": None
    }

    config = {"configurable": {"thread_id": "TEST-PROD-FRAUD-01"}}
    final_output = await app.ainvoke(initial_state, config=config)

    final_msg = final_output["messages"][-1].content
    assert "Fraud" in final_msg or "freeze your card" in final_msg.lower()
    assert "Immediate Safety Recommendation" in final_msg or "freeze" in final_msg.lower()


@pytest.mark.asyncio
async def test_temporal_date_time_query():
    """Verify that asking current date/time returns accurate temporal response."""
    checkpointer = await get_checkpointer(use_postgres=False)
    app = supervisor_graph_builder.compile(checkpointer=checkpointer)

    state = {
        "messages": [HumanMessage(content="What date is today and what is the current time?")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh",
        "active_workflow": "NONE",
        "paused_workflow": None,
        "account_data": {},
        "transfer_data": {},
        "card_data": {},
        "loan_data": {},
        "payment_data": {},
        "support_data": {},
        "insights_data": {},
        "current_intent": None,
        "current_sub_intent": None,
        "intent_confidence": None,
        "routing_reasoning": None,
        "negation_detected": None,
        "hitl_task_id": None,
        "hitl_status": None,
        "final_response": None,
        "customer_memory": {},
        "fraud_check_result": None,
        "aml_check_result": None,
        "ledger_check_result": None,
        "widget_type": None,
        "widget_data": None
    }

    config = {"configurable": {"thread_id": "TEST-PROD-TEMPORAL-01"}}
    output = await app.ainvoke(state, config=config)
    last_resp = output["messages"][-1].content

    assert output["current_intent"] == "TEMPORAL_QUERY"
    assert "Today is" in last_resp
    assert "current local time" in last_resp or "IST" in last_resp


@pytest.mark.asyncio
async def test_agent_at_mention_routing():
    """Verify that explicit @mention routing overrides and dispatches directly."""
    # @loan mention
    loan_dec = await route_banking_request("@loan what is the EMI for 10 lakhs for 3 years?")
    assert loan_dec.intent == BankingIntent.LOAN_ACTION
    assert loan_dec.confidence == 1.0
    assert loan_dec.target_agent_mention == "@loan"
    assert loan_dec.cleaned_message == "what is the EMI for 10 lakhs for 3 years?"
    assert loan_dec.entities.amount == 1000000.0

    # @card mention
    card_dec = await route_banking_request("@card please freeze my debit card")
    assert card_dec.intent == BankingIntent.CARD_ACTION
    assert card_dec.confidence == 1.0
    assert card_dec.target_agent_mention == "@card"
    assert card_dec.entities.card_type == "DEBIT"


@pytest.mark.asyncio
async def test_layered_semantic_caching():
    """Verify that different query variations hit the intent-level semantic cache."""
    customer_id = 999
    # Invalidate initial state
    await cache_engine.invalidate_customer_cache(customer_id)

    payload = {
        "account": "SB****1001",
        "balance": 75000.0,
        "status": "ACTIVE"
    }

    # Set cache with query A
    await cache_engine.set_cached_response(
        customer_id=customer_id,
        query="What is my balance?",
        response_payload=payload,
        intent="BALANCE_CHECK"
    )

    # Lookup with exact match (Layer 1)
    hit1 = await cache_engine.get_cached_response(customer_id, "What is my balance?")
    assert hit1 is not None
    assert hit1["balance"] == 75000.0

    # Lookup with variation + typo (Layer 2 Semantic Cache Hit!)
    hit2 = await cache_engine.get_cached_response(
        customer_id=customer_id,
        query="wht is my balence?",
        intent="BALANCE_CHECK"
    )
    assert hit2 is not None
    assert hit2["balance"] == 75000.0
    assert hit2.get("is_semantic_cache_hit") is True

    # Invalidate on mutation
    await cache_engine.invalidate_customer_cache(customer_id)
    miss = await cache_engine.get_cached_response(customer_id, "What is my balance?")
    assert miss is None
