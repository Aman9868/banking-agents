"""Controlled Money Transfer Subgraph with Policy Engine, Fraud Scoring, and HITL Checkpoints."""

from typing import List
from langgraph.graph import StateGraph, START, END
from agents.state import BankingSessionState
from agents.transfer.nodes import (
    resolve_transfer_entities_node,
    parallel_fraud_scoring_node,
    parallel_aml_screening_node,
    parallel_ledger_verification_node,
    policy_aggregator_node,
    transfer_hitl_node,
    execute_transfer_node,
)


def route_after_resolve(state: BankingSessionState) -> List[str]:
    data = state.get("transfer_data") or {}
    if data.get("step") == "SECURITY_FANOUT":
        return ["parallel_fraud_scoring", "parallel_aml_screening", "parallel_ledger_verification"]
    return [END]


def route_after_policy(state: BankingSessionState) -> str:
    data = state.get("transfer_data") or {}
    if data.get("step") == "HITL_PAUSE":
        return "transfer_hitl"
    elif data.get("step") == "EXECUTE":
        return "execute_transfer"
    return END


# Build Transfer Subgraph with LangGraph Fan-Out Architecture
transfer_subgraph_builder = StateGraph(BankingSessionState)
transfer_subgraph_builder.add_node("resolve_entities", resolve_transfer_entities_node)
transfer_subgraph_builder.add_node("parallel_fraud_scoring", parallel_fraud_scoring_node)
transfer_subgraph_builder.add_node("parallel_aml_screening", parallel_aml_screening_node)
transfer_subgraph_builder.add_node("parallel_ledger_verification", parallel_ledger_verification_node)
transfer_subgraph_builder.add_node("policy_aggregator", policy_aggregator_node)
transfer_subgraph_builder.add_node("transfer_hitl", transfer_hitl_node)
transfer_subgraph_builder.add_node("execute_transfer", execute_transfer_node)

transfer_subgraph_builder.add_edge(START, "resolve_entities")

# 1. Parallel Fan-Out: resolve_entities concurrently triggers 3 security checks
transfer_subgraph_builder.add_conditional_edges(
    "resolve_entities",
    route_after_resolve,
    ["parallel_fraud_scoring", "parallel_aml_screening", "parallel_ledger_verification", END]
)

# 2. Parallel Fan-In: all 3 branches converge into policy_aggregator
transfer_subgraph_builder.add_edge("parallel_fraud_scoring", "policy_aggregator")
transfer_subgraph_builder.add_edge("parallel_aml_screening", "policy_aggregator")
transfer_subgraph_builder.add_edge("parallel_ledger_verification", "policy_aggregator")

# 3. Downstream policy execution
transfer_subgraph_builder.add_conditional_edges(
    "policy_aggregator",
    route_after_policy,
    ["transfer_hitl", "execute_transfer", END]
)
transfer_subgraph_builder.add_edge("transfer_hitl", "execute_transfer")
transfer_subgraph_builder.add_edge("execute_transfer", END)

transfer_subgraph = transfer_subgraph_builder.compile()
