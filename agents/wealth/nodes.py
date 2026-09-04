"""Wealth, SIP Investment Advisory, and Live Market Search Node Functions."""

import re
import json
from typing import Dict, Any, Optional
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from agents.state import BankingSessionState, WealthWorkflowData
from gateway.tool_gateway.gateway import tool_gateway
from gateway.tool_gateway.permissions import AgentRole
from gateway.llm.client import llm_gateway
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from agents.wealth.prompts import WEALTH_ADVISOR_SYSTEM_PROMPT, STUDENT_SIP_RECOMMENDATION_PROMPT
import structlog

logger = structlog.get_logger(__name__)


async def wealth_advisor_node(state: BankingSessionState) -> Dict[str, Any]:
    """
    Orchestrates personalized wealth advisory:
    1. SIP compound calculator tailored for students and early investors.
    2. Free live web search and Yahoo Finance stock quotes.
    3. Emits SIP_PLANNER_WIDGET or STOCK_MARKET_WIDGET for interactive UI exploration.
    """
    last_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_msg = msg.content.strip()
            break

    sub_intent = state.get("current_sub_intent", "SIP_PLANNING")
    customer_id = state.get("customer_id", 1)
    customer_name = state.get("customer_name", "Valued Customer")
    first_name = customer_name.split(" ")[0] if customer_name else "there"

    # Extract or infer investment parameters
    wealth_data = dict(state.get("wealth_data") or {})
    persona = wealth_data.get("user_persona") or "STUDENT"
    if any(w in last_msg.lower() for w in ["college", "student", "coioolsge", "sstudnet", "university", "freshman"]):
        persona = "STUDENT"

    risk = wealth_data.get("risk_profile") or "MODERATE"
    if any(w in last_msg.lower() for w in ["aggressive", "high risk", "max return"]):
        risk = "AGGRESSIVE"
    elif any(w in last_msg.lower() for w in ["conservative", "safe", "low risk"]):
        risk = "CONSERVATIVE"

    # Extract monthly amount
    monthly_amt = wealth_data.get("monthly_investment")
    amt_match = re.search(r"(?:₹|rs\.?|inr)?\s*(\d{1,6}(?:,\d{3})*(?:\.\d+)?)\s*(?:monthly|per month|sip|a month|/mo|amount)?", last_msg, re.IGNORECASE)
    if amt_match:
        try:
            val = float(amt_match.group(1).replace(",", ""))
            if val > 0 and val not in [2024, 2025, 2026, 2027]:
                monthly_amt = val
        except ValueError:
            pass

    if not monthly_amt or monthly_amt <= 0:
        monthly_amt = 1000.0 if persona == "STUDENT" else 5000.0

    wealth_data["monthly_investment"] = monthly_amt
    wealth_data["user_persona"] = persona
    wealth_data["risk_profile"] = risk

    # 1. Stock Market Search & Live Quotes Branch
    is_stock_search = (
        sub_intent == "STOCK_MARKET_SEARCH"
        or any(w in last_msg.lower() for w in ["best stock", "best stocks", "stocks to buy", "share market", "live price", "quote", "share price", "market price"])
    )

    if is_stock_search:
        sym_match = None
        for sym in ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "TATAMOTORS", "ITC", "NIFTY50"]:
            if re.search(r"\b" + sym + r"\b", last_msg, re.IGNORECASE):
                sym_match = sym
                break

        search_query = last_msg if not sym_match else f"{sym_match} stock price news fundamentals"
        async with AsyncSessionLocal() as session:
            repo = BankingRepository(session)
            tool_res = await tool_gateway.execute_tool(
                agent_role=AgentRole.WEALTH_ADVISOR.value,
                tool_name="search_market_stocks",
                repo=repo,
                customer_id=customer_id,
                parameters={"query": search_query, "symbol": sym_match}
            )

        quote_info = (tool_res.data or {}).get("quote")
        web_results = (tool_res.data or {}).get("web_results", [])

        if quote_info and quote_info.get("current_price", 0) > 0:
            price_str = f"₹{quote_info['current_price']:,.2f}"
            chg_str = quote_info.get("change", "0.00%")
            status_symbol = "🟢" if not chg_str.startswith("-") else "🔴"
            market_intro = (
                f"📈 **Live Market Quote for {quote_info['company_name']} ({quote_info['symbol']})**:\n\n"
                f"• **Current Price**: **{price_str}** {status_symbol} ({chg_str})\n"
                f"• **Sector**: {quote_info.get('sector', 'Equity')}\n"
                f"• **Exchange**: {quote_info.get('exchange', 'NSE')}\n\n"
                "### 🔍 Key Market Takeaways & Latest Financial Web Search:\n"
            )
        else:
            market_intro = (
                "📈 **Live Financial & Stock Market Insights** (via Web Search):\n\n"
                "Here are the top trending stocks and analyst consensus for Indian equities:\n\n"
            )

        web_snippets = ""
        for i, res in enumerate(web_results[:3], 1):
            web_snippets += f"**{i}. {res['title']}**\n{res['snippet']}\n*Source: {res['source']}*\n\n"

        default_stock_advice = (
            f"Hello {first_name}! {market_intro}{web_snippets}"
            "💡 *NovaBank Investment Reminder: Equities are subject to market volatility. "
            "For disciplined wealth generation, we strongly recommend combining direct stocks with automated monthly SIPs.*"
        )
        advice = default_stock_advice

        try:
            user_prompt = (
                f"Customer Name: {customer_name}\n"
                f"Customer Query: \"{last_msg}\"\n\n"
                f"LIVE MARKET DATA:\n"
                f"- Quote Details: {json.dumps(quote_info)}\n"
                f"- Live Web Search Insights: {json.dumps(web_results[:3])}\n\n"
                "Synthesize this live data and address the customer's query directly according to your wealth advisory persona."
            )
            llm_res = await llm_gateway.invoke_chat([
                SystemMessage(content=WEALTH_ADVISOR_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt)
            ], model_tier="reasoning")

            if llm_res.provider != "deterministic_fallback" and len(llm_res.content.strip()) > 60:
                advice = llm_res.content.strip()
        except Exception as exc:
            logger.warning("LLM stock market search advisory failed, using structured template", error=str(exc))

        widget_data = {
            "quote": quote_info,
            "web_results": web_results,
            "query": search_query,
            "customer_name": customer_name
        }

        return {
            "active_workflow": "NONE",
            "current_intent": "WEALTH_ADVISORY",
            "current_sub_intent": "STOCK_MARKET_SEARCH",
            "final_response": advice,
            "messages": [AIMessage(content=advice)],
            "widget_type": "STOCK_MARKET_WIDGET",
            "widget_data": widget_data,
            "wealth_data": wealth_data
        }

    # 2. SIP Investment Advisory & Planning Branch
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        tool_res = await tool_gateway.execute_tool(
            agent_role=AgentRole.WEALTH_ADVISOR.value,
            tool_name="calculate_sip",
            repo=repo,
            customer_id=customer_id,
            parameters={
                "monthly_investment": monthly_amt,
                "tenure_years": 5,
                "annual_expected_cagr": 12.0,
                "user_persona": persona,
                "risk_profile": risk
            }
        )

    sip_calc = (tool_res.data or {}).get("sip_calculation", {})
    strategy = (tool_res.data or {}).get("strategy", {})

    total_inv_str = f"₹{sip_calc.get('total_invested', 0):,.2f}"
    future_val_str = f"₹{sip_calc.get('future_value', 0):,.2f}"
    gain_str = f"₹{sip_calc.get('estimated_gain', 0):,.2f}"
    multiplier = sip_calc.get("growth_multiplier", 1.4)

    # Conversational Advice customized for students and early savers
    advice_lines = [
        f"Hello {first_name}! 🎓 {strategy.get('headline', 'Personalized SIP Investment Plan')}\n",
        f"{strategy.get('guidance', '')}\n",
        f"### 📊 Your 5-Year Compounding Projection (₹{monthly_amt:,.2f}/month @ 12% CAGR):",
        f"• **Total Amount Invested**: **{total_inv_str}**",
        f"• **Estimated Wealth Value**: **{future_val_str}** (Gains: **+{gain_str}**, **{multiplier}x** your principal)",
        f"• **10-Year Horizon**: Investing consistently for 10 years would yield **₹{sip_calc.get('projections', [{}, {}, {}, {'estimated_value': 0}])[3].get('estimated_value', 0):,.2f}**!\n",
        "### 🎯 Recommended Student Asset Allocation:"
    ]

    for alloc in strategy.get("allocations", []):
        advice_lines.append(
            f"• **{alloc['category']} ({alloc['percentage']}%)**: ₹{alloc['amount']:,.2f}/month\n"
            f"  *Funds*: {', '.join(alloc.get('recommended_funds', []))} (Expense: {alloc.get('expense_ratio')})\n"
            f"  *Why*: {alloc.get('rationale')}"
        )

    advice_lines.append("\n### 💡 Smart Student Investment Rules:")
    for tip in strategy.get("key_tips", []):
        advice_lines.append(f"• {tip}")

    advice_lines.append(
        "\nWould you like me to set up an automated SIP mandate from your NovaBank Savings account, "
        "or adjust the monthly contribution amount?"
    )

    full_advice = "\n".join(advice_lines)

    # Enhance with LLM Wealth Advisor persona synthesis
    try:
        persona_instructions = STUDENT_SIP_RECOMMENDATION_PROMPT if persona == "STUDENT" else ""
        system_content = f"{WEALTH_ADVISOR_SYSTEM_PROMPT}\n\n{persona_instructions}".strip()

        user_prompt = (
            f"Customer Name: {customer_name}\n"
            f"Detected Persona: {persona} (Risk Profile: {risk})\n"
            f"Customer Query: \"{last_msg}\"\n\n"
            f"CALCULATED MATHEMATICAL SIP FIGURES:\n"
            f"- Monthly Contribution: ₹{monthly_amt:,.2f}\n"
            f"- 5-Year Total Principal: {total_inv_str}\n"
            f"- 5-Year Estimated Maturity: {future_val_str} (Gain: +{gain_str}, {multiplier}x)\n"
            f"- 10-Year Estimated Maturity: ₹{sip_calc.get('projections', [{}, {}, {}, {'estimated_value': 0}])[3].get('estimated_value', 0):,.2f}\n"
            f"- Recommended Allocation: {json.dumps(strategy.get('allocations', []))}\n"
            f"- Key Guidance: {strategy.get('guidance', '')}\n\n"
            "Using these exact mathematical numbers and allocations, synthesize an inspiring, educational response that speaks directly to this customer."
        )

        llm_res = await llm_gateway.invoke_chat([
            SystemMessage(content=system_content),
            HumanMessage(content=user_prompt)
        ], model_tier="reasoning")

        if llm_res.provider != "deterministic_fallback" and len(llm_res.content.strip()) > 60:
            full_advice = llm_res.content.strip()
    except Exception as exc:
        logger.warning("LLM wealth advisory invocation failed, falling back to structured template", error=str(exc))

    widget_data = {
        "monthly_investment": monthly_amt,
        "persona": persona,
        "risk_profile": risk,
        "calculation": sip_calc,
        "strategy": strategy
    }

    return {
        "active_workflow": "WEALTH_ADVISORY",
        "current_intent": "WEALTH_ADVISORY",
        "current_sub_intent": "SIP_PLANNING",
        "final_response": full_advice,
        "messages": [AIMessage(content=full_advice)],
        "widget_type": "SIP_PLANNER_WIDGET",
        "widget_data": widget_data,
        "wealth_data": wealth_data
    }

