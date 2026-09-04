"""Health Insurance, Life Insurance, and Banking Policy Tools."""

from typing import Dict, Any, Optional, List
from tools.base import ToolResult
from services.policies.policy_catalog import search_policies, get_policy_by_id, POLICY_CATALOG


async def get_policy_details_tool(
    policy_id: Optional[str] = None,
    category: Optional[str] = None,
    query: Optional[str] = None
) -> ToolResult:
    """Retrieves full policy details or searches policies matching the user request."""
    try:
        if policy_id:
            policy = get_policy_by_id(policy_id)
            if policy:
                return ToolResult(success=True, data={"policies": [policy], "total": 1})

        results = search_policies(category=category, query=query)
        if not results:
            # Fallback to general list if search was overly specific
            results = list(POLICY_CATALOG.values())[:4]

        return ToolResult(
            success=True,
            data={
                "policies": results,
                "total": len(results),
                "category": category or "ALL",
                "query": query or ""
            }
        )
    except Exception as exc:
        return ToolResult(success=False, error=f"Policy retrieval error: {str(exc)}")


async def compare_policies_tool(
    policy_a_id: str,
    policy_b_id: str
) -> ToolResult:
    """Compares two financial or insurance policies side-by-side."""
    try:
        pol_a = get_policy_by_id(policy_a_id)
        pol_b = get_policy_by_id(policy_b_id)

        if not pol_a or not pol_b:
            return ToolResult(
                success=False,
                error=f"Could not find one or both policies to compare ({policy_a_id}, {policy_b_id})."
            )

        return ToolResult(
            success=True,
            data={
                "policy_a": pol_a,
                "policy_b": pol_b,
                "comparison_keys": ["sum_insured", "annual_premium", "waiting_period", "target_audience"]
            }
        )
    except Exception as exc:
        return ToolResult(success=False, error=f"Policy comparison error: {str(exc)}")

