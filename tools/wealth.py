"""Wealth Advisory, SIP Planning, and Market Search Banking Tools."""

from typing import Dict, Any, Optional
from tools.base import ToolResult
from services.wealth.sip_calculator import calculate_sip_returns, recommend_investment_strategy
from services.market.free_search import free_market_service


async def calculate_sip_tool(
    monthly_investment: float,
    tenure_years: int = 5,
    annual_expected_cagr: float = 12.0,
    user_persona: str = "GENERAL",
    risk_profile: str = "MODERATE"
) -> ToolResult:
    """Calculates compound SIP growth and provides personalized portfolio allocation."""
    try:
        sip_data = calculate_sip_returns(
            monthly_investment=monthly_investment,
            tenure_years=tenure_years,
            annual_expected_cagr=annual_expected_cagr
        )
        strategy = recommend_investment_strategy(
            monthly_amount=monthly_investment,
            user_persona=user_persona,
            risk_profile=risk_profile
        )

        return ToolResult(
            success=True,
            data={
                "sip_calculation": sip_data,
                "strategy": strategy
            }
        )
    except Exception as exc:
        return ToolResult(success=False, error=f"SIP calculation error: {str(exc)}")


async def recommend_portfolio_tool(
    monthly_amount: float,
    user_persona: str = "GENERAL",
    risk_profile: str = "MODERATE"
) -> ToolResult:
    """Generates a personalized investment allocation plan based on customer persona."""
    try:
        strategy = recommend_investment_strategy(
            monthly_amount=monthly_amount,
            user_persona=user_persona,
            risk_profile=risk_profile
        )
        return ToolResult(success=True, data=strategy)
    except Exception as exc:
        return ToolResult(success=False, error=f"Portfolio recommendation error: {str(exc)}")


async def search_market_stocks_tool(
    query: str,
    symbol: Optional[str] = None
) -> ToolResult:
    """Performs free web market search or fetches live stock quotes using DuckDuckGo/Yahoo Finance."""
    try:
        results = {}
        if symbol:
            quote = await free_market_service.get_stock_quote(symbol)
            results["quote"] = quote

        web_results = await free_market_service.search_web_market(query=query, max_results=4)
        results["web_results"] = web_results
        results["query"] = query

        return ToolResult(success=True, data=results)
    except Exception as exc:
        return ToolResult(success=False, error=f"Market search error: {str(exc)}")

