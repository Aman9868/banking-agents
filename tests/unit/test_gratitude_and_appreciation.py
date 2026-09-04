"""Tests for contextual ChatGPT-style gratitude and appreciation handling."""

import pytest
import pytest_asyncio
from langchain_core.messages import HumanMessage, AIMessage

from database.init_db import init_database, seed_mock_data
from gateway.llm.router import route_banking_request, BankingIntent, BankingSubIntent
from agents.supervisor.graph import supervisor_router_node
from agents.state import BankingSessionState


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await init_database()
    await seed_mock_data()


@pytest.mark.asyncio
async def test_router_recognizes_thank_you_tokens():
    """Verifies that all variations of thank you / thanks / thanku route to THANK_YOU sub-intent."""
    for token in ["thanku", "thanks", "thank you", "thx", "thank u so much", "appreciate it", "great thanks"]:
        dec = await route_banking_request(token)
        assert dec.intent == BankingIntent.GENERAL_CONVERSATION
        assert dec.sub_intent == BankingSubIntent.THANK_YOU


@pytest.mark.asyncio
async def test_appreciation_after_transaction_tracking_matches_screenshot():
    """
    Direct reproduction of user screenshot:
    User asks about last transaction (to Rahul) -> Assistant answers -> User says 'thanku'.
    Bot must appreciate warmly with context instead of dumping robotic menu.
    """
    state: BankingSessionState = {
        "messages": [
            HumanMessage(content="what is my last trasnaction i wna l knwo wherte i spend"),
            AIMessage(content=(
                "Your latest transfer was ₹5,000.00 to Rahul on 04 September 2026, 06:58 AM.\n"
                "• Transaction ID: TXN-8A8C5BF3\n"
                "• Status: COMPLETED ✅\n"
                "• Recipient Account: 010**10\n"
                "• Debited From: Savings 7377"
            )),
            HumanMessage(content="thanku")
        ],
        "customer_id": 1,
        "customer_external_id": "CUST-8536",
        "customer_name": "rajuu",
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
        "widget_data": None,
        "kyc_payload": None
    }

    result = await supervisor_router_node(state)
    resp = result["final_response"]

    # Must NOT be the robotic menu dump
    assert "Hello rajuu! I am your AI Banking Assistant. I can assist you with:" not in resp

    # Must contain warm, ChatGPT-style appreciation addressing Raju and Rahul
    assert "You're very welcome" in resp or "welcome" in resp.lower()
    assert "Rajuu" in resp or "rajuu" in resp.lower()
    assert "transfer" in resp.lower() or "Rahul" in resp


@pytest.mark.asyncio
async def test_appreciation_after_balance_check():
    """Verifies contextual appreciation after balance inquiry."""
    state: BankingSessionState = {
        "messages": [
            HumanMessage(content="What is my balance?"),
            AIMessage(content="Your current balance for Savings account ****1234 is ₹100,000.00."),
            HumanMessage(content="thanks a lot!")
        ],
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
        "widget_data": None,
        "kyc_payload": None
    }

    result = await supervisor_router_node(state)
    resp = result["final_response"]

    assert "Hello Amanpreet! I am your AI Banking Assistant" not in resp
    assert "welcome" in resp.lower()
    assert "balance" in resp.lower()

