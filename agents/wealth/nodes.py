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
from agents.wealth.prompts import (
    WEALTH_ADVISOR_SYSTEM_PROMPT,
    STUDENT_SIP_RECOMMENDATION_PROMPT,
    GENERAL_SIP_RECOMMENDATION_PROMPT,
    build_wealth_stock_market_user_prompt,
    build_wealth_sip_user_prompt,
)
import structlog

logger = structlog.get_logger(__name__)


async def wealth_advisor_node(state: BankingSessionState) -> Dict[str, Any]:
    """
    Orchestrates personalized wealth advisory:
    1. SIP compound calculator tailored for individual and institutional investors.
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

    # Extract or infer investment parameters (default to GENERAL investor, NOT student)
    wealth_data = dict(state.get("wealth_data") or {})
    persona = wealth_data.get("user_persona")
    student_keywords = ["college student", "college", "university", "freshman", "sstudnet", "campus", "tuition fee", "pocket money"]
    if any(w in last_msg.lower() for w in student_keywords):
        persona = "STUDENT"
    elif not persona:
        persona = "GENERAL"

    risk = wealth_data.get("risk_profile") or "MODERATE"
    if any(w in last_msg.lower() for w in ["aggressive", "high risk", "max return"]):
        risk = "AGGRESSIVE"
    elif any(w in last_msg.lower() for w in ["conservative", "safe", "low risk"]):
        risk = "CONSERVATIVE"

    # Extract monthly amount vs target future corpus
    monthly_amt = wealth_data.get("monthly_investment")
    target_corpus = wealth_data.get("target_corpus")

    # Detect future target corpus (e.g. "1 cr", "crore", "target", "need in future")
    cr_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:crore|cr)s?", last_msg, re.IGNORECASE)
    if cr_match:
        target_corpus = float(cr_match.group(1)) * 10000000.0
        wealth_data["target_corpus"] = target_corpus

    is_per_month = any(w in last_msg.lower() for w in ["per month", "pe rmonth", "monthly", "savings of", "save", "a month", "/mo", "sip"])

    if not monthly_amt or is_per_month:
        lakh_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|lac)s?", last_msg, re.IGNORECASE)
        k_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:k|thousand)s?", last_msg, re.IGNORECASE)
        amt_match = re.search(r"(?:savings of|save|invest|sip of)?\s*(?:₹|rs\.?|inr)?\s*(\d{1,6}(?:,\d{3})*(?:\.\d+)?)\s*(?:pe\s*r\s*month|per\s*month|monthly|a\s*month|/mo)?", last_msg, re.IGNORECASE)

        if is_per_month and amt_match and amt_match.group(1):
            try:
                val = float(amt_match.group(1).replace(",", ""))
                if val > 50 and val not in [2024, 2025, 2026, 2027]:
                    monthly_amt = val
            except (ValueError, AttributeError):
                pass
        elif k_match and is_per_month:
            monthly_amt = float(k_match.group(1)) * 1000.0
        elif not target_corpus and lakh_match:
            monthly_amt = float(lakh_match.group(1)) * 100000.0

    if not monthly_amt or monthly_amt <= 50:
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
        try:
            async with AsyncSessionLocal() as session:
                repo = BankingRepository(session)
                tool_res = await tool_gateway.execute_tool(
                    agent_role=AgentRole.WEALTH_ADVISOR.value,
                    tool_name="search_market_stocks",
                    repo=repo,
                    customer_id=customer_id,
                    parameters={"query": search_query, "symbol": sym_match}
                )
        except Exception as db_exc:
            logger.warning("DB session unavailable for search_market_stocks, invoking tool directly", error=str(db_exc))
            from tools.wealth import search_market_stocks_tool
            tool_res = await search_market_stocks_tool(query=search_query, symbol=sym_match)

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
            user_prompt = build_wealth_stock_market_user_prompt(
                customer_name=customer_name,
                last_msg=last_msg,
                quote_info=quote_info,
                web_results=web_results
            )
            llm_res = await llm_gateway.invoke_chat([
                SystemMessage(content=WEALTH_ADVISOR_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt)
            ], model_tier="routing")

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
    try:
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
    except Exception as db_exc:
        logger.warning("DB session unavailable for calculate_sip, invoking tool directly", error=str(db_exc))
        from tools.wealth import calculate_sip_tool
        tool_res = await calculate_sip_tool(
            monthly_investment=monthly_amt,
            tenure_years=5,
            annual_expected_cagr=12.0,
            user_persona=persona,
            risk_profile=risk
        )

    sip_calc = (tool_res.data or {}).get("sip_calculation", {})
    strategy = (tool_res.data or {}).get("strategy", {})

    total_inv_str = f"₹{sip_calc.get('total_invested', 0):,.2f}"
    future_val_str = f"₹{sip_calc.get('future_value', 0):,.2f}"
    gain_str = f"₹{sip_calc.get('estimated_gain', 0):,.2f}"
    multiplier = sip_calc.get("growth_multiplier", 1.4)

    icon = "🎓" if persona == "STUDENT" else "📈"
    ten_yr_val = sip_calc.get("projections", [{}, {}, {}, {"estimated_value": 0}])[3].get("estimated_value", 0)

    # Conversational Advice formatted with clean Markdown tables
    advice_lines = [
        f"Hello {first_name}! {icon} **{strategy.get('headline', 'Personalized SIP Investment Plan')}**\n",
        f"{strategy.get('guidance', '')}\n",
        "### 📊 5-Year Compounding Projection",
        "| Metric | Projected Value |",
        "| :--- | :--- |",
        f"| **Monthly Contribution** | ₹{monthly_amt:,.2f} |",
        f"| **Total Principal (5 Yrs)** | **{total_inv_str}** |",
        f"| **Projected Maturity (12% CAGR)** | **{future_val_str}** |",
        f"| **Estimated Wealth Gain** | **+{gain_str}** ({multiplier}x growth) |",
        f"| **10-Year Milestone** | ₹{ten_yr_val:,.2f} |\n",
        "### 🎯 Recommended Asset Allocation",
        "| Category | Share | Monthly (₹) | Top Direct Funds | Expense |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    for alloc in strategy.get("allocations", []):
        funds_short = ", ".join(alloc.get("recommended_funds", [])[:2])
        advice_lines.append(
            f"| {alloc['category']} | {alloc['percentage']}% | ₹{alloc['amount']:,.2f} | {funds_short} | {alloc.get('expense_ratio', '0.20%')} |"
        )

    advice_lines.append(
        "\n*Note: Mutual fund investments are subject to market risks. Projections assume ~12% historical CAGR.*"
    )
    advice_lines.append(
        f"\nWould you like me to set up an automated SIP mandate of **₹{monthly_amt:,.2f}/month** from your NovaBank account, or adjust the parameters?"
    )

    full_advice = "\n".join(advice_lines)

    # Enhance with LLM Wealth Advisor persona synthesis
    try:
        persona_instructions = STUDENT_SIP_RECOMMENDATION_PROMPT if persona == "STUDENT" else GENERAL_SIP_RECOMMENDATION_PROMPT
        system_content = f"{WEALTH_ADVISOR_SYSTEM_PROMPT}\n\n{persona_instructions}".strip()

        user_prompt = build_wealth_sip_user_prompt(
            customer_name=customer_name,
            persona=persona,
            risk=risk,
            last_msg=last_msg,
            monthly_amt=monthly_amt,
            target_corpus=target_corpus,
            total_inv_str=total_inv_str,
            future_val_str=future_val_str,
            gain_str=gain_str,
            multiplier=multiplier,
            ten_yr_val=ten_yr_val,
            strategy=strategy
        )

        llm_res = await llm_gateway.invoke_chat([
            SystemMessage(content=system_content),
            HumanMessage(content=user_prompt)
        ], model_tier="routing")

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

