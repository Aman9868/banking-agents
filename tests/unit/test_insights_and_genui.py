"""Test suite for Next-Gen Capabilities: PFM Insights, Generative UI Widgets, and Guardian."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from apps.api.main import app
from database.init_db import init_database, seed_mock_data
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from tools.insights import get_spending_insights_tool, detect_subscriptions_tool, predict_cashflow_tool
from agents.insights.graph import insights_subgraph
from langchain_core.messages import HumanMessage


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await init_database()
    await seed_mock_data()


@pytest.mark.asyncio
async def test_spending_insights_tool():
    """Verify spending breakdown categories and percentage math."""
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        res = await get_spending_insights_tool(repo=repo, customer_id=1, days=30)

        assert res.success is True
        assert res.data["total_spent"] > 0
        assert len(res.data["breakdown"]) >= 3
        # Verify percentages sum to approx 100%
        pct_sum = sum(item["percentage"] for item in res.data["breakdown"])
        assert 99.0 <= pct_sum <= 101.0


@pytest.mark.asyncio
async def test_subscriptions_tool():
    """Verify detection of recurring subscriptions."""
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        res = await detect_subscriptions_tool(repo=repo, customer_id=1)

        assert res.success is True
        assert res.data["count"] >= 3
        assert res.data["total_monthly_commitment"] > 0
        names = [s["name"] for s in res.data["subscriptions"]]
        assert any("Broadband" in n for n in names)
        assert any("Tata Power" in n for n in names)


@pytest.mark.asyncio
async def test_cashflow_prediction_tool():
    """Verify what-if cashflow projection calculation."""
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        # Check standard cashflow with 5000 proposed debit
        res = await predict_cashflow_tool(repo=repo, customer_id=1, proposed_debit=5000.0)

        assert res.success is True
        assert res.data["proposed_debit"] == 5000.0
        assert res.data["upcoming_commitments_total"] > 0
        assert "is_safe" in res.data


@pytest.mark.asyncio
async def test_insights_subgraph_produces_genui_widget():
    """Verify insights subgraph populates SPENDING_CHART GenUI widget in state."""
    state = {
        "messages": [HumanMessage(content="Show my spending breakdown")],
        "customer_id": 1,
        "customer_external_id": "CUST-1001",
        "customer_name": "Amanpreet Singh",
        "active_workflow": "INSIGHTS",
        "insights_data": {"action": "SPENDING", "days": 30}
    }
    result = await insights_subgraph.ainvoke(state)

    assert "Monthly Spending Breakdown" in result["final_response"]
    assert result.get("widget_type") == "SPENDING_CHART"
    assert result.get("widget_data") is not None
    assert "breakdown" in result["widget_data"]


@pytest.mark.asyncio
async def test_chat_api_loan_inquiry_returns_emi_slider_widget():
    """Verify chat API automatically returns EMI_SLIDER widget for loan inquiry."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/api/v1/chat", json={
            "message": "What is the EMI for a 5 lakh loan for 3 years?",
            "thread_id": "TEST-WIDGET-LOAN",
            "customer_external_id": "CUST-1001"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["widget_type"] == "EMI_SLIDER"
        assert data["widget_data"] is not None
        assert data["widget_data"]["amount"] == 500000.0
        assert data["widget_data"]["tenure_months"] == 36
        assert data["widget_data"]["monthly_emi"] > 0


@pytest.mark.asyncio
async def test_guardian_alerts_endpoint():
    """Verify GET /api/v1/chat/guardian returns proactive due date nudges."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/chat/guardian?customer_external_id=CUST-1001")
        assert res.status_code == 200
        data = res.json()
        assert "alerts" in data
        assert len(data["alerts"]) >= 1
        assert any("Tata Power" in a["title"] for a in data["alerts"])

