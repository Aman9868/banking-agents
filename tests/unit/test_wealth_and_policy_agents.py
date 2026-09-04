"""Unit and Integration Tests for Wealth Advisory, SIP Planner, Free Market Search, and Policy Agents."""

import pytest
from agents.state import BankingSessionState
from agents.supervisor.graph import supervisor_graph_builder
from services.wealth.sip_calculator import calculate_sip_returns, recommend_investment_strategy
from services.market.free_search import free_market_service, OFFLINE_BENCHMARK_MARKET
from services.policies.policy_catalog import search_policies, get_policy_by_id, POLICY_CATALOG
from tools.wealth import calculate_sip_tool, recommend_portfolio_tool, search_market_stocks_tool
from tools.policies import get_policy_details_tool, compare_policies_tool
from gateway.llm.router import route_banking_request, BankingIntent, BankingSubIntent
from langchain_core.messages import HumanMessage, AIMessage


@pytest.mark.asyncio
async def test_sip_calculator_mathematical_precision():
    """Verifies that the SIP compound growth formula executes with precision."""
    # Monthly = 1000, 5 years (60 months), 12% CAGR
    res = calculate_sip_returns(monthly_investment=1000.0, tenure_years=5, annual_expected_cagr=12.0)

    assert res["monthly_investment"] == 1000.0
    assert res["tenure_years"] == 5
    assert res["total_invested"] == 60000.0  # 1000 * 60

    # 1000/mo at 12% for 5y is approx ₹82,486
    assert 80000.0 <= res["future_value"] <= 85000.0
    assert res["estimated_gain"] > 20000.0
    assert res["growth_multiplier"] > 1.3

    # Projections check
    assert len(res["projections"]) == 4
    for p in res["projections"]:
        assert p["years"] in [1, 3, 5, 10]
        assert p["estimated_value"] > p["total_invested"]


@pytest.mark.asyncio
async def test_student_persona_portfolio_recommendation():
    """Verifies that student persona receives tailored micro-SIP advice and low-cost Direct funds."""
    res = recommend_investment_strategy(monthly_amount=1500.0, user_persona="STUDENT")

    assert "Student" in res["headline"]
    assert res["monthly_amount"] == 1500.0
    assert res["user_persona"] == "STUDENT"

    allocs = res["allocations"]
    assert len(allocs) == 3
    # Nifty 50 Large Cap Index Fund (60%)
    assert allocs[0]["percentage"] == 60
    assert allocs[0]["amount"] == 900.0
    assert any("Nifty 50" in f for f in allocs[0]["recommended_funds"])

    # Flexi-Cap (25%)
    assert allocs[1]["percentage"] == 25
    assert allocs[1]["amount"] == 375.0

    # Emergency buffer (15%)
    assert allocs[2]["percentage"] == 15
    assert allocs[2]["amount"] == 225.0


@pytest.mark.asyncio
async def test_free_web_market_search_and_stock_quotes():
    """Verifies that free market search returns real-time quotes or offline benchmark fallback."""
    # Test stock quote
    quote = await free_market_service.get_stock_quote("RELIANCE")
    assert quote["symbol"] == "RELIANCE"
    assert quote["current_price"] > 0
    assert quote["currency"] == "INR"

    # Test web search
    results = await free_market_service.search_web_market("best stocks to buy in India", max_results=3)
    assert len(results) >= 1
    assert "title" in results[0]
    assert "snippet" in results[0]
    assert "source" in results[0]


@pytest.mark.asyncio
async def test_policy_catalog_search_and_retrieval():
    """Verifies health insurance, life insurance, and government scheme policies."""
    # Health policies
    health_pols = search_policies(category="HEALTH")
    assert len(health_pols) >= 3
    assert any("Student Health" in p["title"] for p in health_pols)

    # Government scheme policies
    govt_pols = search_policies(category="GOVT_SCHEME")
    assert len(govt_pols) >= 4
    pmjjby = get_policy_by_id("POL-LIFE-PMJJBY")
    assert pmjjby is not None
    assert "436" in pmjjby["annual_premium"]
    assert "2,00,000" in pmjjby["sum_insured"]

    # Compare tool
    cmp_res = await compare_policies_tool(
        policy_a_id="POL-HEALTH-STUDENT",
        policy_b_id="POL-HEALTH-COMPREHENSIVE"
    )
    assert cmp_res.success is True
    assert cmp_res.data["policy_a"]["id"] == "POL-HEALTH-STUDENT"
    assert cmp_res.data["policy_b"]["id"] == "POL-HEALTH-COMPREHENSIVE"


@pytest.mark.asyncio
async def test_router_wealth_and_policy_intent_classification():
    """Verifies router fast-paths and entity extraction for student SIP, market search, and policies."""
    # 1. Student SIP intent
    dec1 = await route_banking_request(
        "i am college student so my monthly income is 2000. i want to do sip investment tell best sip plans"
    )
    assert dec1.intent == BankingIntent.WEALTH_ADVISORY
    assert dec1.sub_intent == BankingSubIntent.SIP_PLANNING
    assert dec1.entities.user_persona == "STUDENT"
    assert dec1.entities.amount == 2000.0

    # 2. Stock market search intent
    dec2 = await route_banking_request("what are the best stocks to buy right now in India?")
    assert dec2.intent == BankingIntent.WEALTH_ADVISORY
    assert dec2.sub_intent == BankingSubIntent.STOCK_MARKET_SEARCH

    # 3. Policy inquiry intent
    dec3 = await route_banking_request("tell me about health insurance policies for students and PMJJBY")
    assert dec3.intent == BankingIntent.POLICY_INQUIRY
    assert dec3.entities.policy_category in ["HEALTH", "GOVT_SCHEME"]

    # 4. Direct @mentions
    dec4 = await route_banking_request("@wealth how much will 1000 per month grow in 5 years?")
    assert dec4.intent == BankingIntent.WEALTH_ADVISORY

    dec5 = await route_banking_request("@insurance what are the benefits of term life?")
    assert dec5.intent == BankingIntent.POLICY_INQUIRY


@pytest.mark.asyncio
async def test_supervisor_wealth_advisory_flow_and_genui_widget():
    """Verifies that supervisor routes student SIP queries to wealth_subgraph and emits SIP_PLANNER_WIDGET."""
    app = supervisor_graph_builder.compile()

    state: BankingSessionState = {
        "messages": [
            HumanMessage(content="I am a college student and my monthly income is ₹2,000. I want to do SIP investment, tell me the best plans")
        ],
        "customer_id": 1,
        "customer_external_id": "CUST-001",
        "customer_name": "Raju Sharma",
        "active_workflow": "NONE",
        "paused_workflow": None,
        "account_data": {},
        "transfer_data": {},
        "card_data": {},
        "loan_data": {},
        "payment_data": {},
        "support_data": {},
        "insights_data": {},
        "wealth_data": {},
        "policy_data": {},
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
        "kyc_payload": None,
    }

    res = await app.ainvoke(state)

    assert res["current_intent"] == "WEALTH_ADVISORY"
    assert res["widget_type"] == "SIP_PLANNER_WIDGET"
    assert res["widget_data"] is not None
    assert "Nifty 50" in res["final_response"]
    assert "Compounding" in res["final_response"]


@pytest.mark.asyncio
async def test_supervisor_policy_advisory_flow_and_genui_widget():
    """Verifies that supervisor routes policy questions to policy_subgraph and emits POLICY_CARD_WIDGET."""
    app = supervisor_graph_builder.compile()

    state: BankingSessionState = {
        "messages": [
            HumanMessage(content="Tell me about health insurance policies for students and government schemes like PMJJBY")
        ],
        "customer_id": 1,
        "customer_external_id": "CUST-001",
        "customer_name": "Raju Sharma",
        "active_workflow": "NONE",
        "paused_workflow": None,
        "account_data": {},
        "transfer_data": {},
        "card_data": {},
        "loan_data": {},
        "payment_data": {},
        "support_data": {},
        "insights_data": {},
        "wealth_data": {},
        "policy_data": {},
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
        "kyc_payload": None,
    }

    res = await app.ainvoke(state)

    assert res["current_intent"] == "POLICY_INQUIRY"
    assert res["widget_type"] == "POLICY_CARD_WIDGET"
    assert res["widget_data"] is not None
    assert any(k in res["final_response"] for k in ["Health", "Insurance", "PMJJBY", "Nova Care"])


@pytest.mark.asyncio
async def test_gratitude_after_wealth_advisory_flow():
    """Verifies that saying 'thank you' after wealth advisory triggers personalized ChatGPT-style appreciation."""
    app = supervisor_graph_builder.compile()

    state: BankingSessionState = {
        "messages": [
            HumanMessage(content="I want to start an SIP of 1000 per month"),
            AIMessage(content="Hello Raju! Here is your Student Starter Wealth Plan with Nifty 50 Index funds and 12% Compounding."),
            HumanMessage(content="thanku so much bot!")
        ],
        "customer_id": 1,
        "customer_external_id": "CUST-001",
        "customer_name": "Raju Sharma",
        "active_workflow": "NONE",
        "paused_workflow": None,
        "account_data": {},
        "transfer_data": {},
        "card_data": {},
        "loan_data": {},
        "payment_data": {},
        "support_data": {},
        "insights_data": {},
        "wealth_data": {},
        "policy_data": {},
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
        "kyc_payload": None,
    }

    res = await app.ainvoke(state)

    assert res["current_intent"] == "GENERAL_CONVERSATION"
    assert res["current_sub_intent"] == "THANK_YOU"
    # Personalized warmth addressing customer by name Raju and investment journey
    assert "Raju" in res["final_response"]
    assert any(w in res["final_response"] for w in ["investment", "welcome", "SIP"])
    assert "Transfers & Beneficiaries: Send money" not in res["final_response"]

