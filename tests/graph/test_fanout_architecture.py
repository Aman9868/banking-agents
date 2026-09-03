import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage
from database.init_db import init_database, seed_mock_data
from agents.transfer.graph import transfer_subgraph_builder


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await init_database()
    await seed_mock_data()


@pytest.mark.asyncio
async def test_transfer_subgraph_parallel_fanout_execution():
    """Verifies that resolve_entities fans out concurrently to fraud, aml, and ledger nodes."""
    compiled_transfer = transfer_subgraph_builder.compile()

    state = {
        "messages": [HumanMessage(content="Transfer 500 to Rahul")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh",
        "active_workflow": "TRANSFER_MONEY",
        "transfer_data": {
            "amount": 500.0,
            "beneficiary_name": "Rahul",
            "source_account_id": 1,
            "source_account_number": "SB10001234"
        }
    }

    result = await compiled_transfer.ainvoke(state)

    # Verify all 3 parallel Fan-Out branches executed concurrently and populated state!
    assert result.get("fraud_check_result") is not None
    assert result["fraud_check_result"]["score"] is not None
    assert result["fraud_check_result"]["risk_level"] == "LOW"

    assert result.get("aml_check_result") is not None
    assert result["aml_check_result"]["passed"] is True

    assert result.get("ledger_check_result") is not None
    assert result["ledger_check_result"]["sufficient_funds"] is True
    assert result["ledger_check_result"]["available_balance"] > 0

    # Verify Fan-In aggregator processed all 3 results into confirmation step
    t_data = result.get("transfer_data", {})
    assert t_data.get("step") == "CONFIRM"
    assert "Transfer ₹500.00" in result.get("final_response", "")


@pytest.mark.asyncio
async def test_transfer_subgraph_parallel_aml_block_fanout():
    """Verifies that an AML watchlist match in the parallel AML branch blocks the transfer."""
    compiled_transfer = transfer_subgraph_builder.compile()

    state = {
        "messages": [HumanMessage(content="Transfer 5000 to Rahul Sanctioned OFAC")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh",
        "active_workflow": "TRANSFER_MONEY",
        "transfer_data": {
            "amount": 5000.0,
            "beneficiary_id": 1,
            "beneficiary_name": "Rahul Sanctioned OFAC",
            "source_account_id": 1,
            "source_account_number": "SB10001234",
            "beneficiary_account": "SB10007788"
        }
    }

    result = await compiled_transfer.ainvoke(state)

    # Parallel AML node must flag passed=False
    assert result.get("aml_check_result") is not None
    assert result["aml_check_result"]["passed"] is False

    # Policy aggregator must block
    assert "blocked by AML & Sanctions" in result.get("final_response", "")

