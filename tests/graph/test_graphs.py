"""StateGraph execution tests for Supervisor and Subgraphs with MemorySaver checkpointer."""

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
async def test_account_opening_multi_turn_flow():
    checkpointer = MemorySaver()
    app = supervisor_graph_builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "TEST-THREAD-ACC-OPEN"}}

    # Turn 1: Intent to open account
    res1 = await app.ainvoke({
        "messages": [HumanMessage(content="I want to open a savings account")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh"
    }, config=config)
    assert "May I have your full name?" in res1["final_response"]
    assert res1["account_data"]["step"] == "NAME"

    # Turn 2: Provide full name
    res2 = await app.ainvoke({
        "messages": [HumanMessage(content="Amanpreet Singh")]
    }, config=config)
    assert "What is your date of birth?" in res2["final_response"]
    assert res2["account_data"]["step"] == "DOB"

    # Turn 3: Provide DOB
    res3 = await app.ainvoke({
        "messages": [HumanMessage(content="12 March 1997")]
    }, config=config)
    assert "email address" in res3["final_response"].lower()
    assert res3["account_data"]["step"] == "EMAIL"

    # Turn 4: Provide Email -> Account provisioning completes!
    res4 = await app.ainvoke({
        "messages": [HumanMessage(content="amanpreet@example.com")]
    }, config=config)
    assert "Your KYC is complete" in res4["final_response"]
    assert "account" in res4["final_response"].lower()
    assert res4["active_workflow"] == "NONE"


@pytest.mark.asyncio
async def test_money_transfer_flow_and_confirmation():
    checkpointer = MemorySaver()
    app = supervisor_graph_builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "TEST-THREAD-TRANSFER"}}

    # Turn 1: Request transfer
    res1 = await app.ainvoke({
        "messages": [HumanMessage(content="Transfer ₹5,000 to Rahul")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh"
    }, config=config)

    assert "Rahul" in res1["final_response"]
    assert "Transfer ₹5,000.00" in res1["final_response"]
    assert "Please reply 'Yes' to confirm" in res1["final_response"]
    assert res1["transfer_data"]["step"] == "CONFIRM"

    # Turn 2: Confirm transfer
    res2 = await app.ainvoke({
        "messages": [HumanMessage(content="Yes")]
    }, config=config)

    assert "Transfer initiated" in res2["final_response"]
    assert "TXN-" in res2["final_response"]
    assert res2["active_workflow"] == "NONE"


@pytest.mark.asyncio
async def test_context_switching_balance_during_account_opening():
    checkpointer = MemorySaver()
    app = supervisor_graph_builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "TEST-THREAD-CONTEXT-SWITCH"}}

    # Turn 1: Start account opening
    res1 = await app.ainvoke({
        "messages": [HumanMessage(content="I want to open an account")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh"
    }, config=config)
    assert "May I have your full name?" in res1["final_response"]

    # Turn 2: Provide name
    res2 = await app.ainvoke({
        "messages": [HumanMessage(content="Amanpreet Singh")]
    }, config=config)
    assert "What is your date of birth?" in res2["final_response"]

    # Turn 3: Interruption with topic switch!
    res3 = await app.ainvoke({
        "messages": [HumanMessage(content="Before that, what's my current balance?")]
    }, config=config)

    # Bot answers balance AND seamlessly resumes account opening
    assert "Your current balance" in res3["final_response"]
    assert "continuing with your account application: What is your date of birth?" in res3["final_response"]


@pytest.mark.asyncio
async def test_support_declined_transaction_inquiry():
    checkpointer = MemorySaver()
    app = supervisor_graph_builder.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "TEST-THREAD-SUPPORT"}}

    res = await app.ainvoke({
        "messages": [HumanMessage(content="Why was my last transaction declined?")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh"
    }, config=config)

    assert "TXN-10091" in res["final_response"]
    assert "beneficiary security verification was not completed" in res["final_response"]

