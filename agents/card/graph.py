"""Card Operations and Security Subgraph."""

import re
from typing import Dict, Any
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState, CardWorkflowData
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from gateway.tool_gateway.gateway import tool_gateway
from gateway.tool_gateway.permissions import AgentRole
from security.pii import mask_card_number
import structlog

logger = structlog.get_logger(__name__)


async def card_action_node(state: BankingSessionState) -> Dict[str, Any]:
    """Processes card security actions (freeze, unfreeze, limits, replace, status)."""
    customer_id = state.get("customer_id", 1)
    card_data = dict(state.get("card_data") or {})

    last_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_msg = msg.content.strip()
            break

    text_lower = last_msg.lower()
    card_type = card_data.get("card_type") or ("CREDIT" if "credit" in text_lower else "DEBIT")

    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)

        # 1. Emergency Freeze / Stolen reporting
        if any(k in text_lower for k in ["freeze", "stolen", "lost"]):
            res = await tool_gateway.execute_tool(
                agent_role=AgentRole.CARD_AGENT.value,
                tool_name="freeze_card",
                repo=repo,
                customer_id=customer_id,
                parameters={"card_type": card_type}
            )
            resp = res.data.get("message", "Card has been frozen.")

        # 2. Unfreeze
        elif "unfreeze" in text_lower:
            res = await tool_gateway.execute_tool(
                agent_role=AgentRole.CARD_AGENT.value,
                tool_name="unfreeze_card",
                repo=repo,
                customer_id=customer_id,
                parameters={"card_type": card_type}
            )
            resp = res.data.get("message", "Card has been unfrozen.")

        # 3. Replace card
        elif "replace" in text_lower:
            res = await tool_gateway.execute_tool(
                agent_role=AgentRole.CARD_AGENT.value,
                tool_name="replace_card",
                repo=repo,
                customer_id=customer_id,
                parameters={"card_type": card_type, "reason": "LOST"}
            )
            resp = res.data.get("message", "Replacement card has been ordered.")

        # 4. Set Limits
        elif any(k in text_lower for k in ["limit", "set online", "atm limit"]):
            limit_match = re.search(r"(?:₹|rs\.?)?\s*(\d+(?:,\d+)*(?:\.\d+)?)", last_msg)
            online_limit = float(limit_match.group(1).replace(",", "")) if limit_match else 25000.0
            res = await tool_gateway.execute_tool(
                agent_role=AgentRole.CARD_AGENT.value,
                tool_name="set_card_limits",
                repo=repo,
                customer_id=customer_id,
                parameters={"card_type": card_type, "online_limit": online_limit}
            )
            resp = res.data.get("message", "Card limits updated successfully.")

        # 5. Default: List Cards / Status
        else:
            res = await tool_gateway.execute_tool(
                agent_role=AgentRole.CARD_AGENT.value,
                tool_name="get_cards",
                repo=repo,
                customer_id=customer_id,
                parameters={}
            )
            if res.success and res.data.get("cards"):
                card_list = "\n".join([
                    f"• {c['network']} {c['card_type']} ({c['masked_number']}) — Status: {c['status']}, Online Limit: ₹{c['daily_online_limit']:,.2f}"
                    for c in res.data["cards"]
                ])
                resp = f"Here are your registered cards:\n{card_list}\n\nYou can freeze, unfreeze, replace, or change spending limits anytime."
            else:
                resp = "No registered cards found for your profile."

    return {
        "active_workflow": "NONE",
        "card_data": {},
        "final_response": resp,
        "messages": [AIMessage(content=resp)]
    }


# Build Card Subgraph
card_subgraph_builder = StateGraph(BankingSessionState)
card_subgraph_builder.add_node("card_action", card_action_node)
card_subgraph_builder.add_edge(START, "card_action")
card_subgraph_builder.add_edge("card_action", END)

card_subgraph = card_subgraph_builder.compile()

