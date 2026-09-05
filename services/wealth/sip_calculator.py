"""Systematic Investment Plan (SIP) Calculator and Portfolio Recommendation Engine."""

from typing import Dict, Any, List, Optional
import math


def calculate_sip_returns(
    monthly_investment: float,
    tenure_years: int = 5,
    annual_expected_cagr: float = 12.0,
    annual_inflation_rate: float = 6.0
) -> Dict[str, Any]:
    """
    Calculates compound growth of a monthly SIP:
    Formula: M = P * ((1 + i)^n - 1) / i * (1 + i)
    where:
      P = monthly deposit
      i = annual_rate / 12
      n = tenure_years * 12
    """
    if monthly_investment <= 0:
        monthly_investment = 500.0  # Default minimum micro-SIP

    monthly_rate = (annual_expected_cagr / 100.0) / 12.0
    total_months = tenure_years * 12
    total_invested = monthly_investment * total_months

    if monthly_rate > 0:
        future_value = monthly_investment * ((math.pow(1 + monthly_rate, total_months) - 1) / monthly_rate) * (1 + monthly_rate)
    else:
        future_value = total_invested

    estimated_wealth_gain = max(0.0, future_value - total_invested)

    # Inflation adjusted real purchasing power
    real_rate = ((1 + annual_expected_cagr / 100.0) / (1 + annual_inflation_rate / 100.0)) - 1.0
    real_monthly_rate = real_rate / 12.0
    if real_monthly_rate > 0:
        inflation_adjusted_value = monthly_investment * ((math.pow(1 + real_monthly_rate, total_months) - 1) / real_monthly_rate) * (1 + real_monthly_rate)
    else:
        inflation_adjusted_value = future_value

    # Milestone milestones (1y, 3y, 5y, 10y)
    projections: List[Dict[str, Any]] = []
    for yr in [1, 3, 5, 10]:
        n_m = yr * 12
        inv = monthly_investment * n_m
        fv = monthly_investment * ((math.pow(1 + monthly_rate, n_m) - 1) / monthly_rate) * (1 + monthly_rate)
        projections.append({
            "years": yr,
            "total_invested": round(inv, 2),
            "estimated_value": round(fv, 2),
            "wealth_gain": round(fv - inv, 2),
        })

    return {
        "monthly_investment": round(monthly_investment, 2),
        "tenure_years": tenure_years,
        "annual_cagr": annual_expected_cagr,
        "total_invested": round(total_invested, 2),
        "future_value": round(future_value, 2),
        "estimated_gain": round(estimated_wealth_gain, 2),
        "inflation_adjusted_value": round(inflation_adjusted_value, 2),
        "growth_multiplier": round(future_value / total_invested, 2) if total_invested > 0 else 1.0,
        "projections": projections
    }


def recommend_investment_strategy(
    monthly_amount: float,
    user_persona: str = "STUDENT",
    risk_profile: str = "MODERATE"
) -> Dict[str, Any]:
    """
    Generates personalized, student-friendly or professional investment portfolio advice.
    """
    persona = user_persona.upper()
    risk = risk_profile.upper()

    # Special handling strictly for college students when explicitly identified
    if "STUDENT" in persona:
        headline = "Student Starter Wealth Plan: Low Risk, Zero Hidden Fees & High Compounding"
        guidance = (
            f"As a student investing ₹{monthly_amount:,.2f}/month, your biggest superpower is **Time & Compounding**! "
            "Rather than high-risk speculative trading, the smartest strategy is starting micro-SIPs in low-cost, "
            "zero-commission Direct Index Funds and building an emergency liquid buffer."
        )
        allocations = [
            {
                "category": "Nifty 50 Index Fund (Large Cap)",
                "percentage": 60,
                "amount": round(monthly_amount * 0.60, 2),
                "recommended_funds": ["UTI Nifty 50 Index Fund (Direct)", "Navi Nifty 50 Index Fund (Direct)"],
                "expense_ratio": "0.15% - 0.20%",
                "rationale": "Invests in top 50 Indian companies with rock-bottom expense ratios, ideal for long-term compounding."
            },
            {
                "category": "Flexi-Cap / Mid-Cap Fund",
                "percentage": 25,
                "amount": round(monthly_amount * 0.25, 2),
                "recommended_funds": ["Parag Parikh Flexi Cap Fund (Direct)", "Motilal Oswal Midcap Fund (Direct)"],
                "expense_ratio": "0.65% - 0.75%",
                "rationale": "Delivers growth kicker across promising mid-sized Indian enterprises."
            },
            {
                "category": "Liquid Emergency / Safe Buffer",
                "percentage": 15,
                "amount": round(monthly_amount * 0.15, 2),
                "recommended_funds": ["ICICI Prudential Liquid Fund (Direct)", "NovaBank High-Yield Auto-Sweep RD"],
                "expense_ratio": "0.18%",
                "rationale": "Instant liquidity for academic expenses or urgent emergencies without penalty."
            }
        ]
        key_tips = [
            "Start with as little as ₹500/month via auto-debit on the 1st or 5th of each month.",
            "Choose 'Direct - Growth' plans instead of Regular plans to save up to 1.5% annually in distributor commission.",
            "Increase your SIP amount by 10% each year (Step-Up SIP) as your income rises."
        ]

    elif risk == "AGGRESSIVE":
        headline = "Aggressive Growth Wealth Portfolio: Maximum Alpha & Compounding"
        guidance = (
            f"With an aggressive appetite and ₹{monthly_amount:,.2f}/month, your asset allocation focuses on high-beta "
            "equities and small/mid-cap champions capable of beating index benchmarks over a 5-10 year horizon."
        )
        allocations = [
            {
                "category": "Nifty 50 / Large Cap Index",
                "percentage": 40,
                "amount": round(monthly_amount * 0.40, 2),
                "recommended_funds": ["HDFC Index Fund Nifty 50", "Nippon India Large Cap Fund"],
                "expense_ratio": "0.18%",
                "rationale": "Core foundation anchor."
            },
            {
                "category": "Mid & Small Cap Alpha",
                "percentage": 40,
                "amount": round(monthly_amount * 0.40, 2),
                "recommended_funds": ["Nippon India Small Cap Fund", "HDFC Mid-Cap Opportunities Fund"],
                "expense_ratio": "0.72%",
                "rationale": "High-octane growth potential for long horizons."
            },
            {
                "category": "Global / Technology Sector",
                "percentage": 20,
                "amount": round(monthly_amount * 0.20, 2),
                "recommended_funds": ["Mirae Asset NYSE FANG+ ETF Fund", "Tata Digital India Fund"],
                "expense_ratio": "0.55%",
                "rationale": "Geographic diversification and tech secular growth."
            }
        ]
        key_tips = [
            "Expect market volatility: stay invested during market dips to average down unit costs.",
            "Review your portfolio annually rather than daily."
        ]

    else:  # MODERATE / BALANCED
        headline = "Balanced Wealth Builder: Moderate Growth with Capital Stability"
        guidance = (
            f"For a balanced risk profile and ₹{monthly_amount:,.2f}/month, we recommend an all-weather portfolio "
            "combining large-cap equities, flexi-cap dynamism, and debt/gold stability."
        )
        allocations = [
            {
                "category": "Large Cap Index / Bluechip",
                "percentage": 50,
                "amount": round(monthly_amount * 0.50, 2),
                "recommended_funds": ["UTI Nifty 50 Index Fund", "Mirae Asset Large Cap Fund"],
                "expense_ratio": "0.20%",
                "rationale": "Steady returns with leading bluechips."
            },
            {
                "category": "Flexi-Cap / Balanced Advantage",
                "percentage": 30,
                "amount": round(monthly_amount * 0.30, 2),
                "recommended_funds": ["Parag Parikh Flexi Cap Fund", "ICICI Balanced Advantage Fund"],
                "expense_ratio": "0.68%",
                "rationale": "Dynamic asset allocation balancing debt and equity."
            },
            {
                "category": "Gold / Sovereign Debt",
                "percentage": 20,
                "amount": round(monthly_amount * 0.20, 2),
                "recommended_funds": ["SBI Gold ETF / SGB", "Aditya Birla Sun Life Short Term Debt"],
                "expense_ratio": "0.25%",
                "rationale": "Hedge against inflation and economic uncertainty."
            }
        ]
        key_tips = [
            "Rebalance your allocation once a year if equity exceeds your target percentage.",
            "Use auto-sweep for idle bank balances."
        ]

    return {
        "headline": headline,
        "monthly_amount": monthly_amount,
        "user_persona": persona,
        "risk_profile": risk,
        "guidance": guidance,
        "allocations": allocations,
        "key_tips": key_tips
    }

