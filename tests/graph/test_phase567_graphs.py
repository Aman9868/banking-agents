"""StateGraph execution tests for Cards, Loans, Bill Payments, and Support RAG."""

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from agents.supervisor.graph import supervisor_graph_builder
from database.init_db import init_database, seed_mock_data


@pytest.fixture(scope="module", autouse=True)
async def setup_test_db():
    await init_database()
    await seed_mock_data()


@pytest.mark.asyncio
async def test_card_freeze_conversation():
    checkpointer = MemorySaver()
    app = supervisor_graph_builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "TEST-CARD-FREEZE"}}

    res = await app.ainvoke({
        "messages": [HumanMessage(content="My card is stolen, please freeze my debit card immediately")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh"
    }, config=config)

    assert "frozen" in res["final_response"].lower()
    assert "****" in res["final_response"]  # PII masked


@pytest.mark.asyncio
async def test_loan_emi_calculation_conversation():
    checkpointer = MemorySaver()
    app = supervisor_graph_builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "TEST-LOAN-EMI"}}

    res = await app.ainvoke({
        "messages": [HumanMessage(content="What is the EMI for a 5 lakh personal loan for 3 years?")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh"
    }, config=config)

    assert "Personal Loan estimate" in res["final_response"]
    assert "Estimated Monthly EMI" in res["final_response"]
    assert "₹500,000.00" in res["final_response"]


@pytest.mark.asyncio
async def test_bill_payment_multi_turn_confirmation():
    checkpointer = MemorySaver()
    app = supervisor_graph_builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "TEST-BILL-PAY"}}

    # Turn 1: Inquire about electricity bill
    res1 = await app.ainvoke({
        "messages": [HumanMessage(content="Pay my electricity bill for Tata Power")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh"
    }, config=config)

    assert "Tata Power" in res1["final_response"]
    assert "Please reply 'Yes' to confirm" in res1["final_response"]
    assert res1["active_workflow"] == "PAYMENT_ACTION"

    # Turn 2: Confirm payment
    res2 = await app.ainvoke({
        "messages": [HumanMessage(content="Yes")]
    }, config=config)

    assert "successful" in res2["final_response"].lower() or "completed" in res2["final_response"].lower()
    assert "BIL-TXN-" in res2["final_response"]
    assert res2["active_workflow"] == "NONE"


@pytest.mark.asyncio
async def test_knowledge_rag_faq_conversation():
    checkpointer = MemorySaver()
    app = supervisor_graph_builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "TEST-KNOWLEDGE-FAQ"}}

    res = await app.ainvoke({
        "messages": [HumanMessage(content="What is the savings account interest rate?")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh"
    }, config=config)

    assert "interest rate" in res["final_response"].lower()
    assert "3.50%" in res["final_response"]


@pytest.mark.asyncio
async def test_human_support_ticket_escalation():
    checkpointer = MemorySaver()
    app = supervisor_graph_builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "TEST-SUPPORT-TICKET"}}

    res = await app.ainvoke({
        "messages": [HumanMessage(content="I want to talk to a human agent, please open a ticket for me")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh"
    }, config=config)

    assert "TCK-" in res["final_response"]
    assert "support team will follow up" in res["final_response"].lower()

