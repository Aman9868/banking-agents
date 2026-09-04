"""Personal Financial Management (PFM) and Insights Subgraph."""

from typing import Dict, Any
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import AIMessage
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from gateway.tool_gateway.gateway import ToolGateway
from gateway.tool_gateway.permissions import AgentRole
from agents.state import BankingSessionState, InsightsWorkflowData
import structlog

logger = structlog.get_logger(__name__)
tool_gateway = ToolGateway()


async def execute_insights_node(state: BankingSessionState) -> Dict[str, Any]:
    """Evaluates customer financial insights, spending breakdowns, and subscription audits."""
    data: InsightsWorkflowData = dict(state.get("insights_data") or {})
    action = data.get("action", "SPENDING")
    customer_id = state.get("customer_id", 1)

    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)

        # 1. Spending Breakdown
        if action == "SPENDING":
            result = await tool_gateway.execute_tool(
                agent_role=AgentRole.INSIGHTS_AGENT.value,
                tool_name="get_spending_insights",
                repo=repo,
                customer_id=customer_id,
                parameters={"days": data.get("days", 30)}
            )
            if not result.success:
                resp = f"Unable to fetch spending insights: {result.error}"
                return {"active_workflow": "NONE", "final_response": resp, "messages": [AIMessage(content=resp)]}

            info = result.data
            lines = [
                f"📊 **Monthly Spending Breakdown (Last {info['period_days']} Days)**",
                f"**Total Outflow:** ₹{info['total_spent']:,.2f}\n"
            ]
            for item in info["breakdown"]:
                lines.append(f"• **{item['category']}**: ₹{item['amount']:,.2f} ({item['percentage']}%)")

            lines.append(f"\n💡 *Top expense driver:* **{info['top_category']}**.")
            resp = "\n".join(lines)

            return {
                "active_workflow": "NONE",
                "insights_data": {},
                "final_response": resp,
                "messages": [AIMessage(content=resp)],
                "widget_type": "SPENDING_CHART",
                "widget_data": {
                    "total_spent": info["total_spent"],
                    "breakdown": info["breakdown"]
                }
            }

        # 2. Subscription Audit
        elif action == "SUBSCRIPTIONS":
            result = await tool_gateway.execute_tool(
                agent_role=AgentRole.INSIGHTS_AGENT.value,
                tool_name="detect_subscriptions",
                repo=repo,
                customer_id=customer_id,
                parameters={}
            )
            if not result.success:
                resp = f"Unable to audit subscriptions: {result.error}"
                return {"active_workflow": "NONE", "final_response": resp, "messages": [AIMessage(content=resp)]}

            info = result.data
            lines = [
                f"🔄 **Active Recurring Subscriptions Detected ({info['count']})**",
                f"**Total Monthly Commitment:** ₹{info['total_monthly_commitment']:,.2f}",
                f"**Projected Annual Cost:** ₹{info['annual_projected_cost']:,.2f}\n"
            ]
            for sub in info["subscriptions"]:
                lines.append(f"• **{sub['name']}**: ₹{sub['amount']:,.2f}/mo (Last paid: {sub['last_paid']})")

            resp = "\n".join(lines)
            return {
                "active_workflow": "NONE",
                "insights_data": {},
                "final_response": resp,
                "messages": [AIMessage(content=resp)],
                "widget_type": "SUBSCRIPTION_LIST",
                "widget_data": {
                    "total_monthly": info["total_monthly_commitment"],
                    "subscriptions": info["subscriptions"]
                }
            }

        # 3. Cashflow Prediction
        elif action == "CASHFLOW":
            debit = data.get("proposed_debit", 0.0)
            result = await tool_gateway.execute_tool(
                agent_role=AgentRole.INSIGHTS_AGENT.value,
                tool_name="predict_cashflow",
                repo=repo,
                customer_id=customer_id,
                parameters={"proposed_debit": debit}
            )
            if not result.success:
                resp = f"Cashflow projection failed: {result.error}"
                return {"active_workflow": "NONE", "final_response": resp, "messages": [AIMessage(content=resp)]}

            info = result.data
            status_badge = "✅ **Safe to Spend**" if info["is_safe"] else "⚠️ **Cashflow Alert: Low Cushion**"
            resp = (
                f"{status_badge}\n\n"
                f"• Current Balance: ₹{info['current_balance']:,.2f}\n"
                f"• Proposed Debit: ₹{info['proposed_debit']:,.2f}\n"
                f"• Upcoming Commitments (EMIs & Utilities): ₹{info['upcoming_commitments_total']:,.2f}\n"
                f"• **Projected Remaining Balance:** ₹{info['projected_remaining_balance']:,.2f}\n\n"
                + (
                    "You will comfortably maintain your minimum safety reserve."
                    if info["is_safe"]
                    else f"Warning: This will drop your safety buffer by ₹{info['cushion_deficit']:,.2f} before the next billing cycle."
                )
            )
            return {
                "active_workflow": "NONE",
                "insights_data": {},
                "final_response": resp,
                "messages": [AIMessage(content=resp)]
            }


