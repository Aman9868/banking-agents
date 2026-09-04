"""Policy, Insurance Advisory, and Government Schemes Node Functions."""

import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from agents.state import BankingSessionState, PolicyWorkflowData
from gateway.tool_gateway.gateway import tool_gateway
from gateway.tool_gateway.permissions import AgentRole
from gateway.llm.client import llm_gateway
from database.connection import AsyncSessionLocal
from database.repositories.banking_repo import BankingRepository
from agents.policy.prompts import POLICY_ADVISOR_SYSTEM_PROMPT
import structlog

logger = structlog.get_logger(__name__)


async def policy_orchestrator_node(state: BankingSessionState) -> Dict[str, Any]:
    """
    Orchestrates insurance, government scheme, and banking policy inquiries:
    1. Health Insurance (Student Health Shield, Family Floater, Super Top-Up)
    2. Life Insurance (Pure Term Life, PMJJBY, PMSBY)
    3. Government Investment Schemes (PPF, NPS, APY, Sukanya Samriddhi)
    4. Banking Deposit Policies (Fixed Deposits, Recurring Deposits)
    """
    last_msg = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_msg = msg.content.strip()
            break

    customer_id = state.get("customer_id", 1)
    customer_name = state.get("customer_name", "Valued Customer")
    first_name = customer_name.split(" ")[0] if customer_name else "there"
    msg_low = last_msg.lower()

    # Determine policy category
    policy_data = dict(state.get("policy_data") or {})
    category = policy_data.get("category")

    if any(k in msg_low for k in ["health", "mediclaim", "hospital", "doctor", "hralth"]):
        category = "HEALTH"
    elif any(k in msg_low for k in ["term life", "pure term", "life insurance", "term plan"]):
        category = "LIFE"
    elif any(k in msg_low for k in ["pmjjby", "pmsby", "ppf", "nps", "apy", "sukanya", "govt scheme", "government"]):
        category = "GOVT_SCHEME"
    elif any(k in msg_low for k in ["fd", "rd", "deposit", "fixed deposit", "recurring", "interest rate"]):
        category = "BANKING_DEPOSIT"
    elif not category:
        category = "ALL"

    policy_data["category"] = category
    policy_data["query"] = last_msg

    # Execute policy retrieval tool
    async with AsyncSessionLocal() as session:
        repo = BankingRepository(session)
        tool_res = await tool_gateway.execute_tool(
            agent_role=AgentRole.POLICY_ADVISOR.value,
            tool_name="get_policy_details",
            repo=repo,
            customer_id=customer_id,
            parameters={"category": category if category != "ALL" else None, "query": last_msg}
        )

    policies = (tool_res.data or {}).get("policies", [])

    # Format conversational policy advisory
    cat_titles = {
        "HEALTH": "🏥 Health & Medical Insurance Solutions",
        "LIFE": "🛡️ Life Protection & Term Insurance",
        "GOVT_SCHEME": "🏛️ Government Social Security & Sovereign Wealth Schemes",
        "BANKING_DEPOSIT": "🏦 NovaBank Guaranteed Deposit & Savings Policies",
        "ALL": "📋 NovaBank Financial & Insurance Policy Catalog"
    }

    heading = cat_titles.get(category, "📋 NovaBank Policy Catalog")
    response_lines = [
        f"Hello {first_name}! Here is our comprehensive overview of **{heading}**:\n"
    ]

    for i, pol in enumerate(policies[:4], 1):
        response_lines.append(f"### {i}. {pol['title']}")
        response_lines.append(f"• **Target Group**: {pol.get('target_audience')}")
        response_lines.append(f"• **Coverage / Sum Insured**: **{pol.get('sum_insured')}**")
        response_lines.append(f"• **Premium / Cost**: **{pol.get('annual_premium')}**")
        response_lines.append(f"• **Waiting Period**: {pol.get('waiting_period')}")
        response_lines.append("• **Key Features**:")
        for h in pol.get("highlights", [])[:3]:
            response_lines.append(f"  - {h}")
        response_lines.append("")

    response_lines.append(
        "💡 *Tax Savings Tip: Health insurance premiums qualify for tax deductions up to ₹25,000 under Section 80D, "
        "and life insurance/PPF premiums qualify for up to ₹1,50,000 under Section 80C.*"
    )
    response_lines.append(
        "\nWould you like me to compare any of these policies or help you enroll directly through your NovaBank account?"
    )

    full_resp = "\n".join(response_lines)

    # Enhance with LLM Policy Advisor persona synthesis
    try:
        user_prompt = (
            f"Customer Name: {customer_name}\n"
            f"Requested Category: {category}\n"
            f"Customer Query: \"{last_msg}\"\n\n"
            f"RETRIEVED POLICIES & SCHEMES:\n{json.dumps(policies[:4])}\n\n"
            "Synthesize this policy catalog information into an authoritative, clear, and reassuring advisory response."
        )
        llm_res = await llm_gateway.invoke_chat([
            SystemMessage(content=POLICY_ADVISOR_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt)
        ], model_tier="reasoning")

        if llm_res.provider != "deterministic_fallback" and len(llm_res.content.strip()) > 60:
            full_resp = llm_res.content.strip()
    except Exception as exc:
        logger.warning("LLM policy advisory invocation failed, falling back to structured template", error=str(exc))

    widget_data = {
        "category": category,
        "policies": policies[:6],
        "customer_name": customer_name
    }

    return {
        "active_workflow": "POLICY_ACTION",
        "current_intent": "POLICY_INQUIRY",
        "current_sub_intent": state.get("current_sub_intent") or "BANKING_POLICY",
        "final_response": full_resp,
        "messages": [AIMessage(content=full_resp)],
        "widget_type": "POLICY_CARD_WIDGET",
        "widget_data": widget_data,
        "policy_data": policy_data
    }

