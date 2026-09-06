"""Agent Identity and Tool Permission Engine (RBAC)."""

from typing import Set, Dict
from enum import Enum


class AgentRole(str, Enum):
    SUPERVISOR = "supervisor"
    TRANSFER_AGENT = "transfer_agent"
    ACCOUNT_AGENT = "account_agent"
    CARD_AGENT = "card_agent"
    LOAN_AGENT = "loan_agent"
    PAYMENTS_AGENT = "payments_agent"
    SUPPORT_AGENT = "support_agent"
    INSIGHTS_AGENT = "insights_agent"
    WEALTH_ADVISOR = "wealth_advisor"
    POLICY_ADVISOR = "policy_advisor"


class ToolPermissionDeniedError(Exception):
    """Raised when an agent attempts to execute a tool outside its allowed boundaries."""
    pass


# Strict Least-Privilege Permission Matrix for all specialized banking agents
AGENT_TOOL_PERMISSIONS: Dict[AgentRole, Set[str]] = {
    AgentRole.SUPERVISOR: {
        "get_balance",
        "get_accounts",
        "get_cards",
        "search_knowledge_base",
        "add_beneficiary",
        "get_transaction",
        "get_recent_transactions",
        "verify_aadhaar",
        "verify_live_face_kyc",
        "verify_gst",
        "generate_account_statement",
        "explain_transaction",
        "calculate_sip",
        "activate_sip_mandate",
        "recommend_portfolio",
        "search_market_stocks",
        "search_web_banking",
        "get_policy_details",
        "compare_policies",
    },
    AgentRole.TRANSFER_AGENT: {
        "get_balance",
        "get_beneficiary",
        "list_beneficiaries",
        "add_beneficiary",
        "initiate_transfer",
        "get_transaction",
        "get_recent_transactions",
    },

    AgentRole.ACCOUNT_AGENT: {
        "check_customer_profile",
        "create_account",
        "verify_aadhaar",
        "verify_live_face_kyc",
        "verify_gst",
    },
    AgentRole.CARD_AGENT: {
        "get_cards",
        "freeze_card",
        "unfreeze_card",
        "replace_card",
        "set_card_limits",
    },
    AgentRole.LOAN_AGENT: {
        "calculate_emi",
        "check_loan_eligibility",
        "apply_loan",
        "get_loan_status",
    },
    AgentRole.PAYMENTS_AGENT: {
        "get_billers",
        "fetch_bill",
        "pay_bill",
        "verify_upi_id",
        "get_balance",
    },
    AgentRole.SUPPORT_AGENT: {
        "get_transaction",
        "get_recent_transactions",
        "get_accounts",
        "create_support_ticket",
        "search_knowledge_base",
        "search_web_banking",
        "explain_transaction",
        "get_policy_details",
    },
    AgentRole.INSIGHTS_AGENT: {
        "get_spending_insights",
        "detect_subscriptions",
        "predict_cashflow",
        "get_balance",
        "get_accounts",
        "generate_account_statement",
        "explain_transaction",
        "calculate_sip",
        "recommend_portfolio",
    },
    AgentRole.WEALTH_ADVISOR: {
        "calculate_sip",
        "activate_sip_mandate",
        "recommend_portfolio",
        "search_market_stocks",
        "search_web_banking",
        "get_balance",
        "get_accounts",
    },
    AgentRole.POLICY_ADVISOR: {
        "get_policy_details",
        "compare_policies",
        "search_knowledge_base",
        "get_accounts",
    }
}


def authorize_tool_execution(agent_role: str, tool_name: str) -> bool:
    """Validates whether the specified agent is authorized to call the tool."""
    try:
        role = AgentRole(agent_role)
    except ValueError:
        raise ToolPermissionDeniedError(f"Unknown or invalid agent identity: {agent_role}")

    allowed_tools = AGENT_TOOL_PERMISSIONS.get(role, set())
    if tool_name not in allowed_tools:
        raise ToolPermissionDeniedError(
            f"Agent '{agent_role}' is not authorized to execute tool '{tool_name}'. "
            f"Allowed tools: {sorted(list(allowed_tools))}"
        )
    return True
