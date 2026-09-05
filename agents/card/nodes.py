"""Card Operations and Security Node Functions."""

import re
from typing import Dict, Any
from langchain_core.messages import AIMessage, HumanMessage
from agents.state import BankingSessionState, CardWorkflowData
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from gateway.tool_gateway.gateway import tool_gateway
from gateway.tool_gateway.permissions import AgentRole
from security.pii import mask_card_number
from agents.card.prompts import (
    build_cards_list_response,
    build_freeze_card_response,
    build_unfreeze_card_response,
    build_replace_card_response,
    build_set_limits_response,
)
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
    sub_intent = (state.get("current_sub_intent") or "").upper()
    card_type = card_data.get("card_type") or ("CREDIT" if "credit" in text_lower else "DEBIT")

    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)

        # 1. Emergency Freeze / Stolen reporting
        if sub_intent == "FREEZE_CARD" or any(k in text_lower for k in ["freeze", "stolen", "lost", "block"]):
            res = await tool_gateway.execute_tool(
                agent_role=AgentRole.CARD_AGENT.value,
                tool_name="freeze_card",
                repo=repo,
                customer_id=customer_id,
                parameters={"card_type": card_type}
            )
            raw_msg = res.data.get("message", "Card has been frozen.") if res.success else res.error
            resp = build_freeze_card_response(card_type, raw_msg)

        # 2. Unfreeze
        elif sub_intent == "UNFREEZE_CARD" or "unfreeze" in text_lower:
            res = await tool_gateway.execute_tool(
                agent_role=AgentRole.CARD_AGENT.value,
                tool_name="unfreeze_card",
                repo=repo,
                customer_id=customer_id,
                parameters={"card_type": card_type}
            )
            raw_msg = res.data.get("message", "Card has been unfrozen.") if res.success else res.error
            resp = build_unfreeze_card_response(card_type, raw_msg)

        # 3. Replace card
        elif sub_intent == "REPLACE_CARD" or any(k in text_lower for k in ["replace", "reissue", "replacement"]):
            res = await tool_gateway.execute_tool(
                agent_role=AgentRole.CARD_AGENT.value,
                tool_name="replace_card",
                repo=repo,
                customer_id=customer_id,
                parameters={"card_type": card_type, "reason": "LOST"}
            )
            raw_msg = res.data.get("message", "Replacement card has been ordered.") if res.success else res.error
            resp = build_replace_card_response(card_type, raw_msg)

        # 4. Set Limits
        elif sub_intent == "SET_LIMIT" or any(k in text_lower for k in ["limit", "set online", "atm limit"]):
            online_limit = card_data.get("online_limit")
            if not online_limit:
                lakh_m = re.search(r"(\d+(?:\.\d+)?)\s*(?:lakh|lac)s?", text_lower)
                if lakh_m:
                    online_limit = float(lakh_m.group(1)) * 100000.0
                else:
                    k_m = re.search(r"(\d+(?:\.\d+)?)\s*k\b", text_lower)
                    if k_m:
                        online_limit = float(k_m.group(1)) * 1000.0
                    else:
                        limit_match = re.search(r"(?:₹|rs\.?)?\s*(\d+(?:,\d+)*(?:\.\d+)?)", last_msg)
                        online_limit = float(limit_match.group(1).replace(",", "")) if limit_match else 25000.0

            res = await tool_gateway.execute_tool(
                agent_role=AgentRole.CARD_AGENT.value,
                tool_name="set_card_limits",
                repo=repo,
                customer_id=customer_id,
                parameters={"card_type": card_type, "online_limit": online_limit}
            )
            resp = build_set_limits_response(card_type, online_limit)

        # 5. Default / List Cards / Status
        else:
            res = await tool_gateway.execute_tool(
                agent_role=AgentRole.CARD_AGENT.value,
                tool_name="get_cards",
                repo=repo,
                customer_id=customer_id,
                parameters={}
            )
            if res.success and res.data.get("cards"):
                resp = build_cards_list_response(res.data["cards"])
            else:
                resp = "No registered cards found for your profile."

    return {
        "active_workflow": "NONE",
        "card_data": {},
        "final_response": resp,
        "messages": [AIMessage(content=resp)]
    }

