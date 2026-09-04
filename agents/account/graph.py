"""Conversational Account Opening Subgraph and State Machine."""

from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState
from agents.account.nodes import (
    collect_profile_node,
    kyc_aml_node,
    aml_hitl_node,
    create_account_node,
)


def route_after_profile(state: BankingSessionState) -> str:
    data = state.get("account_data") or {}
    if data.get("step") == "KYC":
        return "kyc_aml"
    return END


def route_after_aml(state: BankingSessionState) -> str:
    data = state.get("account_data") or {}
    if data.get("aml_status") == "FLAGGED":
        return "aml_hitl"
    return "create_account"


# Build Account Subgraph
account_subgraph_builder = StateGraph(BankingSessionState)
account_subgraph_builder.add_node("collect_profile", collect_profile_node)
account_subgraph_builder.add_node("kyc_aml", kyc_aml_node)
account_subgraph_builder.add_node("aml_hitl", aml_hitl_node)
account_subgraph_builder.add_node("create_account", create_account_node)

account_subgraph_builder.add_edge(START, "collect_profile")
account_subgraph_builder.add_conditional_edges("collect_profile", route_after_profile, ["kyc_aml", END])
account_subgraph_builder.add_conditional_edges("kyc_aml", route_after_aml, ["aml_hitl", "create_account"])
account_subgraph_builder.add_edge("aml_hitl", "create_account")
account_subgraph_builder.add_edge("create_account", END)

account_subgraph = account_subgraph_builder.compile()
